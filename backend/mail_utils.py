# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
mail_utils.py
--------------------------------------------------
Gemeinsame Hilfsfunktionen fuer die Mail-Pipeline, an einer Stelle, damit alle
Skripte exakt dasselbe Verhalten haben:

  - lade_mails / dedupliziere / normalisiere_body : mails.jsonl laden und nach
    Body deduplizieren (Enron-Korpus + reale Postfaecher enthalten Dubletten).
  - normalisiere_betreff / saeubere_body : Betreff-Praefixe (Re:/Fw:/...) und
    Zitat-/Forward-Bloecke entfernen. Genutzt von prepare_emails.py (Enron-CSV)
    UND parse_mailbox.py (Upload).
  - chain_wahrscheinlichkeit (+ BURNET_PHRASEN, BULK_SENDER_MUSTER) : guenstige
    Heuristik (keine LLM-Kosten), wie wahrscheinlich eine Mailgruppe ein echter
    Dialog-/Aktionsprozess ist. Dient in extract_chains.py nur als Spam-Vorfilter.
"""

import json
import re
from pathlib import Path

# Markante Textstellen der bekannten Burnet-Kernmails (Akzeptanztest).
BURNET_PHRASEN = [
    "site plan for Burnet",
    "written approval from Brenda",
    "site plans for the Burnet deal",
]

# Adressmuster, die auf Massen-/Newsletter-Versender hindeuten (kein Dialog).
# Generische Begriffe wie "update" oder "info" fehlen bewusst: sie treffen auch
# legitime Workflow-Systeme (z.B. enron_update@concureworkplace.com).
BULK_SENDER_MUSTER = re.compile(
    r"(no-?reply|promo|newsletter|marketing|bounce|mailer-daemon|unsubscribe)@",
    re.IGNORECASE,
)


def lade_mails(pfad: Path):
    mails = []
    with open(pfad, "r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                mails.append(json.loads(zeile))
    return mails


def normalisiere_body(body: str) -> str:
    return " ".join(body.split())


def normalisiere_betreff(betreff: str) -> str:
    """Entfernt vorangestellte Re:/Fw:/Fwd:/Aw:-Praefixe (auch mehrfach)."""
    b = (betreff or "").strip()
    aendert = True
    while aendert:
        aendert = False
        for praefix in ("re:", "fw:", "fwd:", "aw:", "wg:"):
            if b.lower().startswith(praefix):
                b = b[len(praefix):].strip()
                aendert = True
    return b


def saeubere_body(text: str) -> str:
    """Entfernt zitierte Vorgaenger-Mails: alles ab einem Forward-/Original-
    Message-Trenner sowie Zitatzeilen ("> ...").

    Wird sowohl vom Enron-CSV-Pfad (prepare_emails.py) als auch vom
    Mailbox-Pfad (parse_mailbox.py) genutzt, damit beide exakt dieselben
    Bodies erzeugen."""
    if not text:
        return ""
    ergebnis = []
    for zeile in text.splitlines():
        g = zeile.strip()
        if g.startswith("---") and ("Original Message" in g or "Forwarded by" in g):
            break
        # Outlook-Trenner "_____" vor einem zitierten Original
        if set(g) == {"_"} and len(g) >= 20:
            break
        if g.startswith(">"):
            continue
        ergebnis.append(zeile)
    text = "\n".join(ergebnis).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def dedupliziere(mails):
    gesehen = set()
    ergebnis = []
    for m in mails:
        schluessel = normalisiere_body(m.get("body", ""))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        ergebnis.append(m)
    return ergebnis


def chain_wahrscheinlichkeit(mails):
    """
    Guenstige Heuristik (keine LLM-Kosten), wie wahrscheinlich eine Gruppe
    von Mails ein echter Dialog-/Aktions-Prozess ist statt z.B. Newsletter
    oder Massen-Werbemails. Score 0..1 plus nachvollziehbare Gruende.

    Signale:
      - reply_anteil:   Anteil Mails mit Re:/Fwd:-Betreff (echte Antworten)
      - absender_bonus: mehr als 1 unterschiedlicher Absender = Dialog moeglich
      - bulk_abzug:     Massen-Versender-Adressmuster (no-reply, promo, ...)
    """
    if not mails:
        return 0.0, ["leere Gruppe"]

    n = len(mails)
    reply_anzahl = sum(
        1 for m in mails if m.get("subject", "") != m.get("subject_norm", m.get("subject", ""))
    )
    reply_anteil = reply_anzahl / n

    absender = {m.get("from", "") for m in mails}
    absender_bonus = min(len(absender) - 1, 3) / 3  # 0 bei 1 Absender, 1 ab 4+

    bulk_treffer = [a for a in absender if BULK_SENDER_MUSTER.search(a)]
    bulk_abzug = 0.5 if bulk_treffer else 0.0

    score = max(0.0, min(1.0, 0.5 * reply_anteil + 0.5 * absender_bonus - bulk_abzug))

    gruende = [
        f"{reply_anzahl}/{n} Mails sind Antworten (Re:/Fwd:)",
        f"{len(absender)} unterschiedliche Absender",
    ]
    if bulk_treffer:
        gruende.append(f"Massen-Versender-Muster erkannt: {bulk_treffer[0]}")

    return round(score, 2), gruende
