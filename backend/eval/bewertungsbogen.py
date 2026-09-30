# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
bewertungsbogen.py
--------------------------------------------------
Schritt 5 der Auswertung: Unterlagen fuer die manuelle Bewertung der Enron-Ketten.

  - out/bewertung.csv: eine Zeile je Kette mit den Spalten
        chain_id; k1; n_tasks; tasks_korrekt; n_edges; edges_korrekt; notiz
    vorausgefuellt sind chain_id, n_tasks (Aufgabenknoten) und n_edges (Kanten),
    die Bewertungsspalten bleiben leer. Urteil in k1: U = korrekt, uebertragbares
    Verfahren; E = korrekt, einmaliger Vorgang; F = fehlerhaft (tasks_korrekt,
    edges_korrekt und notiz optional). Trennzeichen ';', UTF-8 mit BOM (oeffnet
    sich direkt in Excel).
  - out/bewertung/NN_<chain_id>.md: je Kette Titel, Zusammenfassung, Knoten
    (Aktion, Akteur, Beleg), Kanten mit Bedingung und die vollstaendigen
    Quellmails (gesaeuberter Text, wie ihn das LLM gesehen hat).

Reihenfolge zufaellig mit festem Seed (SEED), damit die Bewertung nicht der
Clusterreihenfolge folgt. prozess_wahrscheinlichkeit und prozess_begruendung
werden bewusst NICHT angezeigt (Blindbewertung).

Eine vorhandene bewertung.csv wird nicht ueberschrieben (sie koennte bereits
ausgefuellt sein); dafuer --ueberschreiben angeben.

Aufruf:  python bewertungsbogen.py [--ueberschreiben]
"""

import argparse
import csv
import random
import sys

import eval_utils as eu

SEED = 42
CSV_DATEI = eu.OUT_DIR / "bewertung.csv"
MD_ORDNER = eu.OUT_DIR / "bewertung"
SPALTEN = ["chain_id", "k1", "n_tasks", "tasks_korrekt", "n_edges", "edges_korrekt", "notiz"]
URTEILE = "U = korrekt, uebertragbares Verfahren; E = korrekt, einmaliger Vorgang; F = fehlerhaft"


def akteur(kette, aid):
    if not aid:
        return ""
    a = next((x for x in kette.get("actors", []) if x.get("id") == aid), None)
    return f"{a.get('name', aid)} ({aid})" if a else aid


def kurz(kette, nid):
    n = next((x for x in kette.get("nodes", []) if x.get("id") == nid), None)
    if n is None:
        return f"{nid} (unbekannter Knoten)"
    text = n.get("action") if n.get("type") == "task" else f"◇ {n.get('label', '')}"
    return f"{nid}: {eu.md_zelle(text, 80)}"


def markdown(nr, eintrag, index):
    kette, slug, cid = eintrag["data"], eintrag["slug"], eintrag["cid"]
    tasks = eu.aufgabenknoten(kette)
    flows = kette.get("flows", [])
    zuordnung = eu.ordne_kette_zu(kette, cid, index)
    quellen = {q.get("id"): q for q in kette.get("sources", [])}

    md = [
        f"# {nr:02d} · {slug}",
        "",
        f"Bewertung in `bewertung.csv`, Zeile `{slug}`: **k1** ({URTEILE}); optional tasks_korrekt "
        f"(von {len(tasks)}), edges_korrekt (von {len(flows)}), notiz.",
        "",
        f"## {kette.get('title', '(ohne Titel)')}",
        "",
        kette.get("summary", ""),
        "",
        "## Knoten",
        "",
    ]
    for n in kette.get("nodes", []):
        if n.get("type") == "gateway":
            md += [f"**{n.get('id')} · Entscheidung ({n.get('gateway_type', '?')})** – {n.get('label', '')}", ""]
            continue
        md.append(f"**{n.get('id')} · Aufgabe** – {n.get('action', '')}")
        emp = akteur(kette, n.get("recipient"))
        md.append(f"- Akteur: {akteur(kette, n.get('actor')) or '–'}" + (f" → {emp}" if emp else ""))
        belege = n.get("evidence") or []
        if not belege:
            md.append("- Beleg: –")
        for ev in belege:
            md.append(f"- Beleg [{ev.get('source')}]: „{eu.ws(ev.get('span'))}“")
        md.append("")

    md += ["## Kanten", ""]
    if flows:
        md += ["| von | nach | Bedingung |", "|---|---|---|"]
        md += [f"| {kurz(kette, f.get('from'))} | {kurz(kette, f.get('to'))} | {eu.md_zelle(f.get('condition')) or '–'} |"
               for f in flows]
    else:
        md.append("keine")

    md += ["", "## Quellmails", ""]
    for sid, q in quellen.items():
        z = zuordnung.get(sid, {"status": "nicht_zuordenbar", "mail_ids": []})
        if not z["mail_ids"]:
            md += [f"### {sid} – Mail nicht zuordenbar",
                   f"Angabe in der Kette: {q.get('from', '')} · {q.get('date', '')} · {q.get('subject', '')}", ""]
            continue
        hinweis = " (mehrdeutig: mehrere Mails passen zu Absender, Datum und Betreff)" if z["status"] == "mehrdeutig" else ""
        for mid in z["mail_ids"]:
            m = index.mails[mid]
            md += [
                f"### {sid} → {mid}{hinweis}",
                "",
                f"- Von: {m.get('from', '')}",
                f"- An: {eu.ws(m.get('to', ''))}",
                f"- Datum: {m.get('date', '')}",
                f"- Betreff: {m.get('subject', '')}",
                "",
                "~~~~text",
                m.get("body", "").replace("~~~~", "~ ~ ~ ~"),
                "~~~~",
                "",
            ]
    return "\n".join(md) + "\n"


def main():
    eu.utf8_ausgabe()
    parser = argparse.ArgumentParser(description="Bewertungsbogen erzeugen (siehe Modul-Docstring).")
    parser.add_argument("--ueberschreiben", action="store_true", help="vorhandene bewertung.csv ersetzen")
    args = parser.parse_args()
    if CSV_DATEI.exists() and not args.ueberschreiben:
        print(f"{CSV_DATEI} existiert bereits (evtl. schon ausgefuellt) - nichts geschrieben. "
              "Neu erzeugen mit --ueberschreiben.")
        sys.exit(1)

    ketten = eu.lade_enron_ketten()
    random.Random(SEED).shuffle(ketten)
    index = eu.MailIndex(eu.lade_mails_dedup(), eu.lade_cluster_zuordnung())

    MD_ORDNER.mkdir(parents=True, exist_ok=True)
    for alt in MD_ORDNER.glob("*.md"):
        alt.unlink()
    with open(CSV_DATEI, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(SPALTEN)
        for nr, k in enumerate(ketten, start=1):
            w.writerow([k["slug"], "", len(eu.aufgabenknoten(k["data"])), "", len(k["data"].get("flows", [])), "", ""])
            (MD_ORDNER / f"{nr:02d}_{k['slug']}.md").write_text(markdown(nr, k, index), encoding="utf-8")

    print(f"{len(ketten)} Ketten (Seed {SEED}): {CSV_DATEI} und {MD_ORDNER}/NN_<chain_id>.md geschrieben.")
    print("Reihenfolge:", ", ".join(k["slug"].replace("chain_cluster_", "") for k in ketten))


if __name__ == "__main__":
    main()
