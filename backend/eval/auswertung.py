# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
auswertung.py
--------------------------------------------------
Schritt 6 der Auswertung: wertet die ausgefuellte bewertung.csv aus
(erzeugt von bewertungsbogen.py).

Das Urteil steht in Spalte k1 (Rueckfall: Spalte urteil):
    U = korrekt, uebertragbares Verfahren
    E = korrekt, einmaliger Vorgang
    F = fehlerhaft
Ausgewertet werden nur Zeilen mit ausgefuelltem Urteil. Ausgabe: Anzahl bewerteter
Ketten, Anzahl je Klasse, Anteil korrekt (U+E) und Median der
prozess_wahrscheinlichkeit je Klasse (aus backend/chains/<chain_id>.json).
Trennzeichen ';' oder ',' werden automatisch erkannt, Kleinschreibung ist erlaubt.

Aufruf:  python auswertung.py [--datei out/bewertung.csv]
Ausgabe: Konsole und auswertung.md im Ordner der CSV-Datei
"""

import argparse
import csv
import json
import statistics as st
import sys
from pathlib import Path

import eval_utils as eu

KLASSEN = {
    "U": "korrekt, uebertragbares Verfahren",
    "E": "korrekt, einmaliger Vorgang",
    "F": "fehlerhaft",
}
URTEIL_SPALTEN = ("k1", "urteil")


class _Semikolon(csv.excel):
    delimiter = ";"


def lies_csv(pfad: Path):
    text = pfad.read_text(encoding="utf-8-sig")
    try:
        dialekt = csv.Sniffer().sniff(text.splitlines()[0], delimiters=";,\t")
    except csv.Error:
        dialekt = _Semikolon
    return list(csv.DictReader(text.splitlines(), dialect=dialekt))


def main():
    eu.utf8_ausgabe()
    parser = argparse.ArgumentParser(description="Bewertung auswerten (siehe Modul-Docstring).")
    parser.add_argument("--datei", type=Path, default=eu.OUT_DIR / "bewertung.csv")
    args = parser.parse_args()
    if not args.datei.exists():
        print(f"{args.datei} nicht gefunden - erst bewertungsbogen.py ausfuehren und ausfuellen.")
        sys.exit(1)

    zeilen = lies_csv(args.datei)
    spalte = next((s for s in URTEIL_SPALTEN if zeilen and s in zeilen[0]), None)
    if spalte is None:
        print(f"Keine Urteilsspalte gefunden (erwartet: {' oder '.join(URTEIL_SPALTEN)}).")
        sys.exit(1)

    bewertet, fehler, gesamt = [], [], 0
    for nr, zeile in enumerate(zeilen, start=1):
        cid = (zeile.get("chain_id") or "").strip()
        if not cid:
            continue
        gesamt += 1
        urteil = (zeile.get(spalte) or "").strip().upper()
        if not urteil:
            continue
        if urteil not in KLASSEN:
            fehler.append(f"Zeile {nr} ({cid}): {spalte} = '{urteil}' (erlaubt: {', '.join(KLASSEN)})")
            continue
        datei = eu.CHAINS_DIR / f"{cid}.json"
        p = json.loads(datei.read_text(encoding="utf-8")).get("prozess_wahrscheinlichkeit") if datei.exists() else None
        if p is None:
            fehler.append(f"Zeile {nr} ({cid}): keine prozess_wahrscheinlichkeit gefunden")
        bewertet.append({"chain_id": cid, "urteil": urteil, "p": p})

    n = len(bewertet)
    korrekt = sum(1 for b in bewertet if b["urteil"] in ("U", "E"))
    md = [
        "# Auswertung der manuellen Bewertung",
        "",
        f"Datei: `{args.datei.name}`, Urteil aus Spalte `{spalte}` – **bewertete Ketten: {n}** von {gesamt} "
        f"(ohne Urteil: {gesamt - n})",
        "",
        "| Urteil | Bedeutung | Anzahl | Anteil | Median prozess_wahrscheinlichkeit | Werte |",
        "|---|---|---|---|---|---|",
    ]
    for kl, text in KLASSEN.items():
        teil = [b for b in bewertet if b["urteil"] == kl]
        ps = sorted(b["p"] for b in teil if b["p"] is not None)
        anteil = f"{len(teil) / n:.0%}" if n else "–"
        md.append(f"| {kl} | {text} | {len(teil)} | {anteil} | {st.median(ps) if ps else '–'} | "
                  f"{', '.join(f'{p:g}' for p in ps) or '–'} |")
    md += [
        "",
        f"**Anteil korrekt (U + E): {korrekt}/{n} ({korrekt / n:.1%})**" if n else "**Anteil korrekt (U + E): –** (noch nichts bewertet)",
    ]
    if fehler:
        md += ["", "## Eingabefehler (Zeilen uebersprungen)", "", *[f"- {f}" for f in fehler]]

    args.datei.with_name("auswertung.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
