# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
zusammenfassung.py
--------------------------------------------------
Fasst die Ergebnisse der Auswertungsschritte in out/ZUSAMMENFASSUNG.md zusammen
(Abschnitte: Kennzahlen, Belegpruefung, Token-Kompression, Burnet, Herkunft der
Ketten, Smoke-Test). Liest nur die Ergebnisdateien in out/ und rechnet nichts neu;
vorher muessen die Schritte 1-4, 7 und 8 gelaufen sein.

Aufruf:  python zusammenfassung.py
"""

import csv
import json
import statistics as st
import sys
from datetime import datetime

import eval_utils as eu
from kennzahlen import BESCHRIFTUNG

BENOETIGT = ["kennzahlen.json", "belegpruefung.csv", "token_kompression.csv", "burnet.json",
             "herkunft_ketten.json", "smoke_test.md"]


def lies_json(name):
    return json.loads((eu.OUT_DIR / name).read_text(encoding="utf-8"))


def lies_csv(name):
    with open(eu.OUT_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def quote(teil, gesamt):
    return f"{teil}/{gesamt} ({teil / gesamt:.1%})"


def fmt(x):
    return f"{x:g}" if isinstance(x, float) else str(x)


def abschnitt_kennzahlen():
    k = lies_json("kennzahlen.json")
    werte = {**k["ketten"], **k["clustering"]}
    zeilen, abweichungen = [], []
    for schluessel, text in BESCHRIFTUNG.items():
        soll, ist = k["referenz"].get(schluessel), werte.get(schluessel)
        if soll is None:
            status = "– (kein Sollwert)"
        elif soll == ist:
            status = "✓"
        else:
            status = "⚠ **Abweichung**"
            abweichungen.append(f"{text}: Soll {fmt(soll)}, Ist {fmt(ist)}")
        zeilen.append(f"| {text} | {fmt(soll) if soll is not None else '–'} | {fmt(ist)} | {status} |")
    return [
        "## 1. Kennzahlen",
        "",
        "Soll = Werte aus dem Berichtsentwurf, Ist = berechnet aus `backend/chains/chain_cluster_*.json` "
        "und `backend/clusters.jsonl` (`kennzahlen.py`).",
        "",
        "| Kennzahl | Soll | Ist | Status |",
        "|---|---|---|---|",
        *zeilen,
        "",
        "**Abweichungen:** " + ("keine." if not abweichungen else ""),
        *[f"- {a}" for a in abweichungen],
    ]


def abschnitt_belege():
    belege = lies_csv("belegpruefung.csv")
    n = len(belege)
    strikt = sum(int(b["strikt"]) for b in belege)
    korpus = sum(int(b["im_korpus"]) for b in belege)
    eindeutig = [b for b in belege if b["zuordnung"] == "eindeutig"]
    mehrdeutig = [b for b in belege if b["zuordnung"] == "mehrdeutig"]
    fehler = [b for b in belege if b["strikt"] == "0"]
    return [
        "## 2. Belegpruefung",
        "",
        "Pruefung je evidence-Eintrag: steht der `span` nach Whitespace-Normalisierung woertlich im Body der "
        "Quellmail? Die Quellmail wird ueber `sources[].from/date/subject` (bei Gleichstand `to`) zugeordnet "
        "(`belegpruefung.py`).",
        "",
        f"- **Quote strikt (in der zugeordneten Quellmail): {quote(strikt, n)}**",
        f"- **Quote gegen den Gesamtkorpus (in irgendeiner Mail): {quote(korpus, n)}**",
        f"- Zuordnung der Quellmail: {len(eindeutig)} eindeutig, {len(mehrdeutig)} mehrdeutig (gleicher Absender, "
        f"Betreff und Tag; bestanden, wenn der span in einer der Kandidatinnen steht). Nur eindeutig zugeordnete "
        f"Belege: {quote(sum(int(b['strikt']) for b in eindeutig), len(eindeutig))}.",
        "",
        f"Alle Fehlschlaege der strikten Pruefung ({len(fehler)}):",
        "",
        "| Kette | Knoten | Quelle → Mail | Span | Befund |",
        "|---|---|---|---|---|",
        *[f"| {b['kette']} | {b['knoten']} | {b['source']} → {b['mail_ids'].replace(' ', ', ') or '–'} | "
          f"{eu.md_zelle(b['span'])} | {b['befund']} |" for b in fehler],
    ]


def abschnitt_token():
    zeilen = lies_csv("token_kompression.csv")
    r_a = [float(z["verhaeltnis_json"]) for z in zeilen]
    r_b = [float(z["verhaeltnis_text"]) for z in zeilen]
    s_q = sum(int(z["tokens_quellmails"]) for z in zeilen)
    s_a = sum(int(z["tokens_json"]) for z in zeilen)
    s_b = sum(int(z["tokens_titel_zus_aktionen"]) for z in zeilen)
    return [
        "## 3. Token-Kompression",
        "",
        f"Tokens je Kette ({len(zeilen)} Ketten) im Verhaeltnis zu ihren Quellmails (Betreff + Body der in "
        "`sources[]` genannten Mails). Tokenizer: tiktoken `cl100k_base` als **Naeherung** – Claude nutzt einen "
        "eigenen Tokenizer (`token_kompression.py`).",
        "",
        "| | (a) vollstaendiges JSON | (b) Titel, Summary, Aktionen |",
        "|---|---|---|",
        f"| Median Verhaeltnis Kette/Quellmails | {st.median(r_a):.2f} | {st.median(r_b):.2f} |",
        f"| Summe Tokens Kette | {s_a:,} | {s_b:,} |",
        f"| Summe Tokens Quellmails | {s_q:,} | {s_q:,} |",
        f"| Verhaeltnis der Summen | {s_a / s_q:.2f} | {s_b / s_q:.2f} |",
    ]


def abschnitt_burnet():
    b = lies_json("burnet.json")
    mails = {m["cluster"]: m for m in b["burnet_mails"]}
    cluster_txt = "; ".join(
        f"**{c}** ({mails[c]['mail_id']} „{mails[c]['betreff']}“, {b['cluster_groessen'][str(c)]} Mails im Cluster)"
        for c in b["cluster_ids"])
    uebrige = [q for q in b["gold_quellen"] if not set(q["cluster"]) & set(b["cluster_ids"])]
    if b["kette_vorhanden_in_chains"]:
        vorhanden = "ja – vorhandene Kette(n) aus `backend/chains/` verwendet."
    else:
        ex = b.get("extraktion") or {}
        vorhanden = (f"nein – neu extrahiert ueber `NUR_CLUSTER = {set(b['cluster_ids'])}` "
                     f"({ex.get('modell', '?')}, {ex.get('zeit', '?')}); Ausgabe in `out/burnet/`, "
                     "`backend/chains/` unveraendert.")
    g = b["gold"]
    tabelle = [f"| Gold (`examples/gold_burnet.json`) | {g['knoten']} ({g['aufgaben']}/{g['gateways']}) | {g['kanten']} |"]
    tabelle += [f"| extrahiert: {e['kette']} (Cluster {e['cluster']}) | {e['knoten']} ({e['aufgaben']}/{e['gateways']}) | "
                f"{e['kanten']} |" for e in b["extrahiert"]]
    if len(b["extrahiert"]) > 1:
        tabelle.append(f"| extrahiert gesamt ({len(b['extrahiert'])} Ketten) | {sum(e['knoten'] for e in b['extrahiert'])} | "
                       f"{sum(e['kanten'] for e in b['extrahiert'])} |")
    direkt = sum(1 for k in b["gold_kanten"] if k["status"].startswith("direkt"))
    vorschlag = ", ".join(f"{g_id} → {v['kette'].replace('chain_cluster_', '')} {v['knoten']} ({v['aehnlichkeit']})"
                          for g_id, v in b["zuordnung_vorschlag"].items())
    return [
        "## 4. Burnet",
        "",
        f"- **Cluster-ID:** Die Burnet-Mails (Suche ueber `BURNET_PHRASEN`) liegen in {len(b['cluster_ids'])} "
        f"Cluster(n): {cluster_txt}."
        + (" Die Mails liegen also in verschiedenen Clustern (Akzeptanztest nicht bestanden)." if len(b["cluster_ids"]) > 1 else "")
        + ("" if not uebrige else " Weitere Gold-Quelle ausserhalb davon: "
           + "; ".join(f"{q['id']} „{q['betreff']}“ in Cluster {', '.join(map(str, q['cluster']))}" for q in uebrige) + "."),
        f"- **Kette vorhanden:** {vorhanden}",
        "",
        "| Kette | Knoten (Aufgaben/Gateways) | Kanten |",
        "|---|---|---|",
        *tabelle,
        "",
        f"- Zuordnungsvorschlag (automatisch, noch zu bestaetigen in `burnet_vergleich.md`): "
        f"{len(b['zuordnung_vorschlag'])}/{g['knoten']} Gold-Knoten mit Entsprechung ({vorschlag or '–'}), "
        f"{direkt}/{g['kanten']} Gold-Kanten direkt wiedergefunden.",
    ]


def abschnitt_herkunft():
    h = lies_json("herkunft_ketten.json")
    p = h.get("protokoll") or {}
    v2_seit = next((z for z, t in p.get("zeitleiste", []) if "v2" in t), None)
    uploads_v2 = [u for u in h["upload_logs"] if u["v2_ausgabe"]]
    uploads_sonnet = [u for u in h["upload_logs"] if "google.claude-sonnet-5" in u["modelle"]]
    modell = p.get("model_bei_laufbeginn") or "nicht bestimmbar"
    zeilen = [
        "## 5. Herkunft der 51 Ketten",
        "",
        f"**Prompt-Version: v2** (Ausgabe `{{\"chains\": [...]}}`) – belegt:",
        f"- Formatmerkmale, die nur der v2-Code erzeugt: Dateiname `chain_cluster_<cid>_<k>.json` "
        f"{h['dateiname_mit_k']}/{h['ketten']}, `id` = `cluster_<cid>_<k>` {h['id_passt']}/{h['ketten']}, "
        f"{h['cluster_mit_mehreren_ketten']} Cluster mit mehreren Ketten; Ausgabe-Gate von v2 (p >= 0.4 und >= 2 "
        f"Aufgabenknoten) {h['gate_erfuellt']}/{h['ketten']}.",
        f"- Upload-Logs vor dem Enron-Lauf mit v2-Ausgabe („Kette(n) erkannt“): "
        + (", ".join(f"{u['batch']} ({u['zeit']})" for u in uploads_v2) or "keine") + ".",
    ]
    if p:
        zeilen.append(f"- Claude-Code-Protokolle: v2-Ausgabeformat seit {v2_seit or '?'}; letzte Prompt-Aenderung vor "
                      f"dem Lauf {p.get('letzte_prompt_aenderung_vor_lauf')}; Prompt-Aenderungen nach dem Lauf: "
                      f"{p.get('prompt_aenderungen_nach_lauf')} – der Prompt im Repository ist der verwendete.")
    zeilen += [
        "",
        f"**Modell: {modell}** – indirekt belegt (die Ketten speichern das Modell nicht):",
    ]
    if p:
        zeilen.append(f"- Claude-Code-Protokolle: Standardwert von `MODEL` in `extract_chains.py` seit "
                      f"{p.get('model_gesetzt_am')} `{modell}`; Aenderungen am Standardwert nach dem Lauf: "
                      f"{p.get('model_aenderungen_nach_lauf')}.")
    zeilen += [
        f"- Upload-Laeufe kurz vor dem Enron-Lauf nutzten `google.claude-sonnet-5`: "
        + (", ".join(f"{u['batch']} ({u['zeit']})" for u in uploads_sonnet) or "keine") + ".",
        "- Einschraenkung: Ein ueber die Umgebungsvariable `EXTRACT_MODEL` gesetztes anderes Modell waere nirgends "
        "protokolliert; Aenderungen ausserhalb von Claude Code (z.B. im Editor) enthalten die Protokolle nicht.",
        "",
        "**Zeitpunkt und Lauf (Dateidaten):** Ketten-Dateien "
        f"{h['ketten_von']} bis {h['ketten_bis']}, nach `clusters.jsonl` ({h['clusters_jsonl']}); alle "
        f"{h['in_verarbeitet']}/{h['ketten']} Cluster-IDs stehen in `verarbeitet.json` ({h['verarbeitet_json']}), "
        "d.h. die Ketten stammen aus dem `--alle`-Lauf.",
        "",
        f"**git:** keine Aussage moeglich – alle Ketten kamen mit dem ersten Commit `{h['git_commit_ketten']}` ins "
        "Repository, der den gesamten Projektstand auf einmal enthaelt.",
    ]
    return zeilen


def abschnitt_smoke():
    text = (eu.OUT_DIR / "smoke_test.md").read_text(encoding="utf-8")
    zeilen = text.splitlines()
    # Absatz "Lauf vom ..." (kann ueber mehrere Zeilen umbrochen sein)
    i_lauf = next((i for i, z in enumerate(zeilen) if z.startswith("Lauf vom")), None)
    lauf = []
    if i_lauf is not None:
        for z in zeilen[i_lauf:]:
            if not z.strip():
                break
            lauf.append(z.strip())
    start = next((i for i, z in enumerate(zeilen) if z.startswith("| Schritt")), len(zeilen))
    ende = next((i for i in range(start, len(zeilen)) if not zeilen[i].startswith("|")), len(zeilen))
    fehler_start = next((i for i, z in enumerate(zeilen) if z.startswith("**Fehler:")), None)
    bestanden = fehler_start is not None and zeilen[fehler_start].startswith("**Fehler: keine")
    return [
        "## 6. Smoke-Test",
        "",
        f"- **Bestanden: {'ja' if bestanden else 'nein'}** – frischer Klon von GitHub, Installation nach README, "
        "Build und Pipeline-Lauf auf `examples/beispiel_postfach.mbox`.",
        f"- **Fehlermeldungen:** {'keine' if bestanden else 'siehe unten'}",
        f"- {' '.join(lauf)}" if lauf else "",
        "",
        *zeilen[start:ende],
        "",
        *(zeilen[fehler_start:] if fehler_start is not None else []),
    ]


def main():
    eu.utf8_ausgabe()
    fehlend = [n for n in BENOETIGT if not (eu.OUT_DIR / n).exists()]
    if fehlend:
        print("Es fehlen Ergebnisdateien in out/: " + ", ".join(fehlend) + " - erst die Auswertungsschritte ausfuehren.")
        sys.exit(1)

    md = [
        "# Zusammenfassung der Auswertung",
        "",
        f"Erzeugt am {datetime.now():%Y-%m-%d %H:%M} von `backend/eval/zusammenfassung.py` aus den Ergebnisdateien "
        "in `backend/eval/out/` (Details dort).",
        "",
        *abschnitt_kennzahlen(), "",
        *abschnitt_belege(), "",
        *abschnitt_token(), "",
        *abschnitt_burnet(), "",
        *abschnitt_herkunft(), "",
        *abschnitt_smoke(),
    ]
    (eu.OUT_DIR / "ZUSAMMENFASSUNG.md").write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
