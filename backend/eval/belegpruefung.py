# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
belegpruefung.py
--------------------------------------------------
Schritt 2 der Auswertung: strikte Pruefung der Belegzitate (evidence) der
Enron-Ketten.

Fuer jeden evidence-Eintrag wird die Quelle (evidence.source -> sources[]) ueber
Absender, Datum und Betreff einer Mail aus mails.jsonl (dedupliziert) zugeordnet
(siehe eval_utils.ordne_quelle_zu). Dann wird geprueft, ob der span nach
Whitespace-Normalisierung woertlich (Gross-/Kleinschreibung und Satzzeichen
unveraendert) im Body DIESER Mail steht.

Ausgewiesen werden:
  - strikte Quote: span im Body der zugeordneten Quellmail
  - Quote gegen den Gesamtkorpus: span im Body irgendeiner Mail
  - zur Einordnung: Quote gegen die Mails des Clusters (die Eingabe des LLM)
Bei mehrdeutiger Zuordnung (mehrere Mails mit gleichem Absender, Betreff und Tag)
gilt ein Beleg als bestanden, wenn er in einer der Kandidatinnen steht; diese
Faelle werden getrennt gezaehlt.

Aufruf:  python belegpruefung.py
Ausgabe: out/belegpruefung.md, out/belegpruefung.csv (alle Belege)
"""

import csv
import re
from collections import Counter

import eval_utils as eu


_STEUERZEICHEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def ohne_steuerzeichen(text) -> str:
    """Unsichtbare Steuerzeichen entfernen (im Enron-Korpus z.B. \\x01 statt typografischer Anfuehrungszeichen)."""
    return eu.ws(_STEUERZEICHEN.sub("", str(text)))


def ohne_satzzeichen(text) -> str:
    return eu.ws(re.sub(r"[^\w\s]", " ", _STEUERZEICHEN.sub("", str(text)))).casefold()


def laengster_woertlicher_teil(span_ws, body_ws) -> int:
    """Laenge (in Woertern) der laengsten zusammenhaengenden Wortfolge des spans, die im Body steht."""
    woerter = span_ws.split()
    bester = 0
    for i in range(len(woerter)):
        for j in range(len(woerter), i + bester, -1):
            if " ".join(woerter[i:j]) in body_ws:
                bester = j - i
                break
    return bester


def fragmente_in_reihenfolge(span, body_ws) -> bool:
    """span mit Auslassung ('...' oder '…'): stehen alle Teile in dieser Reihenfolge im Body?"""
    teile = [eu.ws(t) for t in re.split(r"\.\.\.+|…", span) if eu.ws(t)]
    if len(teile) < 2:
        return False
    pos = 0
    for t in teile:
        pos = body_ws.find(t, pos)
        if pos < 0:
            return False
        pos += len(t)
    return True


def befund(span_ws, eintrag, index, korpus_ws, cluster_ids):
    """Heuristische Einordnung eines nicht bestandenen Belegs."""
    mail_ids = eintrag["mail_ids"]
    if eintrag["status_quelle"] == "fehlt":
        return "evidence.source verweist auf keine Quelle in sources[]"
    if eintrag["im_cluster"]:
        return "steht woertlich in einer anderen Mail desselben Clusters (Quellenangabe verweist auf andere Mail)"
    for mid in mail_ids:
        if span_ws and span_ws in eu.ws(index.mails[mid].get("subject")):
            return "steht im Betreff statt im Body"
    for mid in mail_ids:
        if span_ws and span_ws in ohne_steuerzeichen(index.mails[mid].get("body")):
            return "identisch bis auf unsichtbare Steuerzeichen im Original (Kodierungsartefakt)"
    for mid in mail_ids:
        if ohne_satzzeichen(span_ws) and ohne_satzzeichen(span_ws) in ohne_satzzeichen(index.body_ws(mid)):
            return "nur bis auf Gross-/Kleinschreibung bzw. Satzzeichen identisch"
    for mid in mail_ids:
        if fragmente_in_reihenfolge(span_ws, index.body_ws(mid)):
            return "Zitat mit Auslassung (...), Teile stehen woertlich in der Mail"
    if eintrag["im_korpus"]:
        return "steht nur in einer Mail ausserhalb des Clusters"
    if any(ohne_satzzeichen(span_ws) in ohne_satzzeichen(index.body_ws(mid)) for mid in cluster_ids if span_ws):
        return "im Cluster nur bis auf Gross-/Kleinschreibung bzw. Satzzeichen identisch"
    n_woerter = len(span_ws.split())
    teil = max((laengster_woertlicher_teil(span_ws, index.body_ws(mid)) for mid in mail_ids), default=0)
    if n_woerter and teil / n_woerter >= 0.5:
        return f"Wortlaut teilweise veraendert (laengster woertlicher Teil: {teil} von {n_woerter} Woertern)"
    return "nicht im Korpus (Paraphrase oder veraenderter Wortlaut)"


def pruefe(ketten, index):
    # Gesamtkorpus als ein String (Trennzeichen verhindert Treffer ueber Mailgrenzen).
    korpus_ws = "\x00".join(index.body_ws(mid) for mid in index.mails)
    ergebnisse = []
    for k in ketten:
        zuordnung = eu.ordne_kette_zu(k["data"], k["cid"], index)
        cluster_ids = index.cluster_mail_ids(k["cid"])
        cluster_ws = "\x00".join(index.body_ws(mid) for mid in cluster_ids)
        for n in eu.aufgabenknoten(k["data"]):
            for ev in n.get("evidence", []) or []:
                span_ws = eu.ws(ev.get("span"))
                z = zuordnung.get(ev.get("source"))
                mail_ids = z["mail_ids"] if z else []
                treffer = [mid for mid in mail_ids if span_ws and span_ws in index.body_ws(mid)]
                eintrag = {
                    "kette": k["slug"],
                    "knoten": n.get("id"),
                    "source": ev.get("source"),
                    "status_quelle": z["status"] if z else "fehlt",
                    "mail_ids": mail_ids,
                    "span": ev.get("span", ""),
                    "strikt": bool(treffer),
                    "im_cluster": bool(span_ws) and span_ws in cluster_ws,
                    "im_korpus": bool(span_ws) and span_ws in korpus_ws,
                }
                if not eintrag["strikt"]:
                    eintrag["befund"] = befund(span_ws, eintrag, index, korpus_ws, cluster_ids)
                ergebnisse.append(eintrag)
    return ergebnisse


def quote(teil, gesamt) -> str:
    return f"{teil}/{gesamt} ({teil / gesamt:.1%})" if gesamt else "0/0"


def main():
    eu.utf8_ausgabe()
    ketten = eu.lade_enron_ketten()
    index = eu.MailIndex(eu.lade_mails_dedup(), eu.lade_cluster_zuordnung())
    erg = pruefe(ketten, index)

    n = len(erg)
    strikt = sum(e["strikt"] for e in erg)
    korpus = sum(e["im_korpus"] for e in erg)
    cluster = sum(e["im_cluster"] for e in erg)
    eindeutig = [e for e in erg if e["status_quelle"] == "eindeutig"]
    mehrdeutig = [e for e in erg if e["status_quelle"] == "mehrdeutig"]
    quellen_status = Counter(e["status_quelle"] for e in erg)
    fehler = [e for e in erg if not e["strikt"]]
    befunde = Counter(e["befund"] for e in fehler)

    # Knotenebene: Aufgabenknoten, deren Belege alle bzw. mindestens einer bestehen
    je_knoten = {}
    for e in erg:
        je_knoten.setdefault((e["kette"], e["knoten"]), []).append(e["strikt"])
    knoten_alle = sum(all(v) for v in je_knoten.values())
    knoten_einer = sum(any(v) for v in je_knoten.values())

    md = [
        "# Strikte Belegpruefung der Enron-Ketten",
        "",
        "Pruefung: steht der `span` nach Whitespace-Normalisierung woertlich im Body der Quellmail "
        "(Gross-/Kleinschreibung und Satzzeichen unveraendert)? Die Quellmail wird ueber "
        "`sources[].from/date/subject` (bei Gleichstand zusaetzlich `to`) unter den Mails des "
        "Clusters der Kette gesucht, im Rueckfall im gesamten Korpus (`mails.jsonl`, dedupliziert); "
        "der span selbst wird fuer die Zuordnung nicht verwendet.",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Belege (evidence-Eintraege) | {n} in {len(je_knoten)} Aufgabenknoten, {len(ketten)} Ketten |",
        f"| Zuordnung der Quelle | eindeutig {quellen_status['eindeutig']}, mehrdeutig {quellen_status['mehrdeutig']}, "
        f"ausserhalb des Clusters {quellen_status['ausserhalb_cluster']}, nicht zuordenbar "
        f"{quellen_status['nicht_zuordenbar']}, Quelle fehlt {quellen_status['fehlt']} |",
        f"| **Quote strikt** (span in der zugeordneten Quellmail) | **{quote(strikt, n)}** |",
        f"| davon nur eindeutig zugeordnete Belege | {quote(sum(e['strikt'] for e in eindeutig), len(eindeutig))} |",
        f"| davon mehrdeutig zugeordnete Belege (bestanden, wenn in einer Kandidatin) | "
        f"{quote(sum(e['strikt'] for e in mehrdeutig), len(mehrdeutig))} |",
        f"| **Quote gegen den Gesamtkorpus** (span in irgendeiner Mail) | **{quote(korpus, n)}** |",
        f"| zur Einordnung: span in einer Mail des Clusters (Eingabe des LLM) | {quote(cluster, n)} |",
        f"| Aufgabenknoten, deren Belege alle bestehen | {quote(knoten_alle, len(je_knoten))} |",
        f"| Aufgabenknoten mit mindestens einem bestandenen Beleg | {quote(knoten_einer, len(je_knoten))} |",
        "",
        f"## Fehlschlaege ({len(fehler)})",
        "",
        "Befund = heuristische Einordnung, warum der Beleg die strikte Pruefung nicht besteht.",
        "",
        *[f"- {b}: {c}" for b, c in befunde.most_common()],
        "",
        "| Kette | Knoten | Quelle → Mail | Span | Befund |",
        "|---|---|---|---|---|",
        *[f"| {e['kette']} | {e['knoten']} | {e['source']} → {', '.join(e['mail_ids']) or '–'} | "
          f"{eu.md_zelle(e['span'])} | {e['befund']} |" for e in fehler],
    ]

    eu.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (eu.OUT_DIR / "belegpruefung.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with open(eu.OUT_DIR / "belegpruefung.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["kette", "knoten", "source", "zuordnung", "mail_ids", "strikt", "im_cluster", "im_korpus", "befund", "span"])
        for e in erg:
            w.writerow([e["kette"], e["knoten"], e["source"], e["status_quelle"], " ".join(e["mail_ids"]),
                        int(e["strikt"]), int(e["im_cluster"]), int(e["im_korpus"]), e.get("befund", ""), e["span"]])
    print("\n".join(md))


if __name__ == "__main__":
    main()
