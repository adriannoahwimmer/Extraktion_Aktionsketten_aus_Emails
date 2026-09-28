# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
explore_enron.py
--------------------------------------------------
Hilfsskript (nicht Teil der Pipeline): erster Blick in den Enron-Datensatz.

  1. Liest die ersten MAX_MAILS Mails aus data/emails.csv.
  2. Zerlegt jede Rohmail in Header (From, Subject, Date) und Body und
     saeubert den Body (gleiche Logik wie die Pipeline, mail_utils).
  3. Zeigt die ersten Beispiele im Terminal.
  4. Speichert ANZAHL_BEISPIELE gesaeuberte Mails als .txt in beispiele/.

Aufruf (aus backend/):
    python explore_enron.py

Nur Python-Standardbibliothek.
"""

import csv
import email
import sys
from email import policy
from pathlib import Path

from mail_utils import saeubere_body
from prepare_emails import finde_csv

# ------------------------------------------------------------------
# Einstellungen
# ------------------------------------------------------------------
MAX_MAILS = 2000          # so viele CSV-Zeilen lesen
ANZAHL_TERMINAL = 5       # so viele Mails im Terminal anzeigen
ANZAHL_BEISPIELE = 15     # so viele gesaeuberte Mails als Datei speichern
AUSGABE_ORDNER = Path("beispiele")

csv.field_size_limit(10_000_000)


def main():
    csv_pfad = finde_csv()
    if csv_pfad is None:
        print("data/emails.csv nicht gefunden (Download-Hinweis siehe README.md).")
        sys.exit(1)

    print(f"Lese aus: {csv_pfad}\n")

    AUSGABE_ORDNER.mkdir(exist_ok=True)
    gespeichert = 0

    with open(csv_pfad, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "message" not in reader.fieldnames:
            print("Keine Spalte 'message' gefunden. Gefundene Spalten:", reader.fieldnames)
            sys.exit(1)

        for i, zeile in enumerate(reader):
            if i >= MAX_MAILS:
                break

            msg = email.message_from_string(zeile.get("message", ""), policy=policy.default)
            absender = msg.get("From", "?")
            betreff = msg.get("Subject", "(kein Betreff)")
            datum = msg.get("Date", "?")

            try:
                body = msg.get_content()
            except Exception:
                body = msg.get_payload()
            if not isinstance(body, str):
                body = str(body)
            body_sauber = saeubere_body(body)

            if i < ANZAHL_TERMINAL:
                print("=" * 70)
                print(f"Von:     {absender}")
                print(f"Betreff: {betreff}")
                print(f"Datum:   {datum}")
                print("-" * 70)
                print(body_sauber[:600])
                print()

            if gespeichert < ANZAHL_BEISPIELE and len(body_sauber) > 200:
                datei = AUSGABE_ORDNER / f"mail_{gespeichert:02d}.txt"
                datei.write_text(
                    f"Von: {absender}\nBetreff: {betreff}\nDatum: {datum}\n"
                    f"{'-' * 70}\n{body_sauber}",
                    encoding="utf-8",
                )
                gespeichert += 1

    print("=" * 70)
    print(f"Fertig. {gespeichert} Beispiel-Mails gespeichert in: {AUSGABE_ORDNER.resolve()}")


if __name__ == "__main__":
    main()
