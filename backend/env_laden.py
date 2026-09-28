"""
env_laden.py
--------------------------------------------------
Liest die Datei <Projektordner>/.env und setzt die darin stehenden Variablen
(v.a. OPENAI_API_KEY, der KIT-Toolbox-Key) als Umgebungsvariablen - damit man
den Key nicht in jedem neuen Terminal per  $env:OPENAI_API_KEY = "..."  setzen
muss.

Wird einfach per  import env_laden  eingebunden (laedt beim Import).

Regeln:
  - Format: eine Zeile pro Variable, NAME=Wert (Anfuehrungszeichen optional),
    Zeilen mit # sind Kommentare.
  - Eine bereits gesetzte Umgebungsvariable (z.B. per $env:... im Terminal)
    hat Vorrang und wird NICHT ueberschrieben.
  - Leere Werte werden ignoriert.
"""

import os
from pathlib import Path

ENV_DATEI = Path(__file__).resolve().parent.parent / ".env"


def lade_env(pfad: Path = ENV_DATEI) -> None:
    if not pfad.is_file():
        return
    # utf-8-sig: toleriert ein BOM (macht z.B. PowerShell's Out-File gern)
    for zeile in pfad.read_text(encoding="utf-8-sig").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, wert = zeile.split("=", 1)
        name, wert = name.strip(), wert.strip().strip('"').strip("'")
        if name and wert and not os.environ.get(name):
            os.environ[name] = wert


lade_env()
