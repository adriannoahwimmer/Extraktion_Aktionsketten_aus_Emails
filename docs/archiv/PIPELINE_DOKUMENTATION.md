# Pipeline-Dokumentation: Aktionsketten-Extraktion aus E-Mails

Stand: 2026-09-24. Dokumentiert die Enron-Mail-Pipeline im Ordner `backend/` —
Zweck, Design-Entscheidungen, Experimente und offene Punkte, als Grundlage
für das Seminar-Protokoll. Abschnitte 4–5 beschreiben auch frühere
Zwischenstände (Gemini, Sonnet 4.6, Prompt v1); der aktuelle Stand steht in
Abschnitt 3 und 7.

## 1. Ziel

Aus dem Enron-Mail-Korpus (`data/emails.csv`) automatisch **implizites
prozedurales Wissen** extrahieren: wiederkehrende Geschäftsabläufe, die sich
über mehrere E-Mails erstrecken, als strukturierte "Aktionsketten" (Akteure,
Schritte, Flüsse, Belege). Ohne die Anzahl der Prozesse vorzugeben und ohne
manuell nach Stichworten zu suchen.

## 2. Pipeline-Überblick

```
data/emails.csv
      |  prepare_emails.py   (säubern, dedizierte Felder extrahieren)
      v
backend/mails.jsonl          (1346 Mails, 1 JSON-Objekt pro Zeile)
      |  cluster_mails.py    (Embedding -> UMAP -> HDBSCAN -> chain_score)
      v
backend/clusters.jsonl       (750 dedup. Mails je einem Cluster/Rauschen zugeordnet)
      |  extract_chains.py   (Spam-Vorfilter -> LLM pro Cluster)
      v
backend/chains/chain_cluster_<id>_<k>.json   (0..n Aktionsketten je Cluster)
```

Gemeinsame Hilfsfunktionen (Laden, Deduplizieren, Heuristik-Score) liegen in
`backend/mail_utils.py`, damit alle Skripte exakt dieselben Mail-IDs nutzen.

## 3. Schritt für Schritt

### 3.1 `prepare_emails.py`
Liest die Enron-CSV, parst jede Mail (`email`-Modul), entfernt Zitat-Zeilen
und Forward-/Original-Message-Blöcke, normalisiert den Betreff (Re:/Fw:/Fwd:
-Präfixe entfernt) und schreibt jede Mail als JSON-Zeile nach `mails.jsonl`.
Felder: `id, from, to, date, subject, subject_norm, body`.

### 3.2 `cluster_mails.py`
1. **Deduplizieren** nach normalisiertem Body (Enron-Korpus enthält dieselbe
   Mail mehrfach in verschiedenen Postfächern). 1346 → 750 Mails.
2. **Embedden** über KIT-Toolbox (`kit.qwen3-embedding-8b`, 4096 Dimensionen),
   Text = `subject + "\n\n" + body[:6000 Zeichen]`. Ergebnis wird lokal
   gecacht (`embeddings.npy` + `embeddings_ids.json`), erneute Läufe embedden
   nur fehlende Mails nach.
3. **Dimensionsreduktion**: UMAP auf 5 Dimensionen, `metric="cosine"`,
   `n_neighbors=15`, `random_state=42`.
4. **Clustering**: `sklearn.cluster.HDBSCAN(min_cluster_size=2)`. Label `-1`
   = Rauschen (bewusst erlaubt, für irrelevante Einzelmails).
5. **chain_score-Heuristik** (siehe 4.2) pro Cluster berechnet und mit
   ausgegeben.
6. Ausgabe: `clusters.jsonl` (pro Mail: `id, cluster, subject, date, from,
   to, chain_score, chain_gruende`) + Konsolen-Report (Clusteranzahl,
   Rauschen-Quote, größte Cluster, Burnet-Akzeptanztest).

**Aktuelle Kennzahlen** (Stand nach Tuning-Experiment, siehe 5.3):
200 Cluster, 92/750 Mails Rauschen (12 %).

### 3.3 `extract_chains.py`
1. Lädt `mails.jsonl` (dedupliziert) + `clusters.jsonl`.
2. **Spam-Vorfilter**: Cluster mit `chain_score < CHAIN_SCORE_MIN` (0.05)
   werden nicht ans LLM geschickt (siehe 4.2/4.3 — der Score dient NUR
   diesem Zweck, nicht der Priorisierung).
3. **Auswahl** der Cluster, drei Modi:
   - Standard (Stichprobe): die `TOP_N_CLUSTERS` (5) größten Cluster plus
     jeder Cluster mit einer bekannten Burnet-Testphrase (Kontroll-Cluster,
     unabhängig vom Score).
   - `--alle`: **alle** Cluster (größte zuerst) **plus einzelne
     Rauschen-Mails** (siehe 7), gedeckelt auf `MAX_CLUSTER` (300) LLM-Calls.
   - `NUR_CLUSTER` (Konstante im Skript): genau diese Cluster-IDs, für
     gezielte Wiederholungsläufe.
4. Pro Cluster: chronologisch sortierte Mails + Schema-Prompt an
   `google.claude-sonnet-5` (KIT-Toolbox, per `EXTRACT_MODEL`
   überschreibbar). Die Antwort ist `{"chains": [...]}` mit **null, einer
   oder mehreren** Ketten; jede wird einzeln gespeichert unter
   `chains/chain_cluster_<id>_<k>.json`. Ausgegeben werden nur Ketten mit
   `prozess_wahrscheinlichkeit` ≥ 0.4 und mindestens 2 Aufgabenknoten.
5. **Robustheit:** ein Fehler bei einem Cluster wird geloggt und übersprungen,
   bricht den Lauf nicht ab. Abgearbeitete Cluster werden in
   `verarbeitet.json` vermerkt, ein abgebrochener Lauf setzt dort fort.
   `max_tokens` = 16000, leere Antworten (Reasoning hat das Token-Limit
   aufgebraucht) werden abgefangen.

## 4. Wichtige Design-Entscheidungen

### 4.1 Modellwahl für die Extraktion: Gemini → Claude Sonnet
Ursprünglich `google.gemini-2.5-flash`. Im Test bei einem Cluster aus
einseitigen Werbe-Mails (iWon-Newsletter ohne jede Antwort des Empfängers)
hat Gemini einen 15-Knoten-Ablauf **erfunden**, in dem der Empfänger auf
jede Werbemail reagiert ("nimmt an Gewinnspiel teil", "wählt Tarif") — obwohl
dafür keine einzige Beleg-Mail existierte. Klarer Verstoß gegen die Regel
"Erfinde nichts" im Prompt.

→ Wechsel auf `google.claude-sonnet-4.6` (über `client.models.list()`
ermittelte verfügbare KIT-Modelle). Zusätzlich Prompt-Regel verschärft:
*"Nimm nur dann an, dass eine Person reagiert hat, wenn dafür eine EIGENE
Mail dieser Person als Beleg existiert."* Ergebnis: derselbe Cluster liefert
jetzt korrekt `nodes: []` mit Begründung "einseitige Massen-/Werbemails ohne
Reaktion".

Später Wechsel auf `google.claude-sonnet-5` (aktueller Standard; Opus 4.8
im Upload wählbar). Nebenfunde dabei: doppelt kodierte Umlaute über die
KIT-Toolbox (→ Prompt-Regel „ASCII-Umlaute"), und `temperature` wird
abgelehnt, Läufe sind daher nicht bitgenau reproduzierbar.

**Nebenfund:** `google.claude-sonnet-4.6` umschließt die JSON-Antwort
gelegentlich mit Markdown-Codezäunen (` ```json ... ``` `), obwohl
`response_format={"type": "json_object"}` gesetzt ist. Behoben durch
`entferne_markdown_zaeune()` vor `json.loads()`.

### 4.2 chain_score-Heuristik (mail_utils.chain_wahrscheinlichkeit)
Günstige Vorab-Einschätzung **ohne LLM-Kosten**, wie wahrscheinlich eine
Mailgruppe ein echter Dialogprozess ist statt Newsletter/Spam:

```
score = 0.5 * reply_anteil + 0.5 * absender_bonus - bulk_abzug
```

- `reply_anteil`: Anteil Mails mit Re:/Fwd:-Betreff (erkannt am Unterschied
  `subject` vs. `subject_norm`)
- `absender_bonus`: `min(anzahl_absender - 1, 3) / 3` (0 bei 1 Absender, 1
  ab 4+)
- `bulk_abzug`: 0.5 falls ein Absender das Muster
  `(no-?reply|promo|newsletter|marketing|bounce|mailer-daemon|unsubscribe)@`
  matcht

**Wichtige Korrektur während der Arbeit:** Ursprünglich enthielt das
Bulk-Muster auch `update` und `info` — das hat `enron_update@
concureworkplace.com` (ein echtes, teilautomatisiertes Genehmigungs-System)
fälschlich als Spam markiert (Score 0.0 statt korrekt 0.23). Regex
entschärft, generische Begriffe entfernt.

### 4.3 Score-Nutzung: Vorfilter statt Priorisierung
Vergleich `chain_score` (Heuristik) vs. `prozess_wahrscheinlichkeit`
(LLM-Selbsteinschätzung, Teil des Extraktions-Schemas) auf denselben
Clustern zeigte **schwache Korrelation**:

| Cluster | chain_score | prozess_wahrscheinlichkeit | Einordnung |
|---|---|---|---|
| 13 (iWon-Spam) | 0.0 | 0.05 | ✅ einig |
| 150 | 0.71 | 0.05 | ⚠️ Heuristik überschätzt deutlich |
| 157 | 0.71 | 0.05 | ⚠️ Heuristik überschätzt deutlich |
| 102 (Burnet) | 0.33 | 0.72 | ⚠️ Heuristik unterschätzt |
| 183 (Recruiting) | 0.48 | 0.82 | ⚠️ Heuristik unterschätzt |
| 168 (FERC Talking Points) | 0.80 | 0.72 | ✅ beide hoch |

Grund: die Heuristik erfasst nur Metadaten (Reply-Anteil, Absenderzahl), aber
nicht, ob die Mails *inhaltlich* zusammenhängen. Cluster 150/157 hatten viele
Antworten, aber zu völlig unterschiedlichen, unzusammenhängenden Themen.

**Konsequenz:** `chain_score` wird nur noch als harter **Vorfilter gegen
offensichtlichen Spam** verwendet (`CHAIN_SCORE_MIN = 0.05`, meist
Bulk-Pattern-Treffer), nicht mehr zur Priorisierung "guter" Cluster. Die
eigentliche Qualitätsbeurteilung übernimmt die LLM-Selbsteinschätzung
`prozess_wahrscheinlichkeit`, die im selben Extraktions-Call mitgeliefert
wird (kein Mehraufwand).

## 5. Experimente

### 5.1 Burnet-Akzeptanztest (laufender Sanity-Check)
Prüft, ob die bekannten Burnet-Mails (3 Textphrasen als Fingerabdruck) im
selben Cluster landen. Besteht bei allen getesteten Parameter-Konfigurationen
außer bei zu hohem `min_cluster_size` (siehe 5.3).

**Wichtige Einschränkung, die den Test relativiert:** Der Test prüft nur
Recall (landen die bekannten Mails zusammen?), nicht Präzision (ist sonst
nichts Falsches im Cluster?) und nichts über die Qualität der daraus
extrahierten Kette. Eine der drei Burnet-Mails (`mail_00537`) behandelt
inhaltlich primär einen *anderen* Deal ("Leander deal", Closing), erwähnt
Burnet nur als Nebenthema (Steuerfragen) — die Extraktion hat das Burnet-Detail
korrekt herausgepickt, den Leander-Anteil aber komplett ignoriert. Zeigt eine
grundsätzliche Grenze der Pipeline: **eine Mail kann zu mehreren gleichzeitig
laufenden Prozessen gehören**, das Modell geht aber implizit von "eine Mail =
ein Prozess" aus.

**Gelöst mit Prompt v2** (mehrere Ketten pro Cluster, erst prüfen *ob* und
*welche* Prozesse vorliegen): Cluster 102 liefert jetzt 3 getrennte Ketten
(Burnet, Leander, Chelsea Villas) statt einer Mischkette.

### 5.2 Modell-Vergleich (Vollständiger Testlauf, 11 Cluster)
Mit `google.claude-sonnet-4.6`, Prompt v1 (eine Kette pro Cluster) und der
verschärften Anti-Halluzinations-Regel:
- 3 von 11 Clustern lieferten stabile, gut belegte Ketten (Burnet, FERC
  Talking Points, Recruiting/Trading-Track)
- 2 von 11 lieferten korrekt **leere** `nodes: []` (Cluster 150, 157 —
  unzusammenhängende Kurzmails, das Modell hat richtig erkannt, dass kein
  Prozess vorliegt, statt etwas zu erfinden)
- Rest: Mischfälle mit expliziter Selbstkritik in `prozess_begruendung`
  (z.B. "mehrere unabhängige Kommunikationsstränge, kein einzelner Prozess")

### 5.3 UMAP/HDBSCAN-Parameter-Tuning (`tune_clustering.py`)
Ausgangsfrage: senkt ein höheres `HDBSCAN_MIN_CLUSTER_SIZE` die
Rauschen-Quote (92/750 = 12 %) und verbessert die Clusterqualität (Cluster
150/157 warfen kurze, generische, thematisch unpassende Mails zusammen)?

**Sweep-Ergebnis** (`n_neighbors` × `min_cluster_size`, gecachte Embeddings,
kein neuer API-Call):

| n_neighbors | min_cluster | Cluster | Rauschen | Burnet |
|---|---|---|---|---|
| 10 | 2 | 208 | 12 % | ❌ |
| 10 | 3 | 104 | 17 % | ❌ (gespalten) |
| **15** | **2 (Standard)** | **200** | **12 %** | ✅ |
| 15 | 3 | 104 | 18 % | ✅ |
| 15 | 4 | 55 | 22 % | ❌ (Burnet nur 3 Mails, fällt raus) |
| 30 | 2/3/4 | 202/93/56 | 16–25 % | ✅ alle |
| 50 | 2/3/4 | 198/81/41 | 15–29 % | ✅ alle |

**Kontraintuitives Ergebnis:** Höheres `min_cluster_size` senkt die
Rauschen-Quote NICHT, sondern erhöht sie — aber das ist per se kein
Qualitätsverlust (siehe unten).

**Qualitative Prüfung** (min_cluster_size=3 vs. 2, `n_neighbors=15`):
Der größte neue Cluster (19 Mails) erwies sich als Sammelbecken völlig
unzusammenhängender Themen (Strohballenhaus-Bau-Mailingliste, privates
Bauprojekt, eine Bounce-Mail, diverse private Kontakte). **HDBSCAN
verschmilzt kleine, schwache Cluster bei höherem Schwellwert nicht mit
Rauschen, sondern mit dem nächstgrößeren akzeptierten Cluster** in seiner
internen Hierarchie — es entstehen also weniger, aber größere Fehlcluster
statt vieler kleiner.

Test mit `cluster_selection_method="leaf"` (wählt untere statt obere
Hierarchie-Ebenen, sollte theoretisch eher zu Rauschen tendieren): **kein
Unterschied** — identischer 19-Mail-Cluster, nur andere ID. Das
Verschmelzungsproblem liegt an der Dichtestruktur der UMAP-Projektion
selbst, nicht an der HDBSCAN-Auswahlmethode.

**Entscheidung: zurückgesetzt auf `min_cluster_size=2`.** Begründung:
- Kleine falsche Cluster (2-3 Mails) sind günstiger und harmloser als große
  falsche Cluster (mehr verschwendete LLM-Tokens, mehr Fehlerpotenzial).
- Die eigentliche Qualitätskontrolle passiert ohnehin nachgelagert über
  `prozess_wahrscheinlichkeit` (siehe 4.3) — das Clustering muss nicht
  perfekt sein, das LLM fängt Fehlcluster zuverlässig ab.
- Parameter-Tuning an dieser Stelle hat sichtbar abnehmenden Grenznutzen.

`tune_clustering.py` bleibt im Repo für spätere manuelle/visuelle Prüfung.

## 6. Offene Punkte / Ideen für die Weiterarbeit

- **Mehrfach-Prozess-Mails**: innerhalb eines Clusters gelöst (mehrere
  Ketten, siehe 5.1). Eine Mail bleibt aber genau einem Cluster zugeordnet;
  gehört ein zweiter Prozess inhaltlich zu einem anderen Cluster, sieht das
  LLM beide Teile nie gemeinsam.
- **Voller Lauf über alle 200 Cluster** ist mit `--alle` möglich (fortsetzbar,
  gedeckelt auf `MAX_CLUSTER`); die Standardeinstellung bleibt aus
  Kostengründen die Stichprobe Top-5 + Burnet-Kontrolle.
- **chain_score als Vorfilter weiter verfeinern**: aktuell nur
  Metadaten-basiert; ggf. zusätzliche Signale (z.B. Body-Länge, Anzahl
  gemeinsamer Empfänger) denkbar — aber wie in 4.3 gezeigt, mit Vorsicht zu
  genießen.
- **Burnet als einziger Benchmark ist dünn**: nur ein bekannter Fall, prüft
  nur Cluster-Zugehörigkeit, nicht Kettenqualität. Für belastbarere Aussagen
  wäre ein zweiter, unabhängig verifizierter Prozess als zusätzlicher
  Testfall sinnvoll.

## 7. Batch-Upload aus dem Frontend

Zusätzlich zum Enron-CSV-Weg kann ein Postfach über die Weboberfläche
hochgeladen werden. Details: `UPLOAD_FEATURE_PLAN.md`. Kurz:

- **Jeder Upload = ein unabhängiger Batch.** Nur die Mails dieses Uploads
  werden verglichen, geclustert und extrahiert. Bestehende Aktionsketten
  werden nie gelesen oder verändert.
- Ablauf pro Batch: `parse_mailbox.py` (`.eml`/`.mbox`/`.pst`/`.zip` →
  `mails.jsonl`) → `cluster_mails.py --batch-dir …` → `extract_chains.py
  --batch-dir …`. Orchestriert von `run_pipeline.py`, das `status.json`
  schreibt (Phase, Fortschritt, Zahlen).
- Batch-Verzeichnis: `backend/batches/<batch_id>/`. Ketten landen mit
  `<batch_id>`-Präfix im gemeinsamen `backend/chains/`-Ordner
  (`chain_<batch_id>_cluster_<cid>_<k>.json`) — kollidiert nie mit
  vorhandenen Dateien.
- `extract_chains.py` verarbeitet im Batch-Modus **alle** Cluster (kein
  `NUR_CLUSTER`) **plus einzelne Rauschen-Mails**: eine einzelne Mail kann
  bereits eine vollständige Aktionskette enthalten, HDBSCAN wirft sie aber als
  Rauschen raus. Solche Mails werden grob vorgefiltert (kein Bulk-Sender, Body
  ≥ `EINZELMAIL_MIN_BODY` = 200 Zeichen) und einzeln ans LLM geschickt; die
  „mind. 2 Knoten / prozess_wahrscheinlichkeit ≥ 0.4"-Regel im Prompt
  entscheidet dann. Gesamtzahl der LLM-Calls (Cluster + Einzelmails) ist auf
  `MAX_CLUSTER` (300) gedeckelt. Modell per `EXTRACT_MODEL` bzw. `config.json`.
- Voraussetzung: KIT-Toolbox-Key in `<Projekt>/.env` (`OPENAI_API_KEY`, wird
  vom Frontend und den Python-Skripten gelesen); `.pst` wird über `backend/tools/pst`
  (Node + `pst-extractor`, Installation beim ersten Mal automatisch) gelesen;
  nur als Rückfall wird `readpst` (libpst) genutzt, falls es im `PATH` liegt.
- Erster `cluster_mails.py`-Aufruf pro Prozess dauert ~30–60 s länger
  (`import umap` / numba-JIT).

## 8. Zentrale Dateien

| Datei | Zweck |
|---|---|
| `backend/prepare_emails.py` | Enron-CSV → `mails.jsonl` |
| `backend/parse_mailbox.py` | `.eml`/`.mbox`/`.pst`/`.zip` → `mails.jsonl` (Upload) |
| `backend/mail_utils.py` | Laden/Dedup/Reinigung/chain_score (gemeinsam genutzt) |
| `backend/cluster_mails.py` | Embedding → UMAP → HDBSCAN → `clusters.jsonl` (`--batch-dir`) |
| `backend/extract_chains.py` | Cluster → LLM → `chains/chain_*.json` (`--batch-dir`) |
| `backend/run_pipeline.py` | Orchestrator für einen Upload-Batch + `status.json` |
| `backend/tune_clustering.py` | Experimentier-Skript für UMAP/HDBSCAN-Parameter |
| `backend/batches/<id>/` | pro Upload: `upload/`, `mails.jsonl`, `clusters.jsonl`, `status.json` |
| `backend/chains/*.json` | Extrahierte Aktionsketten (Enron: `chain_cluster_*`, Upload: `chain_<id>_cluster_*`) |
| `frontend/src/components/MailUpload.tsx` | Upload-UI + Fortschritt |
| `frontend/src/lib/batches.ts` | Batch anlegen, Pipeline starten, `status.json` lesen |
