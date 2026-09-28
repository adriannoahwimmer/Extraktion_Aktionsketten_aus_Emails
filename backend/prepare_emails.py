# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
prepare_emails.py
--------------------------------------------------
Schritt 1 der Enron-Pipeline: liest die Enron-CSV (data/emails.csv), parst jede
Zeile als Mail, saeubert den Body (gemeinsame Logik aus mail_utils) und schreibt
alle Mails nach mails.jsonl - eine Mail pro Zeile als JSON-Objekt
({id, from, to, date, subject, subject_norm, body}). Dieses Format erwarten
cluster_mails.py und extract_chains.py.

Fuer hochgeladene Postfaecher (.eml/.mbox/.pst/.zip) erzeugt parse_mailbox.py
dasselbe Schema.

Aufruf (aus backend/):
    python prepare_emails.py

Nur Python-Standardbibliothek.
"""

import csv
import json
import email
import sys
from email import policy
from pathlib import Path

from mail_utils import normalisiere_betreff, saeubere_body

# ------------------------------------------------------------------
# Einstellungen
# ------------------------------------------------------------------
MAX_MAILS = 30000                      # so viele CSV-Zeilen lesen (Ausschnitt des Korpus)
MIN_BODY_LEN = 40                      # zu kurze Mails ueberspringen
AUSGABE_DATEI = Path("mails.jsonl")    # hier landet das Ergebnis

csv.field_size_limit(10_000_000)


def finde_csv():
    kandidaten = [
        Path(__file__).parent / "data" / "emails.csv",
        Path(__file__).parent.parent / "data" / "emails.csv",
        Path("data") / "emails.csv",
        Path("..") / "data" / "emails.csv",
    ]
    for pfad in kandidaten:
        if pfad.exists():
            return pfad
    return None


def main():
    csv_pfad = finde_csv()
    if csv_pfad is None:
        print("data/emails.csv nicht gefunden (Download-Hinweis siehe README.md).")
        sys.exit(1)

    print(f"Lese aus: {csv_pfad}")
    geschrieben = 0

    with open(csv_pfad, "r", encoding="utf-8", errors="replace", newline="") as f_in, \
         open(AUSGABE_DATEI, "w", encoding="utf-8") as f_out:

        reader = csv.DictReader(f_in)
        if reader.fieldnames and "message" not in reader.fieldnames:
            print("Keine 'message'-Spalte. Gefunden:", reader.fieldnames)
            return

        for i, zeile in enumerate(reader):
            if i >= MAX_MAILS:
                break

            msg = email.message_from_string(zeile.get("message", ""), policy=policy.default)

            try:
                body = msg.get_content()
            except Exception:
                body = msg.get_payload()
            if not isinstance(body, str):
                body = str(body)

            body_sauber = saeubere_body(body)
            if len(body_sauber) < MIN_BODY_LEN:
                continue

            eintrag = {
                "id": f"mail_{i:05d}",
                "from": msg.get("From", ""),
                "to": msg.get("To", ""),
                "date": msg.get("Date", ""),
                "subject": msg.get("Subject", ""),
                "subject_norm": normalisiere_betreff(msg.get("Subject", "")),
                "body": body_sauber,
            }
            f_out.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
            geschrieben += 1

    print(f"Fertig. {geschrieben} Mails geschrieben in: {AUSGABE_DATEI.resolve()}")
    print("Jede Zeile ist ein JSON-Objekt (eine Mail).")


if __name__ == "__main__":
    main()
