# Projektzusammenfassung – Grundlage für den Seminarbericht

Stand: 2026-09-21. Diese Datei fasst zusammen, was im Projekt gebaut, getestet und
entschieden wurde, was das Programm kann und welche Dateien wichtig sind. Ergänzend:
`PIPELINE_DOKUMENTATION.md` (Detailentscheidungen der Pipeline), `UPLOAD_FEATURE_PLAN.md`
(Plan des Upload-Features), `backend/README.md` (Skript-Übersicht).

---

## 1. Ziel

Aus E-Mail-Kommunikation soll **implizites prozedurales Wissen** automatisch extrahiert und
als **Aktionsketten** strukturiert werden: wiederkehrende Abläufe, Zuständigkeiten,
Entscheidungen und konkrete Handlungsschritte, die über mehrere Mails verteilt sind. Die
Anzahl der Prozesse wird **nicht vorgegeben**, und es wird **nicht manuell nach
Stichworten** gesucht. Das Ergebnis soll durchsuchbar, darstellbar und bearbeitbar sein.

Ansatz in einem Satz: *Mails säubern → semantisch zu Vorgängen gruppieren (Embedding,
UMAP, HDBSCAN) → pro Gruppe ein LLM (Claude) eine belegte Aktionskette extrahieren lassen →
Ergebnis in einer Weboberfläche anzeigen und bearbeiten.*

## 2. Was das Programm kann

**Extraktion (Backend, Python)**
- Liest den Enron-Korpus (CSV) **oder** hochgeladene Postfächer: `.eml`, `.mbox`
  (Gmail Takeout), `.pst` (Outlook), `.zip` mit diesen Formaten.
- Säubert Mails (Zitate, Forward-Blöcke, Betreff-Präfixe), wandelt HTML-only-Mails in Text
  um, dedupliziert.
- Gruppiert Mails automatisch nach Vorgang, ohne Clusteranzahl vorzugeben; Ausreißer
  landen als „Rauschen".
- Extrahiert pro Gruppe **null, eine oder mehrere** Aktionsketten (ein Cluster kann
  mehrere unabhängige Prozesse enthalten). Jede Kette hat Titel, Zusammenfassung, Akteure,
  Aufgaben- und Entscheidungsknoten (Gateways), Kanten mit Bedingungen, Quellenmails und
  **wörtliche Belegzitate** je Schritt.
- Bewertet jede Kette mit einer Selbsteinschätzung (`prozess_wahrscheinlichkeit`) und
  gibt nur Ketten mit Wert ≥ 0,4 und mindestens 2 Aufgabenknoten aus.
- Prüft auch **einzelne Mails**, die in keinem Cluster landen (eine Mail kann schon eine
  vollständige Kette enthalten).
- Robust bei langen Läufen: Wiederholung bei vorübergehenden API-Fehlern, ein fehlerhafter
  Cluster bricht den Lauf nicht ab, Läufe sind **fortsetzbar**.

**Weboberfläche (Frontend, Next.js)**
- Kettenliste mit Suche über Titel, Zusammenfassung, Tags, Akteure und Aktionen.
- Detailansicht mit **Ablaufdiagramm** (Aufgaben als Kästen, Gateways als Rauten,
  Kantenbeschriftung), Akteursliste, Quellenmails mit den zugehörigen Belegzitaten und
  Wahrscheinlichkeits-Badge.
- Ketten **manuell anlegen, bearbeiten, löschen**.
- **Upload** eines Postfachs mit Modellwahl (Sonnet 5 / Opus 4.8) und Fortschrittsbalken.
  Jeder Upload ist ein unabhängiger Batch, bestehende Ketten bleiben unverändert.

## 3. Architektur

Zwei Wege, ein gemeinsamer Ergebnisordner (`backend/chains/`):

```
Weg A: Enron (Kommandozeile)          Weg B: Upload (Frontend)
data/emails.csv                        .eml / .mbox / .pst / .zip
   │ prepare_emails.py                    │ parse_mailbox.py   (PST: tools/pst)
   ▼                                      ▼
mails.jsonl  ◄──── gleiches Schema ────►  batches/<id>/mails.jsonl
   │ cluster_mails.py                     │ cluster_mails.py --batch-dir
   ▼   (Embedding → UMAP → HDBSCAN)       ▼
clusters.jsonl                            batches/<id>/clusters.jsonl
   │ extract_chains.py --alle             │ extract_chains.py --batch-dir
   ▼   (LLM pro Cluster)                  ▼   (orchestriert von run_pipeline.py)
        backend/chains/*.json  ──►  Frontend (Liste, Diagramm, Bearbeiten)
```

Gemeinsame Bausteine: `mail_utils.py` (Reinigung, Dedup, Heuristik), `env_laden.py`
(API-Key aus `.env`). Modelle laufen über die **KIT-Toolbox** (OpenAI-kompatibler Endpunkt):
Embedding `kit.qwen3-embedding-8b` (4096 Dim.), Extraktion `google.claude-sonnet-5`.

**Aktionsketten-Schema** (Vorlage: `aktionskettenstruktur.json`, an vereinfachte
Prozessmodelle angelehnt): `nodes` (Typ `task` oder `gateway` mit `xor/and/or`), `flows`
(Kanten mit optionaler Bedingung), `actors`, `sources`, je Aufgabe `evidence`
(Quelle + wörtliches Zitat), dazu `prozess_wahrscheinlichkeit` und `prozess_begruendung`.

## 4. Methodik und Entscheidungen (mit Begründung)

### 4.1 Vorverarbeitung
Enron-CSV → Mails per `email`-Modul geparst; Zitatzeilen (`>`), „Original Message"- und
Forward-Blöcke entfernt, Betreff normalisiert (Re:/Fw:/Aw:), Mails unter 40 Zeichen
verworfen. **Deduplizierung nach normalisiertem Body**, weil derselbe Text in vielen
Postfächern liegt. Für Uploads dieselbe Reinigungslogik (`mail_utils`), damit beide Wege
identische Bodies erzeugen.

### 4.2 Gruppierung
Embedding (Betreff + erste 6000 Zeichen) → **UMAP** auf 5 Dimensionen (cosine,
`n_neighbors=15`, feste Zufallszahl) → **HDBSCAN** (`min_cluster_size=2`). Label −1 =
Rauschen, bewusst erlaubt.
- *Parameter-Sweep* (`tune_clustering.py`, `n_neighbors` × `min_cluster_size`): höhere
  `min_cluster_size` senkte das Rauschen nicht, sondern **verschmolz kleine schwache Cluster
  zu größeren falschen** (Beispiel: ein 19-Mail-Cluster aus Bauprojekt, Mailingliste und
  Bounce-Mail). `cluster_selection_method="leaf"` änderte nichts. **Entscheidung: 2**;
  kleine Fehlcluster sind billiger und harmloser, die Qualitätskontrolle übernimmt das LLM.
- *Kleine Batches:* unter 15 Mails wird UMAP übersprungen und direkt auf den Embeddings
  (cosine) geclustert.

### 4.3 Heuristik `chain_score` – nur als Spam-Vorfilter
Metadaten-Score (Reply-Anteil, Absenderzahl, Bulk-Absender-Abzug). Vergleich mit der
LLM-Selbsteinschätzung zeigte **schwache Korrelation** (z. B. Cluster 150/157: Heuristik
0,71, LLM 0,05; Cluster 102: 0,33 vs. 0,72), weil die Heuristik keine Inhalte kennt.
Konsequenz: nur noch harter Vorfilter (`< 0,05`), nicht mehr zur Priorisierung. Fund
unterwegs: die ursprüngliche Bulk-Regex (`update|info`) markierte ein echtes
Genehmigungssystem (`enron_update@concureworkplace.com`) als Spam → Regex entschärft.

### 4.4 Modellwahl
`gemini-2.5-flash` **erfand** bei reinen Werbemails (iWon) einen 15-Knoten-Ablauf, in dem
der Empfänger auf jede Mail reagiert, ohne Beleg. Wechsel auf Claude Sonnet 4.6 mit der
Regel „Reaktion nur mit eigener Mail als Beleg", später auf `claude-sonnet-5`.
Preisverhältnis (Anthropic-Listenpreise je 1 Mio. Token, Input/Output): Sonnet 5 2 $/10 $,
Opus 4.8 5 $/25 $ → Sonnet 5 rund 2,5× günstiger. Die tatsächlichen Kosten über die
KIT-Toolbox wurden **nicht gemessen**.

### 4.5 Prompt-Überarbeitung (Version 2)
Änderungen und Gründe:
1. **Definition** von prozeduralem Wissen und Aktionskette im Prompt (Grundlage: Einleitung
   des Berichts).
2. **Arbeitsreihenfolge:** erst prüfen, *ob* und *welche* Prozesse vorliegen, dann
   extrahieren. Vorher überstimmte „rekonstruiere EINEN Ablauf" die Regel „leere Liste",
   und das Modell verkettete unabhängige Mails.
3. **Mehrere Ketten pro Cluster** (`{"chains":[…]}`), denn eine Mail kann zu mehreren
   Prozessen gehören.
4. **Score neu definiert:** misst jetzt Menge und Klarheit des prozeduralen Wissens, nicht
   Dialoghaftigkeit. Eine einzelne Mail, die einen mehrstufigen Ablauf beschreibt, kann
   hoch bewertet werden.
5. **Ausgabe-Gate:** Score ≥ 0,4 und ≥ 2 Aufgabenknoten.
6. **Regeln gegen Erfindungen:** Kante nur, wenn ein Schritt inhaltlich auf dem anderen
   aufbaut (nicht bei bloßer zeitlicher Nähe); wörtliche Belegzitate; referenzielle
   Integrität (Akteure, Quellen und Knoten-IDs müssen existieren); Negativbeispiel im
   Prompt; ASCII-Umlaute (siehe unten).

**Wirkung** (Vergleich der Testcluster vor/nach, aus den Testläufen):
- Werbe-Cluster 13: vorher 10 Knoten mit 9 erfundenen Kanten (bei Selbstbewertung 0,05),
  nachher korrekt **keine Kette**.
- Cluster 102 (Burnet/Leander/Chelsea Villas): vorher eine Mischkette, nachher **3
  getrennte Ketten**. Das löst die dokumentierte Grenze „eine Mail gehört zu mehreren
  Prozessen".
- Cluster 63: zwei unabhängige Prozesse (tägliche P&L-Schätzung, Freigabe von
  Backtest-Daten) sauber getrennt.
- Nebenfunde: Sonnet 5 lieferte über die KIT-Toolbox **doppelt kodierte Umlaute**
  (`GrundstÃ¼ck`) → Prompt-Regel „ASCII-Umlaute". Ein großer Cluster brach ab, weil das
  interne Reasoning das Token-Limit aufbrauchte (leere Antwort) → `max_tokens` 8000 →
  16000 und Abfangen leerer Antworten. `temperature` wird von Sonnet 5 abgelehnt →
  Läufe sind **nicht bitgenau reproduzierbar**.

### 4.6 Einzelmail-Ketten
Ein Hinweis aus dem Test: eine einzelne Mail kann bereits eine vollständige Aktionskette
sein, HDBSCAN wirft sie aber als Rauschen raus. Im Batch-Modus (Upload) und mit `--alle`
werden Rauschen-Mails deshalb einzeln geprüft, grob vorgefiltert (kein Bulk-Absender,
Body ≥ 200 Zeichen). Der Prompt erlaubt ausdrücklich Ein-Mail- und Ein-Akteur-Ketten, wenn
sie einen echten mehrstufigen Ablauf beschreiben. Im Upload-Test lieferten 5 Mails, die
alle Rauschen waren, 2 Ketten.

### 4.7 Upload-Feature
Jeder Upload ist ein **eigenständiger Batch** (`backend/batches/<id>/`); nur diese Mails
werden geclustert und extrahiert, bestehende Ketten werden nie gelesen oder verändert
(Dateinamen mit Batch-Präfix). Die Pipeline läuft als Hintergrundprozess, der Fortschritt
steht in `status.json`, das Frontend fragt alle 2 s ab. `.pst` wird über das
JavaScript-Paket `pst-extractor` gelesen (kein C-Compiler und keine externe Binary
nötig).

