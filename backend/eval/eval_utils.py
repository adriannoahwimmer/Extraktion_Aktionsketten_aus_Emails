# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
eval_utils.py
--------------------------------------------------
Gemeinsame Hilfsfunktionen fuer die Auswertungsskripte in backend/eval/:
Pfade, Laden der Enron-Ketten, der Mails und der Cluster-Zuordnung sowie die
Zuordnung der Kettenquellen (sources[]) zu den Mails aus mails.jsonl.

Alle Auswertungsskripte lesen backend/chains/ nur; sie veraendern dort nichts.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BACKEND = EVAL_DIR.parent
PROJEKT = BACKEND.parent
CHAINS_DIR = BACKEND / "chains"
OUT_DIR = EVAL_DIR / "out"
MAILS_DATEI = BACKEND / "mails.jsonl"
CLUSTERS_DATEI = BACKEND / "clusters.jsonl"
VERARBEITET_DATEI = BACKEND / "verarbeitet.json"

sys.path.insert(0, str(BACKEND))
from mail_utils import lade_mails, dedupliziere, normalisiere_betreff  # noqa: E402

# Nur Enron-Ketten: chain_cluster_<cid>_<k>.json (Upload-Batches heissen chain_b..., manuelle chain_manuell_...)
KETTEN_MUSTER = re.compile(r"^chain_cluster_(.+)_(\d+)\.json$")

# Mindestpunktzahl (von 3) fuer die Zuordnung einer Quelle zu einer Mail, siehe bewerte_kandidat().
MIN_PUNKTE_CLUSTER = 1.5   # Kandidaten aus dem Cluster der Kette (die Mails, die das LLM gesehen hat)
MIN_PUNKTE_KORPUS = 2.5    # Rueckfall: Suche im gesamten Korpus (strenger, da viel mehr Kandidaten)


def utf8_ausgabe():
    """Konsolenausgabe auf UTF-8 stellen (Windows nutzt sonst cp1252)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def ws(text) -> str:
    """Whitespace-Normalisierung: alle Folgen von Leerraum -> ein Leerzeichen."""
    return " ".join(str(text or "").split())


def md_zelle(text, max_len=None) -> str:
    """Text fuer eine Markdown-Tabellenzelle (einzeilig, | maskiert)."""
    t = ws(text).replace("|", "\\|")
    if max_len and len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t


# ------------------------------------------------------------------
# Laden
# ------------------------------------------------------------------
def lade_enron_ketten():
    """Alle Enron-Ketten, sortiert nach Dateiname: [{slug, cid, k, datei, data}]."""
    ketten = []
    for datei in sorted(CHAINS_DIR.glob("chain_cluster_*.json")):
        m = KETTEN_MUSTER.match(datei.name)
        if not m:
            continue
        ketten.append({
            "slug": datei.stem,
            "cid": m.group(1),
            "k": int(m.group(2)),
            "datei": datei,
            "data": json.loads(datei.read_text(encoding="utf-8")),
        })
    return ketten


def lade_mails_dedup():
    """mails.jsonl, dedupliziert wie in cluster_mails.py/extract_chains.py."""
    return dedupliziere(lade_mails(MAILS_DATEI))


def lade_cluster_zuordnung():
    """clusters.jsonl als {mail_id: cluster_label}."""
    zuordnung = {}
    with open(CLUSTERS_DATEI, encoding="utf-8") as f:
        for zeile in f:
            if zeile.strip():
                e = json.loads(zeile)
                zuordnung[e["id"]] = e["cluster"]
    return zuordnung


def aufgabenknoten(kette):
    return [n for n in kette.get("nodes", []) if n.get("type") == "task"]


# ------------------------------------------------------------------
# Zuordnung sources[] -> Mail
# ------------------------------------------------------------------
_ADRESSE = re.compile(r"[\w.+'\-]+@[\w\-]+(?:\.[\w\-]+)+")


def _adressen(text) -> set:
    return {a.lower() for a in _ADRESSE.findall(str(text or ""))}


def _betreff_norm(text) -> str:
    return ws(normalisiere_betreff(str(text or ""))).casefold()


def parse_datum(text):
    """-> (datetime, mit_uhrzeit) oder (None, False). Versteht RFC 2822 (Mail-Header),
    ISO 8601 und TT.MM.JJJJ - so, wie das LLM Datumsangaben uebernimmt."""
    t = ws(text)
    if not t:
        return None, False
    try:
        d = parsedate_to_datetime(t)
        if d is not None:
            return d, True
    except (TypeError, ValueError, IndexError):
        pass
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return d, len(t) > 10
    except ValueError:
        pass
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t)
    if m:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))), False
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))), False
    return None, False


class MailIndex:
    """Vorberechnete Vergleichsmerkmale aller (deduplizierten) Mails."""

    def __init__(self, mails, zuordnung):
        self.mails = {m["id"]: m for m in mails}
        self.zuordnung = zuordnung
        self.nach_cluster = {}
        for m in mails:
            self.nach_cluster.setdefault(zuordnung.get(m["id"]), []).append(m["id"])
        self.merkmale = {
            m["id"]: {
                "betreff": _betreff_norm(m.get("subject")),
                "von": str(m.get("from") or "").casefold(),
                "adressen": _adressen(m.get("from")),
                "an": _adressen(m.get("to")),
                "datum": parse_datum(m.get("date"))[0],
            }
            for m in mails
        }
        self._body_ws = {}

    def body_ws(self, mail_id) -> str:
        if mail_id not in self._body_ws:
            self._body_ws[mail_id] = ws(self.mails[mail_id].get("body"))
        return self._body_ws[mail_id]

    def cluster_mail_ids(self, cid: str):
        """Mails, die das LLM fuer diese Gruppe gesehen hat. cid 'e<nr>' = Einzelmail mail_<nr>."""
        if cid.startswith("e"):
            mid = f"mail_{cid[1:]}"
            return [mid] if mid in self.mails else []
        try:
            return self.nach_cluster.get(int(cid), [])
        except ValueError:
            return []


def bewerte_kandidat(quelle, merkmale):
    """Punkte (0..3) fuer die Uebereinstimmung einer Quelle (sources[]-Eintrag) mit
    einer Mail: je bis zu 1 Punkt fuer Betreff, Absender und Datum."""
    punkte = 0.0

    b = _betreff_norm(quelle.get("subject"))
    if b and b == merkmale["betreff"]:
        punkte += 1.0
    elif b and len(b) >= 8 and (b in merkmale["betreff"] or merkmale["betreff"] in b) and merkmale["betreff"]:
        punkte += 0.6

    von = str(quelle.get("from") or "")
    adr = _adressen(von)
    if adr and adr & merkmale["adressen"]:
        punkte += 1.0
    elif not adr:
        teile = [t for t in re.split(r"[^\w]+", von.casefold()) if len(t) >= 3]
        if teile and all(t in merkmale["von"] for t in teile):
            punkte += 0.8

    dq, mit_zeit = parse_datum(quelle.get("date"))
    dm = merkmale["datum"]
    if dq is not None and dm is not None:
        if mit_zeit and dq.tzinfo is not None and dm.tzinfo is not None and abs(dq - dm) < timedelta(minutes=1):
            punkte += 1.0
        elif dq.date() == dm.date():
            punkte += 0.8
        elif abs((dq.date() - dm.date()).days) <= 1:
            punkte += 0.4
    return punkte


def _empfaenger_treffer(quelle, merkmale) -> float:
    """Anteil der Empfaengeradressen der Quelle, die bei der Mail vorkommen (Gleichstandsaufloesung)."""
    adr = _adressen(quelle.get("to"))
    return len(adr & merkmale["an"]) / len(adr) if adr else 0.0


def ordne_quelle_zu(quelle, cid, index: MailIndex):
    """Ordnet einen sources[]-Eintrag einer Mail zu (Absender, Datum, Betreff;
    bei Gleichstand zusaetzlich die Empfaenger). Der Belegtext (span) wird bewusst
    nicht verwendet, damit die anschliessende Belegpruefung unabhaengig bleibt.

    Gesucht wird zuerst unter den Mails des Clusters der Kette (die Eingabe des
    LLM), nur wenn dort nichts passt im gesamten Korpus.
    Rueckgabe: {status, mail_ids, punkte} mit status in
      'eindeutig' | 'mehrdeutig' | 'ausserhalb_cluster' | 'nicht_zuordenbar'.
    'mehrdeutig': mehrere Mails passen gleich gut (meist gleicher Absender und
    Betreff am selben Tag, wenn das LLM das Datum ohne Uhrzeit uebernommen hat)."""
    def beste(kandidaten):
        bewertet = [(bewerte_kandidat(quelle, index.merkmale[mid]), mid) for mid in kandidaten]
        if not bewertet:
            return 0.0, []
        top = max(p for p, _ in bewertet)
        ids = [mid for p, mid in bewertet if p == top]
        if len(ids) > 1:
            an = {mid: _empfaenger_treffer(quelle, index.merkmale[mid]) for mid in ids}
            bestes_an = max(an.values())
            ids = [mid for mid in ids if an[mid] == bestes_an]
        return top, ids

    punkte, ids = beste(index.cluster_mail_ids(cid))
    if punkte >= MIN_PUNKTE_CLUSTER:
        return {"status": "eindeutig" if len(ids) == 1 else "mehrdeutig", "mail_ids": ids, "punkte": punkte}

    punkte_k, ids_k = beste(index.mails.keys())
    if punkte_k >= MIN_PUNKTE_KORPUS:
        return {"status": "ausserhalb_cluster", "mail_ids": ids_k, "punkte": punkte_k}
    return {"status": "nicht_zuordenbar", "mail_ids": [], "punkte": max(punkte, punkte_k)}


def ordne_kette_zu(kette, cid, index: MailIndex):
    """{source_id: Zuordnung} fuer alle sources[] einer Kette."""
    return {q.get("id"): ordne_quelle_zu(q, cid, index) for q in kette.get("sources", [])}
