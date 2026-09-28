"""
parse_mailbox.py
--------------------------------------------------
Wandelt hochgeladene Postfach-Dateien in mails.jsonl um - dasselbe Schema,
das auch prepare_emails.py (Enron-CSV) erzeugt:

    { "id", "from", "to", "date", "subject", "subject_norm", "body" }

Unterstuetzte Formate (im Ordner <batch-dir>/upload/):
  .eml    - einzelne RFC822-Mail          (stdlib email)
  .mbox   - Gmail Takeout / Thunderbird   (stdlib mailbox)
  .zip    - enthaelt .eml / .mbox / .pst  (wird entpackt, dann rekursiv)
  .pst    - Outlook                        (bevorzugt ueber backend/tools/pst
            - reines JavaScript "pst-extractor", braucht nur Node; Rueckfall:
            externes 'readpst' aus libpst)

Mails, die nur einen HTML-Teil haben (kein text/plain), werden zu Text
umgewandelt statt verworfen.

Ausfuehren:
    python parse_mailbox.py --batch-dir batches/<batch_id>

Das Verzeichnis muss <batch-dir>/upload/ mit den Rohdateien enthalten.
Ergebnis: <batch-dir>/mails.jsonl
"""

import argparse
import email
import json
import mailbox
import re
import shutil
import subprocess
import tempfile
import zipfile
from email import policy
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path

from mail_utils import normalisiere_betreff, saeubere_body

HIER = Path(__file__).parent
PST_TOOL_DIR = HIER / "tools" / "pst"   # Node-Werkzeug fuer .pst (pst_to_jsonl.js)

MIN_BODY_LEN = 40          # zu kurze Mails ueberspringen
MAX_MAILS = 20000          # harte Obergrenze pro Batch

# Windows: Unterprozesse (node, npm, readpst) ohne aufpoppendes Konsolenfenster.
_KEIN_FENSTER = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _HtmlZuText(HTMLParser):
    """Sehr einfache HTML -> Text-Umwandlung (Skripte/Styles raus, Absaetze
    werden zu Zeilenumbruechen)."""

    _BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.teile.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.teile.append(data)


def html_zu_text(html: str) -> str:
    if not html:
        return ""
    parser = _HtmlZuText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    text = "".join(parser.teile).replace("\xa0", " ")
    zeilen = [re.sub(r"[ \t]+", " ", z).strip() for z in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(zeilen)).strip()


def _text_aus_part(teil: Message) -> str:
    try:
        inhalt = teil.get_content()
        return inhalt if isinstance(inhalt, str) else str(inhalt)
    except Exception:
        payload = teil.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return ""


def _body_aus_message(msg: Message) -> str:
    """Bevorzugt den text/plain-Teil; gibt es keinen, wird der HTML-Teil zu
    Text umgewandelt."""
    plain, html = "", ""
    teile = msg.walk() if msg.is_multipart() else [msg]
    for teil in teile:
        if teil.is_multipart() or teil.get_filename():
            continue
        typ = teil.get_content_type()
        if typ == "text/plain" and not plain.strip():
            plain = _text_aus_part(teil)
        elif typ == "text/html" and not html.strip():
            html = _text_aus_part(teil)
    if plain.strip():
        return plain
    return html_zu_text(html)


def _eintrag_aus_message(msg: Message):
    """Ein Message-Objekt -> mails.jsonl-Eintrag (ohne id) oder None."""
    body = saeubere_body(_body_aus_message(msg))
    if len(body) < MIN_BODY_LEN:
        return None
    betreff = msg.get("Subject", "") or ""
    return {
        "from": msg.get("From", "") or "",
        "to": msg.get("To", "") or "",
        "date": msg.get("Date", "") or "",
        "subject": betreff,
        "subject_norm": normalisiere_betreff(betreff),
        "body": body,
    }


def _lies_eml(pfad: Path):
    try:
        roh = pfad.read_bytes().lstrip(b"\xef\xbb\xbf")  # evtl. UTF-8-BOM weg
        msg = email.message_from_bytes(roh, policy=policy.default)
    except Exception as e:
        print(f"  uebersprungen ({pfad.name}): {e}")
        return
    eintrag = _eintrag_aus_message(msg)
    if eintrag:
        yield eintrag


def _lies_mbox(pfad: Path):
    box = mailbox.mbox(str(pfad), factory=None)
    for key in box.iterkeys():
        try:
            roh = box.get_bytes(key)
            msg = email.message_from_bytes(roh, policy=policy.default)
        except Exception as e:
            print(f"  Mail in {pfad.name} uebersprungen: {e}")
            continue
        eintrag = _eintrag_aus_message(msg)
        if eintrag:
            yield eintrag


def _pst_node_bereit() -> bool:
    """Node-Werkzeug fuer .pst benutzbar? Installiert die Abhaengigkeit
    (pst-extractor) beim ersten Mal automatisch per npm, falls sie fehlt."""
    if shutil.which("node") is None:
        return False
    if (PST_TOOL_DIR / "node_modules" / "pst-extractor").is_dir():
        return True
    npm = shutil.which("npm")
    if npm is None:
        return False
    print("  Installiere pst-extractor (einmalig, npm install) ...")
    try:
        subprocess.run(
            [npm, "install", "--no-audit", "--no-fund"], cwd=PST_TOOL_DIR,
            check=True, capture_output=True, text=True, creationflags=_KEIN_FENSTER,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"  npm install fehlgeschlagen: {e}")
        return False
    return (PST_TOOL_DIR / "node_modules" / "pst-extractor").is_dir()


def _lies_pst_node(pfad: Path):
    """pst_to_jsonl.js (reines JavaScript) liest die .pst direkt aus."""
    with tempfile.TemporaryDirectory(prefix="pst_") as tmp:
        ausgabe = Path(tmp) / "mails.jsonl"
        lauf = subprocess.run(
            ["node", str(PST_TOOL_DIR / "pst_to_jsonl.js"), str(pfad), str(ausgabe)],
            cwd=PST_TOOL_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", creationflags=_KEIN_FENSTER,
        )
        if lauf.stdout.strip():
            print(lauf.stdout.strip())
        if lauf.returncode != 0:
            raise RuntimeError(
                f"PST-Datei {pfad.name} konnte nicht gelesen werden: "
                f"{(lauf.stderr or lauf.stdout).strip()[:500]} "
                "(defekte oder passwortgeschuetzte PST?)"
            )
        with open(ausgabe, "r", encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if not zeile:
                    continue
                m = json.loads(zeile)
                body = m.get("body") or html_zu_text(m.get("body_html", ""))
                body = saeubere_body(body)
                if len(body) < MIN_BODY_LEN:
                    continue
                betreff = m.get("subject", "") or ""
                yield {
                    "from": m.get("from", ""),
                    "to": m.get("to", ""),
                    "date": m.get("date", ""),
                    "subject": betreff,
                    "subject_norm": normalisiere_betreff(betreff),
                    "body": body,
                }


def _lies_pst_readpst(pfad: Path):
    """Rueckfall: externes readpst (libpst) konvertiert die .pst in .eml-Dateien."""
    ziel = Path(tempfile.mkdtemp(prefix="pst_"))
    try:
        subprocess.run(
            ["readpst", "-e", "-D", "-o", str(ziel), str(pfad)],
            check=True, capture_output=True, text=True, creationflags=_KEIN_FENSTER,
        )
        for eml in sorted(ziel.rglob("*.eml")):
            yield from _lies_eml(eml)
    finally:
        shutil.rmtree(ziel, ignore_errors=True)


def _lies_pst(pfad: Path):
    if _pst_node_bereit():
        yield from _lies_pst_node(pfad)
    elif shutil.which("readpst") is not None:
        yield from _lies_pst_readpst(pfad)
    else:
        raise RuntimeError(
            "PST-Dateien brauchen Node.js (https://nodejs.org) - oder alternativ "
            "'readpst' (libpst) im PATH. Oder in Outlook nach .eml/.mbox exportieren."
        )


def _lies_zip(pfad: Path):
    ziel = Path(tempfile.mkdtemp(prefix="zip_"))
    try:
        with zipfile.ZipFile(pfad) as zf:
            zf.extractall(ziel)
        for datei in sorted(ziel.rglob("*")):
            if datei.is_file():
                yield from _lies_datei(datei)
    finally:
        shutil.rmtree(ziel, ignore_errors=True)


def _lies_datei(pfad: Path):
    endung = pfad.suffix.lower()
    if endung == ".eml":
        yield from _lies_eml(pfad)
    elif endung == ".mbox":
        yield from _lies_mbox(pfad)
    elif endung == ".pst":
        yield from _lies_pst(pfad)
    elif endung == ".zip":
        yield from _lies_zip(pfad)
    elif endung == "":
        # mbox aus Takeout heisst oft nur "All mail Including Spam and Trash"
        try:
            yield from _lies_mbox(pfad)
        except Exception:
            pass


def parse_upload(batch_dir: Path) -> int:
    upload_dir = batch_dir / "upload"
    if not upload_dir.is_dir():
        raise FileNotFoundError(f"{upload_dir} nicht gefunden.")

    dateien = sorted(p for p in upload_dir.iterdir() if p.is_file())
    if not dateien:
        raise FileNotFoundError(f"Keine Dateien in {upload_dir}.")

    ausgabe = batch_dir / "mails.jsonl"
    geschrieben = 0
    with open(ausgabe, "w", encoding="utf-8") as f_out:
        for datei in dateien:
            print(f"Lese {datei.name} ...")
            for eintrag in _lies_datei(datei):
                if geschrieben >= MAX_MAILS:
                    print(f"Obergrenze {MAX_MAILS} erreicht, Rest ignoriert.")
                    break
                eintrag["id"] = f"mail_{geschrieben:05d}"
                f_out.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
                geschrieben += 1

    print(f"Fertig. {geschrieben} Mails -> {ausgabe}")
    return geschrieben


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", required=True, type=Path)
    args = parser.parse_args()
    parse_upload(args.batch_dir)


if __name__ == "__main__":
    main()
