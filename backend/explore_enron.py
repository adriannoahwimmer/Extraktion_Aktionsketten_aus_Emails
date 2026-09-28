"""
explore_enron.py
--------------------------------------------------
Erster Blick in den Enron-Datensatz (emails.csv).

Was das Skript macht:
  1. Liest die ersten MAX_MAILS Mails aus emails.csv
  2. Zerlegt jede Rohmail in Header (From, Subject, Date) und Body
  3. Saeubert den Body grob (zitierte Replies + Forward-Bloecke raus)
  4. Zeigt die ersten paar Beispiele im Terminal
  5. Speichert ANZAHL_BEISPIELE gesaeuberte Mails als .txt zum Anschauen

Ausfuehren (im Terminal, im Ordner wo dieses Skript liegt):
    python explore_enron.py

Braucht KEINE Zusatzpakete - nur eingebaute Python-Module.
"""

import csv
import email
from email import policy
from pathlib import Path

# ------------------------------------------------------------------
# Einstellungen (Zahlen kannst du frei anpassen)
# ------------------------------------------------------------------
MAX_MAILS = 2000          # so viele Zeilen der CSV schauen wir ueberhaupt an
ANZAHL_BEISPIELE = 15     # so viele gesaeuberte Mails speichern wir als Datei
AUSGABE_ORDNER = Path("beispiele")

# Die CSV hat teils riesige Felder -> Standardlimit hochsetzen,
# sonst bricht das Einlesen mit "field larger than field limit" ab.
csv.field_size_limit(10_000_000)


def finde_csv():
    """Sucht emails.csv an ein paar ueblichen Stellen relativ zum Skript."""
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


def saeubere_body(text: str) -> str:
    """
    Entfernt grob den 'Muell' aus einer Mail (bewusst simpel, v1):
      - alles ab dem Original-/Forward-Trenner
      - zitierte Zeilen (beginnen mit '>')
    """
    ergebnis = []
    for zeile in text.splitlines():
        g = zeile.strip()
        # Ab hier faengt meist die zitierte Vor-Mail an -> abbrechen
        if g.startswith("---") and ("Original Message" in g or "Forwarded by" in g):
            break
        # Zitierte Zeilen ueberspringen
        if g.startswith(">"):
            continue
        ergebnis.append(zeile)
    return "\n".join(ergebnis).strip()


def main():
    csv_pfad = finde_csv()
    if csv_pfad is None:
        print("emails.csv wurde nicht gefunden.")
        print("Lege die Datei in einen 'data'-Ordner neben dieses Skript,")
        print("oder passe die Pfade in finde_csv() an.")
        return

    print(f"Lese aus: {csv_pfad}\n")

    AUSGABE_ORDNER.mkdir(exist_ok=True)
    gespeichert = 0

    with open(csv_pfad, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)

        # Sicherheitscheck: hat die CSV wirklich eine 'message'-Spalte?
        if reader.fieldnames and "message" not in reader.fieldnames:
            print("Achtung: keine Spalte 'message' gefunden.")
            print("Gefundene Spalten:", reader.fieldnames)
            return

        for i, zeile in enumerate(reader):
            if i >= MAX_MAILS:
                break

            rohmail = zeile.get("message", "")
            msg = email.message_from_string(rohmail, policy=policy.default)

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

            # Die ersten 5 direkt im Terminal zeigen
            if i < 5:
                print("=" * 70)
                print(f"Von:     {absender}")
                print(f"Betreff: {betreff}")
                print(f"Datum:   {datum}")
                print("-" * 70)
                print(body_sauber[:600])
                print()

            # Ein paar mit echtem Inhalt als Datei speichern
            if gespeichert < ANZAHL_BEISPIELE and len(body_sauber) > 200:
                datei = AUSGABE_ORDNER / f"mail_{gespeichert:02d}.txt"
                datei.write_text(
                    f"Von: {absender}\nBetreff: {betreff}\nDatum: {datum}\n"
                    f"{'-' * 70}\n{body_sauber}",
                    encoding="utf-8",
                )
                gespeichert += 1

    print("=" * 70)
    print(f"Fertig. {gespeichert} Beispiel-Mails gespeichert in:")
    print(f"  {AUSGABE_ORDNER.resolve()}")
    print("Oeffne den Ordner in VS Code und lies ein paar durch.")


if __name__ == "__main__":
    main()