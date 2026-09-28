"""
extract_chains.py
--------------------------------------------------
Extrahiert Aktionsketten aus E-Mail-CLUSTERN mithilfe eines LLM.

Ablauf:
  1. Laedt mails.jsonl und clusters.jsonl (Ausgabe von cluster_mails.py).
     clusters.jsonl enthaelt pro Mail auch einen chain_score (0..1,
     guenstige Heuristik aus mail_utils.chain_wahrscheinlichkeit, OHNE
     LLM-Kosten). Der Score korreliert kaum mit der tatsaechlichen
     Prozess-Qualitaet (siehe Testlauf) - er dient daher NUR als billiger
     Vorfilter, um offensichtlichen Spam/Newsletter (Score nahe 0, meist
     Bulk-Versender-Treffer) VOR dem teuren LLM-Call auszusortieren. Er
     priorisiert NICHT, welche Cluster "gut" sind - das entscheidet die
     eigene Selbsteinschaetzung des LLM (prozess_wahrscheinlichkeit).
  2. Waehlt eine Menge von Clustern aus: von allen Clustern mit
     chain_score >= CHAIN_SCORE_MIN die TOP_N_CLUSTERS groessten, plus
     automatisch jeden Cluster mit einer der bekannten Burnet-Testphrasen
     (Kontrolle, auch wenn der Score niedrig waere). Rauschen (Cluster -1)
     wird nie verarbeitet.
  3. Schickt pro ausgewaehltem Cluster Schema + Mails an ein LLM
     (KIT-Toolbox, OpenAI-kompatibel).
  4. Bekommt je Cluster EINE ODER MEHRERE Aktionsketten zurueck ({"chains": [...]}),
     ein Cluster kann mehrere unabhaengige Prozesse enthalten. Jede Kette wird
     einzeln gespeichert unter backend/chains/chain_cluster_<id>_<k>.json
     (k = 1, 2, ...). Alte Dateien desselben Clusters werden vorher geloescht.

  Mit  python extract_chains.py --models  nur die verfuegbaren Modelle listen.
  Ueber NUR_CLUSTER (unten) laesst sich der Lauf auf bestimmte Cluster begrenzen.

Einmalig vorbereiten:
    pip install openai
    # KIT-Toolbox-API-Key setzen (PowerShell, gilt fuer diese Terminal-Sitzung):
    #   $env:OPENAI_API_KEY = "sk-..."

Ausfuehren (WICHTIG: aus dem Ordner, in dem mails.jsonl liegt, also backend/):
    cd backend
    python extract_chains.py
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from email.utils import parsedate_to_datetime

from openai import OpenAI   # pip install openai

import env_laden  # noqa: F401  - liest OPENAI_API_KEY aus <Projekt>/.env (vor MODEL/EXTRACT_MODEL)
from mail_utils import lade_mails, dedupliziere, BURNET_PHRASEN, BULK_SENDER_MUSTER

# ------------------------------------------------------------------
# Einstellungen
# ------------------------------------------------------------------
# KIT-Toolbox statt OpenAI: OpenAI-kompatibler Endpunkt am SCC.
BASE_URL = "https://ki-toolbox.scc.kit.edu/api/v1"
# Modellname am KIT. Ueber client.models.list() abgefragte Optionen (Auswahl):
#   google.claude-opus-4.8     <- aktuell gewaehlt: staerkstes Instruction-Following,
#                                 haelt sich am zuverlaessigsten an "erfinde nichts"
#   google.claude-sonnet-4.6   guenstiger, gut, aber neigt eher zum Ueberextrahieren
#   google.gemini-2.5-flash    schnell/guenstig, erfand im Test bei Werbe-Mails
#                               nicht belegte Empfaenger-Reaktionen
#   azure.gpt-5-mini           guenstige Alternative
# NICHT verwenden: "standard-extern"/"standard-local" (veraendern den Systemprompt).
# Aktuelle Modellliste pruefen:  python extract_chains.py --models
# Per Umgebungsvariable EXTRACT_MODEL ueberschreibbar (nutzt das Frontend beim Upload).
MODEL = os.environ.get("EXTRACT_MODEL") or "google.claude-sonnet-5"

# Antwortlaenge. Grosse Cluster mit mehreren Ketten koennen viel JSON erzeugen -
# zu niedrig => abgeschnittenes JSON => Cluster wird uebersprungen.
MAX_TOKENS = 16000

MAILS_DATEI = Path("mails.jsonl")
CLUSTERS_DATEI = Path("clusters.jsonl")
AUSGABE_ORDNER = Path("chains")

# Im Batch-Modus (--batch-dir) gesetzt: Praefix fuer die Ketten-Dateinamen, damit
# ein Upload nie eine bestehende Datei ueberschreibt (chain_<batch_id>_cluster_...).
DATEI_PRAEFIX = ""
# Batch-Modus: alle Cluster verarbeiten (kein NUR_CLUSTER / Burnet), aber
# nie mehr als so viele LLM-Calls - Sicherung gegen versehentliche Grosslaeufe.
# Der Deckel gilt fuer echte Cluster UND Einzelmails zusammen.
BATCH_MODUS = False
MAX_CLUSTER = 300

# Batch-Modus: eine EINZELNE Mail kann bereits eine vollstaendige Aktionskette
# enthalten (Anweisung mit mehreren Schritten, Zustaendigkeiten). HDBSCAN wirft
# solche Mails aber als "Rauschen" raus, weil sie mit keiner anderen gruppieren.
# Darum werden Rauschen-Mails im Batch-Modus zusaetzlich einzeln ans LLM
# geschickt - grob vorgefiltert, damit nicht jede FYI-/Werbemail einen Call
# ausloest. Das LLM + die "min. 2 Knoten"-Regel entscheiden dann, ob wirklich
# eine Kette drinsteckt.
EINZELMAIL_MIN_BODY = 200     # kuerzere Mails gelten als zu duenn

# Stellschrauben: wie viele Cluster werden verarbeitet?
# (Testlauf, um Kosten/Laufzeit klein zu halten. Der Burnet-Cluster wird
# unabhaengig davon immer mitverarbeitet, siehe waehle_cluster().)
TOP_N_CLUSTERS = 5        # die N groessten Cluster (nach dem Spam-Vorfilter)

# Wenn gesetzt (nicht leer): NUR genau diese Cluster verarbeiten, alles andere
# (TOP_N, Burnet-Kontrolle, Spam-Vorfilter) wird ignoriert. Fuer gezielte
# Wiederholungslaeufe auf einzelnen Cluster-IDs. Leer lassen fuer den
# Normalfall (TOP_N/--alle) - Cluster-IDs verschieben sich bei jedem
# cluster_mails.py-Lauf neu, alte IDs hier sind nach einem Re-Clustering
# hinfaellig.
NUR_CLUSTER = set()

# --alle (CLI-Flag): wie im Batch-Modus (Upload) ALLE Cluster + Einzelmails
# verarbeiten statt TOP_N_CLUSTERS/Burnet-Kontrolle. Fuer einen vollstaendigen
# Enron-Lauf statt einer Stichprobe. Gedeckelt auf MAX_CLUSTER LLM-Calls.
ALLE_VERARBEITEN = False

# Billiger Vorfilter (keine LLM-Kosten): Cluster mit chain_score darunter
# gelten als offensichtlicher Spam/Newsletter und werden gar nicht erst
# ans LLM geschickt. Bewusst niedrig, da der Score sonst zu ungenau ist,
# um echte Prozesse auszusortieren (siehe Docstring oben).
CHAIN_SCORE_MIN = 0.05

# ------------------------------------------------------------------
# Die Anweisung ans LLM (inkl. deinem Schema)
# ------------------------------------------------------------------
SYSTEM_PROMPT = """Du analysierst geschaeftliche E-Mail-Kommunikation und machst darin
enthaltenes prozedurales Wissen explizit, als strukturierte Aktionsketten (JSON).

WAS IST PROZEDURALES WISSEN / EINE AKTIONSKETTE?
In geschaeftlicher Kommunikation stecken - meist implizit - haeufig wiederkehrende
Ablaeufe: wer wofuer zustaendig ist, welche Entscheidungen getroffen werden und
welche konkreten Handlungsschritte in welcher Reihenfolge passieren. In der
Rohform ist das unuebersichtlich, redundant und schwer auffindbar. Eine
Aktionskette beschreibt einen solchen Ablauf als Folge einzelner Schritte
(orientiert an einem vereinfachten Prozessmodell): Akteure fuehren Handlungen
aus, erzeugen Ergebnisse, an Entscheidungspunkten (Gateways) verzweigt der
Ablauf. Ziel ist ein Format, das man durchsuchen, darstellen und bearbeiten kann.

Die Eingabe ist eine Gruppe zusammengehoeriger E-Mails (manchmal auch nur eine
einzige Mail). Sie koennen zu einem Prozess gehoeren, zu MEHREREN unabhaengigen
Prozessen, oder zu keinem. Auch eine einzelne Mail kann bereits einen
vollstaendigen Ablauf enthalten.

ARBEITE IN DIESER REIHENFOLGE:

1. Identifiziere, welche Prozesse in diesem Cluster stecken. Trenne unabhaengige
   Ablaeufe (unterschiedliche Beteiligte, Ziele, Vorgaenge) voneinander -
   auch wenn sie zeitlich verschraenkt sind. Fasse Mails, die denselben Vorgang
   betreffen, zu EINER Kette zusammen, auch bei unterschiedlichem Betreff.

2. Bewerte jede gefundene Kette mit prozess_wahrscheinlichkeit (0.0-1.0).
   Der Wert misst, wie viel klar erkennbares prozedurales Wissen die Kette
   enthaelt - NICHT, wie dialoghaft die Mails sind:
     - hoch (>=0.7): mehrere konkrete Handlungsschritte, klare Zustaendigkeiten,
       ggf. Entscheidungspunkte; ein nachvollziehbarer, potenziell
       wiederkehrender Ablauf. Eine EINZELNE Mail, die einen mehrstufigen Ablauf
       explizit beschreibt ("erst X, dann sammelt Y ein, dann meldet Z"), zaehlt
       hier ausdruecklich als hoch.
     - mittel (0.4-0.7): ein erkennbarer Ablauf, aber lueckenhaft, sehr wenige
       Schritte oder unklare Zustaendigkeiten.
     - niedrig (<0.4): kaum prozedurales Wissen - blosser Informationsaustausch,
       Smalltalk, eine einzelne Nachfrage, Massen-/Werbemails, automatische
       Benachrichtigungen ohne erkennbaren Ablauf.
   Fehlende Antworten der Empfaenger im Cluster senken den Wert NICHT, solange
   der Ablauf selbst klar beschrieben ist. prozess_begruendung: 1 Satz, welches
   prozedurale Wissen enthalten ist (bzw. warum kaum welches).

3. Gib nur Ketten aus mit prozess_wahrscheinlichkeit >= 0.4 UND mindestens
   2 task-Knoten. Eine Kette mit nur EINEM Akteur ist erlaubt, wenn sie einen
   echten mehrstufigen Arbeitsablauf beschreibt (z.B. eine Anweisung "erst X,
   dann Y, dann Z" oder ein dokumentiertes Vorgehen) - aber nicht fuer blossen
   Smalltalk oder eine einzelne Bitte. Bleibt keine Kette uebrig: "chains": [].

Gib AUSSCHLIESSLICH gueltiges JSON in genau diesem Schema zurueck
(keine Erklaerungen, kein Markdown, keine ```-Zaeune):

{
  "cluster": <n>,
  "chains": [
    {
      "id": "chain_cluster_<n>_<k>",
      "title": "<kurzer Titel, DEUTSCH>",
      "summary": "<1-2 Saetze, worum der Ablauf geht, DEUTSCH>",
      "prozess_wahrscheinlichkeit": <Zahl 0.0-1.0>,
      "prozess_begruendung": "<1 Satz: was spricht dafuer/dagegen>",
      "tags": ["<schlagwort>", "..."],
      "actors": [ { "id": "a1", "name": "...", "type": "person|organisation|system" } ],
      "nodes": [
        { "id": "n1", "type": "task", "action": "<DEUTSCH>", "actor": "a1",
          "recipient": "a2", "inputs": ["..."], "outputs": ["..."],
          "evidence": [ { "source": "src_1", "span": "<woertliches Zitat, Englisch>" } ] },
        { "id": "n2", "type": "gateway", "gateway_type": "xor|and|or",
          "label": "<Entscheidungsfrage, DEUTSCH>" }
      ],
      "flows": [ { "from": "n1", "to": "n2", "condition": "<optional>" } ],
      "sources": [ { "id": "src_1", "type": "email", "from": "...", "to": "...",
                     "date": "...", "subject": "..." } ]
    }
  ]
}

REGELN (gelten pro Kette):
- Erfinde nichts. Jeder Schritt muss durch den Text einer der Mails gedeckt sein.
- Reaktion/Handlung einer Person (z.B. "nimmt teil", "loest ein", "bestaetigt")
  nur annehmen, wenn eine EIGENE Mail dieser Person das belegt. Eine Werbe-
  oder Newsletter-Mail allein belegt KEINE Reaktion des Empfaengers.
  Negativbeispiel: 8 Werbemails verschiedener Absender an dieselbe Person ohne
  eine einzige Antwort => gehoert in keine Kette.
- Kante "from": n -> "to": m NUR, wenn m inhaltlich auf n aufbaut (direkte
  Antwort, Bezugnahme, explizit genannte Reihenfolge). Blosse zeitliche
  Abfolge oder gleicher Cluster ist KEINE Kante.
- Referenzielle Integritaet: "actor"/"recipient" = eine "id" aus "actors";
  "evidence.source" = eine "id" aus "sources"; "flows.from"/"flows.to" = eine
  "id" aus "nodes". Keine Verweise auf nicht existierende IDs. Jeder Akteur in
  "actors" muss in mindestens einem Knoten als actor oder recipient vorkommen.
- IDs fortlaufend und ohne Luecken: a1, a2, a3, ...; ebenso n... und src...
- Deutscher Text ASCII: "ae", "oe", "ue", "ss" statt Umlauten/ß (Titel, summary,
  action, label, begruendung, Akteursnamen). evidence-spans bleiben woertlich.
- Jeder task-Knoten hat >=1 evidence-Eintrag mit einem KURZEN, woertlich aus
  einer Mail kopierten Zitat (Englisch, keine Paraphrase).
- gateway: nur fuer echte Entscheidungen/Vorbedingungen; >=2 ausgehende flows,
  jeweils mit "condition".
- Stabile IDs innerhalb jeder Kette: n1, n2, ...; a1, a2, ...; src_1, src_2, ...
- title, summary, action, label, prozess_begruendung DEUTSCH; evidence-spans
  Englisch (Originalzitat).
"""


def _datum(mail):
    """Hilfsfunktion zum Sortieren nach Datum (faellt zurueck, wenn unparsbar)."""
    try:
        return parsedate_to_datetime(mail.get("date", ""))
    except Exception:
        return None


def lade_cluster_zuordnung(pfad: Path):
    """Liest clusters.jsonl (Ausgabe von cluster_mails.py) als id -> cluster."""
    zuordnung = {}
    cluster_scores = {}
    with open(pfad, "r", encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                eintrag = json.loads(zeile)
                zuordnung[eintrag["id"]] = eintrag["cluster"]
                if eintrag["cluster"] != -1:
                    cluster_scores[eintrag["cluster"]] = eintrag.get("chain_score")
    return zuordnung, cluster_scores


def gruppiere_nach_cluster(mails, zuordnung):
    """Gruppiert Mails nach Cluster-Label. Rauschen (-1) wird ausgelassen."""
    gruppen = {}
    for m in mails:
        cluster = zuordnung.get(m["id"])
        if cluster is None or cluster == -1:
            continue
        gruppen.setdefault(cluster, []).append(m)
    return gruppen


def ergaenze_einzelmails(gruppen, mails, zuordnung):
    """Batch-Modus: nimmt Rauschen-Mails (in keinem Cluster) als Einzel-'Cluster'
    mit dem Schluessel 'e<mailnummer>' dazu. Grob vorgefiltert (kein Bulk-Sender,
    Body lang genug), damit nicht jede FYI-/Werbemail einen LLM-Call ausloest."""
    schon_drin = {m["id"] for ml in gruppen.values() for m in ml}
    dazu = 0
    for m in mails:
        if m["id"] in schon_drin:
            continue
        if zuordnung.get(m["id"], -1) != -1:
            continue
        if BULK_SENDER_MUSTER.search(m.get("from", "")):
            continue
        if len(m.get("body", "")) < EINZELMAIL_MIN_BODY:
            continue
        gruppen[f"e{m['id'].split('_')[-1]}"] = [m]
        dazu += 1
    if dazu:
        print(f"{dazu} Einzelmails (Rauschen) werden zusaetzlich einzeln geprueft.")
    return gruppen


def waehle_cluster(gruppen, cluster_scores, top_n_groesse, score_min):
    """Spam-Vorfilter (chain_score < score_min raus), davon die groessten
    top_n_groesse Cluster + jeder Cluster mit Burnet-Testphrase (Kontrolle,
    unabhaengig vom Score).

    Ausnahme: ist NUR_CLUSTER gesetzt, werden genau diese Cluster verarbeitet
    (soweit vorhanden) und sonst nichts."""
    if BATCH_MODUS or ALLE_VERARBEITEN:
        # Upload bzw. --alle: alle Cluster, groesste zuerst, gedeckelt auf MAX_CLUSTER.
        nach_groesse = sorted(gruppen.items(), key=lambda kv: -len(kv[1]))
        ausgewaehlt = {cid for cid, _ in nach_groesse[:MAX_CLUSTER]}
        if len(gruppen) > MAX_CLUSTER:
            print(f"{len(gruppen)} Cluster - deckle auf die {MAX_CLUSTER} groessten.")
        return ausgewaehlt, 0

    if NUR_CLUSTER:
        ausgewaehlt = {cid for cid in NUR_CLUSTER if cid in gruppen}
        fehlt = sorted(NUR_CLUSTER - ausgewaehlt)
        if fehlt:
            print(f"Hinweis: Cluster {fehlt} nicht in clusters.jsonl gefunden.")
        return ausgewaehlt, 0

    ohne_spam = {
        cid: mails for cid, mails in gruppen.items()
        if (cluster_scores.get(cid) or 0) >= score_min
    }
    verworfen = len(gruppen) - len(ohne_spam)

    nach_groesse = sorted(ohne_spam.items(), key=lambda kv: -len(kv[1]))
    ausgewaehlt = {cid for cid, _ in nach_groesse[:top_n_groesse]}

    for cid, mails in gruppen.items():
        if any(any(p in m.get("body", "") for p in BURNET_PHRASEN) for m in mails):
            ausgewaehlt.add(cid)

    return ausgewaehlt, verworfen


def entferne_markdown_zaeune(text: str) -> str:
    """Manche Modelle umschliessen JSON trotz response_format mit ```-Zaeunen."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def sortiere_chronologisch(batch):
    return sorted(batch, key=lambda m: (_datum(m) is None, _datum(m)))


def baue_user_prompt(batch):
    teile = []
    for i, m in enumerate(batch, start=1):
        teile.append(
            f"--- E-MAIL {i} ---\n"
            f"Von: {m.get('from','')}\n"
            f"An: {m.get('to','')}\n"
            f"Datum: {m.get('date','')}\n"
            f"Betreff: {m.get('subject','')}\n\n"
            f"{m.get('body','')}"
        )
    return "\n\n".join(teile)


def frage_llm(system: str, user: str) -> str:
    """
    Schickt die Anfrage ans LLM und gibt die Roh-Antwort (JSON-Text) zurueck.

    >>> Das ist die EINZIGE Stelle, die du aendern musst, wenn du einen
    >>> anderen Anbieter nutzt. Varianten unten als Kommentar.
    """
    # api_key wird aus der Umgebungsvariable OPENAI_API_KEY gelesen;
    # base_url zeigt auf die KIT-Toolbox statt auf api.openai.com.
    client = OpenAI(base_url=BASE_URL)

    nachrichten = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Optionale Parameter. Manche Modelle lehnen einzelne davon mit HTTP 400 ab:
    #   - response_format: v.a. lokale KIT-Modelle
    #   - temperature: neuere Modelle (z.B. claude-sonnet-5) erlauben nur den
    #     Default und antworten sonst mit 400.
    # Wir versuchen es zuerst mit allen und lassen bei einem 400 den jeweils
    # genannten Parameter weg (der Systemprompt fordert ohnehin reines JSON).
    optional = {
        "response_format": {"type": "json_object"},
        "temperature": 0,   # deterministisch -> reproduzierbar fuer die Evaluation
    }
    # Transiente Fehler (kurze Verbindungsaussetzer zum Modell-Backend hinter
    # der KIT-Toolbox, Rate-Limits, ueberlastete Server) sollen einen
    # mehrstuendigen Lauf nicht abbrechen - mit Backoff erneut versuchen.
    TRANSIENT_MARKER = (
        "server connection error", "connection error", "timeout",
        "rate limit", "overloaded", "503", "502", "504", "429",
    )
    transiente_versuche = 0
    MAX_TRANSIENTE_VERSUCHE = 4

    while True:
        try:
            antwort = client.chat.completions.create(
                model=MODEL, messages=nachrichten, max_tokens=MAX_TOKENS, **optional
            )
            wahl = antwort.choices[0]
            inhalt = wahl.message.content
            if not inhalt:
                # Kein Text in der Antwort. Haeufigste Ursache: max_tokens vom
                # (unsichtbaren) Reasoning aufgebraucht -> finish_reason "length".
                print(
                    f"  (LEERE Antwort, finish_reason={wahl.finish_reason}, "
                    f"usage={getattr(antwort, 'usage', None)})"
                )
                return ""
            return inhalt
        except Exception as e:
            fehlertext = str(e).lower()
            entfernt = next(
                (p for p in list(optional) if p in fehlertext
                 or (p == "response_format" and "json" in fehlertext)),
                None,
            )
            if entfernt is not None:
                print(f"  (Modell lehnt '{entfernt}' ab, versuche es ohne)")
                optional.pop(entfernt)
                continue

            if any(m in fehlertext for m in TRANSIENT_MARKER) and transiente_versuche < MAX_TRANSIENTE_VERSUCHE:
                transiente_versuche += 1
                wartezeit = 5 * transiente_versuche  # 5, 10, 15, 20 Sekunden
                print(f"  (transienter Fehler, Versuch {transiente_versuche}/{MAX_TRANSIENTE_VERSUCHE}, "
                      f"warte {wartezeit}s: {e})")
                time.sleep(wartezeit)
                continue

            raise  # echter/anhaltender Fehler (falscher Key, Modell unbekannt, ...)

    # --- ALTERNATIVE: OpenAI direkt (kostenpflichtig) ------------------
    # client = OpenAI()          # ohne base_url -> geht an api.openai.com
    # MODEL oben auf "gpt-4o" setzen und einen echten OpenAI-Key verwenden.

    # --- ALTERNATIVE: Anthropic (Claude) -------------------------------
    # pip install anthropic ; $env:ANTHROPIC_API_KEY = "..."
    # from anthropic import Anthropic
    # client = Anthropic()
    # antwort = client.messages.create(
    #     model="claude-sonnet-4-5",
    #     max_tokens=2000,
    #     system=system,
    #     messages=[{"role": "user", "content": user}],
    # )
    # return antwort.content[0].text

    # --- ALTERNATIVE: Lokal via Ollama (kostenlos) ---------------------
    # pip install requests ; vorher: ollama pull llama3.1
    # import requests
    # r = requests.post("http://localhost:11434/api/chat", json={
    #     "model": "llama3.1",
    #     "messages": [{"role": "system", "content": system},
    #                  {"role": "user", "content": user}],
    #     "format": "json", "stream": False,
    # })
    # return r.json()["message"]["content"]


def extrahiere_ketten(antwort_obj, cid):
    """Holt die Ketten-Liste aus der LLM-Antwort. Akzeptiert das neue Format
    {"chains": [...]}, eine nackte Liste, oder (Rueckwaertskompatibilitaet)
    ein einzelnes Ketten-Objekt mit "nodes"."""
    if isinstance(antwort_obj, dict) and isinstance(antwort_obj.get("chains"), list):
        ketten = antwort_obj["chains"]
    elif isinstance(antwort_obj, list):
        ketten = antwort_obj
    elif isinstance(antwort_obj, dict) and "nodes" in antwort_obj:
        ketten = [antwort_obj]
    else:
        ketten = []
    # Nur Ketten mit tatsaechlichem Ablauf behalten.
    return [k for k in ketten if isinstance(k, dict) and k.get("nodes")]


def schreibe_ketten(cid, ketten):
    """Loescht die alten Ketten-Dateien DIESES Clusters (und, im Batch-Modus,
    nur die mit diesem Batch-Praefix - andere Batches bleiben unberuehrt) und
    schreibt eine Datei je Kette."""
    basis = f"chain_{DATEI_PRAEFIX}cluster_{cid}"
    for alt in AUSGABE_ORDNER.glob(f"{basis}.json"):
        alt.unlink()
    for alt in AUSGABE_ORDNER.glob(f"{basis}_*.json"):
        alt.unlink()

    if not ketten:
        print("  -> keine belegte Kette, nichts gespeichert.\n")
        return

    for k, kette in enumerate(ketten, start=1):
        kette["id"] = f"{DATEI_PRAEFIX}cluster_{cid}_{k}"
        datei = AUSGABE_ORDNER / f"{basis}_{k}.json"
        datei.write_text(json.dumps(kette, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"  -> {datei.name}  "
            f"({len(kette.get('nodes', []))} Knoten, "
            f"prozess_wahrscheinlichkeit={kette.get('prozess_wahrscheinlichkeit')})"
        )
    print()


def liste_modelle():
    client = OpenAI(base_url=BASE_URL)
    for m in sorted(mod.id for mod in client.models.list().data):
        print(m)


def _setze_batch_modus(batch_dir: Path):
    """Batch-Modus: Ein-/Ausgabe an einen Upload binden."""
    global MAILS_DATEI, CLUSTERS_DATEI, DATEI_PRAEFIX, BATCH_MODUS
    MAILS_DATEI = batch_dir / "mails.jsonl"
    CLUSTERS_DATEI = batch_dir / "clusters.jsonl"
    # Ordnername des Batches wird zum Dateinamen-Praefix.
    DATEI_PRAEFIX = f"{batch_dir.name}_"
    BATCH_MODUS = True


def _verarbeitet_datei() -> Path:
    """Fortschritts-Marker liegt neben clusters.jsonl - also pro Batch-Ordner
    eigenstaendig, beim Enron-Modus (--alle) eine gemeinsame Datei in backend/."""
    return CLUSTERS_DATEI.parent / "verarbeitet.json"


def lade_verarbeitet() -> set:
    pfad = _verarbeitet_datei()
    if not pfad.exists():
        return set()
    try:
        return set(json.loads(pfad.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def markiere_verarbeitet(cid):
    """Merkt eine Gruppe als abgearbeitet (egal ob mit oder ohne Ergebnis),
    damit ein Wiederholungslauf nach einem Abbruch nicht bei Null anfaengt."""
    erledigt = lade_verarbeitet()
    erledigt.add(str(cid))
    _verarbeitet_datei().write_text(
        json.dumps(sorted(erledigt), ensure_ascii=False), encoding="utf-8"
    )


def verarbeite_gruppe(cid, batch, cluster_scores):
    """Ein Cluster/eine Einzelmail: LLM fragen, JSON parsen, Ketten speichern.
    Fehler werden geloggt, nie weitergereicht - ein Lauf ueber viele Gruppen
    (--alle / --batch-dir) soll an einer einzelnen kaputten Gruppe nicht
    komplett abbrechen."""
    print(f"=== Cluster {cid} ({len(batch)} Mails, chain_score={cluster_scores.get(cid)}) ===")
    for m in batch:
        print(f"  - {m['id']} | {m.get('date','')} | Betreff: {m.get('subject','')!r}")

    print(f"Schicke an {MODEL} (ueber {BASE_URL}) ...")
    try:
        roh = frage_llm(SYSTEM_PROMPT, baue_user_prompt(batch))
    except Exception as e:
        print(f"  FEHLER bei diesem Cluster, wird uebersprungen: {e}\n")
        return

    roh = entferne_markdown_zaeune(roh)
    if not roh:
        print("  Leere Antwort, Cluster wird uebersprungen.\n")
        return
    try:
        antwort_obj = json.loads(roh)
    except json.JSONDecodeError:
        print("Antwort war kein gueltiges JSON, ueberspringe Cluster:\n", roh[:2000])
        return

    ketten = extrahiere_ketten(antwort_obj, cid)
    print(f"  {len(ketten)} Kette(n) erkannt.")
    schreibe_ketten(cid, ketten)


def main():
    if "--models" in sys.argv:
        liste_modelle()
        return

    parser = argparse.ArgumentParser(description="Aktionsketten extrahieren (siehe Docstring).")
    parser.add_argument("--batch-dir", type=Path, default=None,
                        help="Upload-Batch; ohne Angabe: Enron-Modus im aktuellen Ordner.")
    parser.add_argument("--alle", action="store_true",
                        help="Enron-Modus: alle Cluster + Einzelmails verarbeiten (wie Batch-Modus), "
                             "statt TOP_N_CLUSTERS/Burnet-Kontrolle. Gedeckelt auf MAX_CLUSTER.")
    parser.add_argument("--models", action="store_true", help="verfuegbare Modelle listen")
    args = parser.parse_args()
    if args.batch_dir is not None:
        _setze_batch_modus(args.batch_dir)
    global ALLE_VERARBEITEN
    if args.alle:
        ALLE_VERARBEITEN = True

    if not MAILS_DATEI.exists():
        print(f"{MAILS_DATEI} nicht gefunden.")
        return
    if not CLUSTERS_DATEI.exists():
        print(f"{CLUSTERS_DATEI} nicht gefunden. Erst cluster_mails.py ausfuehren.")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Kein OPENAI_API_KEY gesetzt.")
        print('PowerShell:  $env:OPENAI_API_KEY = "sk-..."  (dein KIT-Toolbox-Key)')
        return

    mails = dedupliziere(lade_mails(MAILS_DATEI))
    zuordnung, cluster_scores = lade_cluster_zuordnung(CLUSTERS_DATEI)
    gruppen = gruppiere_nach_cluster(mails, zuordnung)
    if BATCH_MODUS or ALLE_VERARBEITEN:
        gruppen = ergaenze_einzelmails(gruppen, mails, zuordnung)
    ausgewaehlt, verworfen = waehle_cluster(gruppen, cluster_scores, TOP_N_CLUSTERS, CHAIN_SCORE_MIN)

    AUSGABE_ORDNER.mkdir(exist_ok=True)

    resumierbar = BATCH_MODUS or ALLE_VERARBEITEN
    if resumierbar:
        erledigt = lade_verarbeitet()
        uebersprungen = {c for c in ausgewaehlt if str(c) in erledigt}
        if uebersprungen:
            print(f"{len(uebersprungen)} Gruppen schon in einem frueheren Lauf verarbeitet "
                  f"({_verarbeitet_datei().name}) - werden uebersprungen. Zum Neu-Start diese "
                  f"Datei loeschen.")
        ausgewaehlt = ausgewaehlt - uebersprungen

    print(f"{len(gruppen)} Gruppen (Cluster + ggf. Einzelmails).")
    if not resumierbar:
        print(f"Vorfilter: {verworfen} Cluster mit chain_score < {CHAIN_SCORE_MIN} ausgeschlossen (vermutlich Spam).")
    print(f"Verarbeite {len(ausgewaehlt)} Gruppen: {sorted(ausgewaehlt, key=str)}\n")

    for cid in sorted(ausgewaehlt, key=str):
        verarbeite_gruppe(cid, sortiere_chronologisch(gruppen[cid]), cluster_scores)
        if resumierbar:
            markiere_verarbeitet(cid)


if __name__ == "__main__":
    main()
