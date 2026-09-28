# backend/ – Skript-Übersicht

Es gibt **zwei Wege**, an Aktionsketten zu kommen. Beide enden im selben Ordner
`backend/chains/` und werden vom Frontend gleich angezeigt.

| | Weg A: Enron-Initialdatensatz | Weg B: Postfach hochladen |
|---|---|---|
| Auslöser | manuell auf der Kommandozeile | Upload-Button im Frontend |
| Eingabe | `data/emails.csv` | `.eml` / `.mbox` / `.pst` / `.zip` |
| Arbeitsordner | `backend/` direkt | `backend/batches/<batch_id>/` |
| Ketten-Dateien | `chains/chain_cluster_<n>_<k>.json` | `chains/chain_<batch_id>_cluster_<n>_<k>.json` |
| bestehende Ketten | werden überschrieben | bleiben unberührt |

---

## Weg A – Enron-Initialdatensatz (Kommandozeile)

Einmalig von Hand, in `backend/` mit gesetztem `$env:OPENAI_API_KEY`:

```
python prepare_emails.py      # 1. CSV säubern
python cluster_mails.py       # 2. einbetten + clustern
python extract_chains.py      # 3. Ketten extrahieren
```

| Skript | Aufgabe |
|---|---|
| **`prepare_emails.py`** | Liest `data/emails.csv`, parst jede Mail, säubert den Body (Zitate/Forwards raus), normalisiert den Betreff → schreibt `mails.jsonl` (`{id, from, to, date, subject, subject_norm, body}`). |
| **`cluster_mails.py`** | Lädt `mails.jsonl`, dedupliziert nach Body, bettet jede Mail über die KIT-Toolbox ein (`kit.qwen3-embedding-8b`, Cache `embeddings.npy`), reduziert mit UMAP auf 5D, clustert mit HDBSCAN → `clusters.jsonl` (`{id, cluster, chain_score, …}`). Plus Konsolen-Report + Burnet-Akzeptanztest. |
| **`extract_chains.py`** | Lädt `mails.jsonl` + `clusters.jsonl`. Ohne `--batch-dir`: verarbeitet die in `NUR_CLUSTER` aufgelisteten Cluster (bzw. Top-N + Burnet-Kontrolle). Schickt jeden Cluster ans LLM (`google.claude-sonnet-5`), speichert die zurückgegebenen Ketten als `chains/chain_cluster_<n>_<k>.json`. |
| `explore_enron.py` | Nur zum Reinschauen in die CSV (Beispiele als `.txt`). Nicht Teil der Pipeline. |
| `tune_clustering.py` | Experimentierskript für UMAP/HDBSCAN-Parameter. Nicht Teil der Pipeline. |

---

## Weg B – Postfach hochladen (Frontend)

Der Nutzer lädt eine Datei hoch → das Frontend legt `batches/<batch_id>/upload/`
an und startet **`run_pipeline.py`** als Hintergrundprozess. Alles Weitere läuft
automatisch. Jeder Upload ist ein abgeschlossener Batch; nur die Mails dieses
Uploads werden verglichen, geclustert und extrahiert.

```
run_pipeline.py --batch-dir batches/<batch_id>
   │
   ├─ parse_mailbox.py --batch-dir …     → mails.jsonl
   ├─ cluster_mails.py  --batch-dir …     → clusters.jsonl
   └─ extract_chains.py --batch-dir …     → ../chains/chain_<batch_id>_cluster_*.json
```

| Skript | Aufgabe im Batch-Modus |
|---|---|
| **`run_pipeline.py`** | Orchestrator. Prüft den API-Key, ruft die drei Skripte nacheinander auf, schreibt fortlaufend `status.json` (Phase, Fortschritt, Zahlen) und `pipeline.log`. Bricht mit klarer Meldung ab bei fehlendem Key / kaputtem Upload. |
| **`parse_mailbox.py`** | Liest die Rohdateien aus `upload/`: `.eml` (stdlib), `.mbox` (stdlib), `.zip` (entpacken, dann rekursiv), `.pst` (über `tools/pst/pst_to_jsonl.js`, reines JavaScript mit dem Paket `pst-extractor` – braucht nur Node, das Paket wird beim ersten Mal automatisch per `npm install` geholt; Rückfall: externes `readpst`). HTML-only-Mails werden zu Text umgewandelt. Säubert mit derselben Logik wie `prepare_emails.py` → `mails.jsonl` im Batch-Ordner. |
| **`cluster_mails.py`** | Wie bei Weg A, aber `--batch-dir` lenkt alle Pfade in den Batch-Ordner. Kleiner-Batch-Schutz: < 15 Mails → UMAP übersprungen, direkt auf den Embeddings geclustert. |
| **`extract_chains.py`** | Mit `--batch-dir` im **Batch-Modus**: verarbeitet **alle** Cluster (kein `NUR_CLUSTER`) **plus einzelne Rauschen-Mails** (eine Mail kann schon eine Kette sein; grob gefiltert: kein Bulk-Sender, Body ≥ 200 Zeichen). Deckel: `MAX_CLUSTER` = 300 Calls gesamt. Dateiname mit `<batch_id>`-Präfix → überschreibt nie fremde Ketten. Modell per `EXTRACT_MODEL` / `config.json`. |

---

## Gemeinsam genutzt (beide Wege)

| Datei | Aufgabe |
|---|---|
| **`mail_utils.py`** | `lade_mails` / `dedupliziere` / `normalisiere_body`, `normalisiere_betreff` / `saeubere_body` (Reinigung), `chain_wahrscheinlichkeit` + `BURNET_PHRASEN` + `BULK_SENDER_MUSTER` (Spam-Heuristik). Eine Quelle, damit CSV- und Upload-Weg identisch säubern. |
| `mails.jsonl` | gesäuberte Mails, eine JSON-Zeile pro Mail |
| `clusters.jsonl` | Cluster-Zuordnung + `chain_score` pro Mail |
| `embeddings.npy` / `embeddings_ids.json` | Embedding-Cache |
| `chains/*.json` | die extrahierten Aktionsketten (Weg A ohne, Weg B mit `<batch_id>`-Präfix; manuell angelegte: `chain_manuell_*`) |

## Frontend-Bezug

| Datei | Weg |
|---|---|
| `src/lib/chains.ts` | beide – liest/schreibt die `chains/*.json` |
| `src/lib/batches.ts` | B – Batch anlegen, `run_pipeline.py` starten, `status.json` lesen |
| `src/app/api/chains/…` | beide – Ketten anzeigen/bearbeiten/löschen |
| `src/app/api/batches/…` | B – Upload entgegennehmen, Status ausliefern |
| `src/components/MailUpload.tsx` | B – Upload-Formular + Fortschritt |
| `src/components/ChainFlowDiagram.tsx` | beide – Ablaufdiagramm |
