# backend/ – Skript-Übersicht

Installation und Start des Gesamtprojekts: siehe [README im Projektordner](../README.md).
Alle Skripte werden aus `backend/` aufgerufen und lesen den KIT-Toolbox-Key aus
`<Projekt>/.env` (über `env_laden.py`).

Es gibt **zwei Wege** zu Aktionsketten. Beide enden im selben Ordner
`backend/chains/`, den das Frontend anzeigt.

| | Weg A: Enron-Datensatz | Weg B: Postfach hochladen |
|---|---|---|
| Auslöser | manuell auf der Kommandozeile | Upload in der Weboberfläche |
| Eingabe | `data/emails.csv` | `.eml` / `.mbox` / `.pst` / `.zip` |
| Arbeitsordner | `backend/` direkt | `backend/batches/<batch_id>/` |
| Ketten-Dateien | `chains/chain_cluster_<n>_<k>.json` | `chains/chain_<batch_id>_cluster_<n>_<k>.json` |
| bestehende Ketten | gleichnamige werden überschrieben | bleiben unberührt |

Manuell in der Weboberfläche angelegte Ketten heißen `chains/chain_manuell_<id>.json`.

---

## Weg A – Enron-Datensatz (Kommandozeile)

```
python prepare_emails.py          # 1. CSV säubern
python cluster_mails.py           # 2. einbetten + clustern
python extract_chains.py          # 3. Ketten extrahieren (Stichprobe)
python extract_chains.py --alle   #    oder alle Cluster + Einzelmails
```

| Skript | Aufgabe |
|---|---|
| **`prepare_emails.py`** | Liest `data/emails.csv`, parst jede Mail, säubert den Body (Zitate/Forwards raus), normalisiert den Betreff → `mails.jsonl` (`{id, from, to, date, subject, subject_norm, body}`). |
| **`cluster_mails.py`** | Lädt `mails.jsonl`, dedupliziert nach Body, bettet jede Mail über die KIT-Toolbox ein (`kit.qwen3-embedding-8b`, Cache `embeddings.npy`), reduziert mit UMAP auf 5 Dimensionen, clustert mit HDBSCAN → `clusters.jsonl` (`{id, cluster, chain_score, …}`). Dazu Konsolen-Report und Burnet-Akzeptanztest. |
| **`extract_chains.py`** | Lädt `mails.jsonl` + `clusters.jsonl`, wählt die Cluster aus (Standard: 5 größte + Burnet-Kontrolle; `--alle`: alle Cluster + Einzelmails, fortsetzbar über `verarbeitet.json`), schickt jede Gruppe an das LLM (`google.claude-sonnet-5`) und speichert die Ketten als `chains/chain_cluster_<n>_<k>.json`. `--models` listet die verfügbaren Modelle. |
| `explore_enron.py` | Hilfsskript: Blick in die CSV (Beispiele als `.txt` in `beispiele/`). |
| `tune_clustering.py` | Hilfsskript: Parameter-Sweep für UMAP/HDBSCAN auf dem Embedding-Cache. |

---

## Weg B – Postfach hochladen (Weboberfläche)

Das Frontend legt `batches/<batch_id>/upload/` an und startet **`run_pipeline.py`**
als Hintergrundprozess. Jeder Upload ist ein abgeschlossener Batch: Nur die Mails
dieses Uploads werden verglichen, geclustert und extrahiert.

```
run_pipeline.py --batch-dir batches/<batch_id>
   │
   ├─ parse_mailbox.py  --batch-dir …     → mails.jsonl
   ├─ cluster_mails.py  --batch-dir …     → clusters.jsonl
   └─ extract_chains.py --batch-dir …     → ../chains/chain_<batch_id>_cluster_*.json
```

| Skript | Aufgabe im Batch-Modus |
|---|---|
| **`run_pipeline.py`** | Orchestrator. Prüft den API-Key, ruft die drei Skripte nacheinander auf, schreibt fortlaufend `status.json` (Phase, Fortschritt, Zahlen) und `pipeline.log`. Bricht mit klarer Meldung ab bei fehlendem Key oder unlesbarem Upload. |
| **`parse_mailbox.py`** | Liest die Rohdateien aus `upload/`: `.eml` und `.mbox` (Standardbibliothek), `.zip` (entpacken, dann rekursiv), `.pst` (über `tools/pst/pst_to_jsonl.js` mit dem Paket `pst-extractor`; braucht nur Node, das Paket wird beim ersten Mal automatisch per `npm install` geholt; Rückfall: externes `readpst`). HTML-only-Mails werden in Text umgewandelt. Gleiche Reinigung wie `prepare_emails.py`. |
| **`cluster_mails.py`** | Wie bei Weg A, `--batch-dir` lenkt alle Pfade in den Batch-Ordner. Unter 15 Mails wird UMAP übersprungen und direkt auf den Embeddings geclustert. |
| **`extract_chains.py`** | Verarbeitet **alle** Cluster **plus einzelne Rauschen-Mails** (eine Mail kann schon eine Kette sein; grob gefiltert: kein Massenversender, Body ≥ 200 Zeichen). Deckel: `MAX_CLUSTER` = 300 Aufrufe. Dateinamen mit `<batch_id>`-Präfix. Modell aus `config.json` (vom Frontend gesetzt). |

---

## Gemeinsam genutzt

| Datei | Aufgabe |
|---|---|
| **`mail_utils.py`** | `lade_mails` / `dedupliziere` / `normalisiere_body`, `normalisiere_betreff` / `saeubere_body` (Reinigung), `chain_wahrscheinlichkeit` + `BURNET_PHRASEN` + `BULK_SENDER_MUSTER` (Spam-Heuristik). Eine Quelle, damit beide Wege identisch säubern. |
| **`env_laden.py`** | Liest `<Projekt>/.env` in die Umgebungsvariablen. |
| `mails.jsonl` | gesäuberte Mails, eine JSON-Zeile pro Mail |
| `clusters.jsonl` | Cluster-Zuordnung + `chain_score` pro Mail |
| `embeddings.npy` / `embeddings_ids.json` | Embedding-Cache |
| `chains/*.json` | die Aktionsketten |

`mails.jsonl`, `clusters.jsonl`, der Embedding-Cache und `batches/` werden lokal
erzeugt und sind nicht im Repository.

## Frontend-Bezug

| Datei | Weg |
|---|---|
| `frontend/src/lib/chains.ts` | beide – liest/schreibt `chains/*.json` |
| `frontend/src/lib/batches.ts` | B – Batch anlegen, `run_pipeline.py` starten, `status.json` lesen |
| `frontend/src/app/api/chains/…` | beide – Ketten anzeigen/bearbeiten/löschen |
| `frontend/src/app/api/batches/…` | B – Upload entgegennehmen, Status ausliefern |
| `frontend/src/components/MailUpload.tsx` | B – Upload-Formular + Fortschritt |
| `frontend/src/components/ChainFlowDiagram.tsx` | beide – Ablaufdiagramm |
