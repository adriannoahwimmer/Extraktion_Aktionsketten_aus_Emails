# Plan: Mail-Upload & Aktionsketten-Extraktion aus der Weboberfläche

Stand: 2026-09-24 (Plan vom 2026-09-10, inzwischen umgesetzt; Abweichungen
vom ursprünglichen Plan sind vermerkt). Erweitert die bestehende
Enron-Pipeline (`backend/`) um die Möglichkeit, ein Postfach über das Frontend
hochzuladen und daraus Aktionsketten zu extrahieren.

## 1. Ziel & Kernprinzip

Der Nutzer lädt ein Postfach (bzw. einen Teil davon) über einen Upload-Button
im Frontend hoch und startet die Extraktion. Die Pipeline läuft wie bisher
(säubern → clustern → LLM-Extraktion) und die neuen Aktionsketten erscheinen in
der bestehenden Kettenliste.

**Kernprinzip: jeder Upload ist ein abgeschlossener, unabhängiger Batch.**

- Es werden **nur die Mails dieses Uploads** miteinander verglichen, geclustert
  und extrahiert.
- Bestehende Aktionsketten (aus früheren Uploads oder dem Enron-Lauf) werden
  **nie gelesen und nie verändert**.
- Kein Deduplizieren gegen frühere Batches, keine inkrementelle Zuordnung zu
  alten Clustern, keine "hat sich ein Cluster geändert"-Logik.

Konsequenz: Lädt der Nutzer zweimal überlappende Postfächer hoch, entstehen
doppelte Ketten. Das ist bei diesem Modell bewusst so.

## 2. Unterstützte Dateiformate

| Format | Quelle | Verarbeitung |
|---|---|---|
| `.eml` | einzeln gespeicherte Mail (Outlook, Thunderbird, Apple Mail) | stdlib `email` |
| `.mbox` | Gmail (Google Takeout exportiert direkt `.mbox`), Thunderbird | stdlib `mailbox` |
| `.pst` | Outlook Desktop ("Datei → Öffnen/Exportieren → Exportieren in Datei") | `backend/tools/pst/pst_to_jsonl.js` (Node, Paket `pst-extractor`) → JSON-Zeilen → gleiche Reinigung. Rückfall: `readpst` (libpst) |
| `.zip` | ein ganzes Postfach als viele `.eml` (dann gezippt) — enthält `.eml`, `.mbox` oder `.pst` | entpacken, dann pro Datei wie oben |

Nicht in v1:

- `.msg` (einzelne Outlook-Mail im OLE-Format) — bräuchte das Paket
  `extract-msg`. Später leicht ergänzbar.
- `.ost` (Outlook Offline-Cache) — nicht zuverlässig konvertierbar.

**`.pst`-Abhängigkeit (Stand: umgesetzt):** Node.js. Das Paket `pst-extractor`
liegt in `backend/tools/pst/` und wird beim ersten `.pst`-Upload automatisch per
`npm install` geholt, falls `node_modules` fehlt. Kein C-Compiler und keine
externe Binary nötig (die ursprünglich geplante `readpst`-Route ist nur noch
Rückfall). Fehlt Node, gibt der Parser eine klare Meldung aus.

**Kleiner Batch:** UMAP mit `n_neighbors=15` braucht genug Datenpunkte. Bei
weniger als 15 Mails im Batch wird UMAP übersprungen und direkt auf den
Embeddings (cosine) geclustert, darüber `n_neighbors = min(15, n − 1)`
(siehe §9).

## 3. Verzeichnis- & Namensschema

```
backend/
  batches/
    <batch_id>/                        z.B. b20260910_1432_a1b2  (nur [a-z0-9_])
      upload/                          rohe Uploads (.eml/.mbox/.pst/.zip)
      mails.jsonl                      gesäubert, Schema wie bisher
      embeddings.npy                   Embedding-Cache dieses Batches
      embeddings_ids.json
      clusters.jsonl                   Cluster-Zuordnung dieses Batches
      config.json                      { modell, umap/hdbscan-parameter, max_cluster }
      status.json                      Fortschritt (siehe §6)

  chains/                              FLACH, wie bisher — Frontend liest hier
    chain_<batch_id>_cluster_<cid>_<k>.json    neue Batches (prefixed)
    chain_cluster_<cid>_<k>.json               aktueller Enron-Lauf (bleibt)
    chain_manuell_<uuid>.json                  manuell angelegte Ketten
```

Der `<batch_id>`-Präfix im Dateinamen garantiert: ein neuer Batch überschreibt
**nie** eine bestehende Ketten-Datei, auch wenn beide Batches "Cluster 63" haben.

`batch_id` = `b` + Zeitstempel + kurzer Zufalls-Suffix, nur Kleinbuchstaben,
Ziffern und `_` (damit der Frontend-Slug-Check `^[a-zA-Z0-9_-]+$` in
`frontend/src/lib/chains.ts` weiter passt).

## 4. Pipeline pro Batch

`run_pipeline.py --batch-dir backend/batches/<batch_id>` führt nacheinander aus:

1. **parse** — `parse_mailbox.py`
   - Uploads in `upload/` erkennen (Endung), `.zip` entpacken, `.pst` über
     `tools/pst/pst_to_jsonl.js` (`pst-extractor`) lesen, Rückfall `readpst`.
     HTML-only-Mails werden in Text umgewandelt.
   - Jede Mail parsen (`email`/`mailbox`), säubern (gemeinsame Logik aus
     `mail_utils.py`), Betreff normalisieren.
   - Schreibt `mails.jsonl` im bestehenden Schema
     (`id, from, to, date, subject, subject_norm, body`).
   - `id` = `mail_<laufende_nummer>` innerhalb des Batches.

2. **cluster** — `cluster_mails.py --batch-dir …`
   - Wie bisher: Dedup nach Body (nur innerhalb des Batches), Embedding über
     KIT-Toolbox (`kit.qwen3-embedding-8b`, Cache im Batch-Ordner),
     UMAP → HDBSCAN.
   - Burnet-Akzeptanztest wird übersprungen, wenn keine Burnet-Phrasen im
     Datensatz sind (Enron-spezifisch).
   - Schreibt `clusters.jsonl` im Batch-Ordner.

3. **extract** — `extract_chains.py --batch-dir …`
   - Verarbeitet **alle** Cluster des Batches (kein `NUR_CLUSTER`) **plus
     einzelne Rauschen-Mails** (eine Mail kann schon eine vollständige Kette
     sein; grob gefiltert: kein Bulk-Absender, Body ≥ 200 Zeichen). Gesamtzahl
     der LLM-Calls gedeckelt auf `MAX_CLUSTER` (Default 300, Sicherung gegen
     versehentliche Großläufe).
   - Prompt & Multi-Chain-Logik unverändert.
   - Fortsetzbar über `verarbeitet.json` im Batch-Ordner.
   - Schreibt nach `backend/chains/chain_<batch_id>_cluster_<cid>_<k>.json`.
   - `schreibe_ketten` löscht vorher nur Dateien **mit diesem `batch_id`-Präfix**
     (Wiederholungslauf desselben Batches ist sicher, andere Batches unberührt).

`status.json` wird nach jeder Phase aktualisiert.

## 5. Neue & geänderte Dateien

| Datei | Art | Inhalt |
|---|---|---|
| `backend/parse_mailbox.py` | **neu** | `.eml`/`.mbox`/`.pst`/`.zip` → `mails.jsonl`. CLI: `--batch-dir`. |
| `backend/run_pipeline.py` | **neu** | Orchestrator: parse → cluster → extract, schreibt `status.json`. CLI: `--batch-dir`. |
| `backend/mail_utils.py` | geändert | `normalisiere_betreff` + `saeubere_body` aus `prepare_emails.py` hierher ziehen (von CSV- und Mailbox-Pfad genutzt). |
| `backend/prepare_emails.py` | geändert | nutzt die verschobenen Funktionen aus `mail_utils`; sonst unverändert (Enron-CSV, Seminar-Reproduzierbarkeit). |
| `backend/cluster_mails.py` | geändert | `--batch-dir`-Argument (alle Pfade relativ dazu); Burnet-Test nur bei vorhandenen Phrasen; kleiner-Batch-Guard für UMAP (§9). |
| `backend/extract_chains.py` | geändert | `--batch-dir`-Argument; `NUR_CLUSTER` entfällt für Batch-Läufe; `MAX_CLUSTER`-Deckel; Output-Dateiname mit `<batch_id>`-Präfix; `schreibe_ketten` scoped auf den Präfix. |
| `frontend/src/app/api/batches/route.ts` | **neu** | `POST`: Upload entgegennehmen, `batches/<id>/upload/` anlegen, `run_pipeline.py` als Kindprozess starten, `{ batch_id }` zurückgeben. |
| `frontend/src/app/api/batches/[id]/status/route.ts` | **neu** | `GET`: `status.json` des Batches ausliefern. |
| `frontend/src/components/MailUpload.tsx` | **neu** | Button + Drop-Zone, POST, danach Status-Polling mit Fortschrittsanzeige. |
| `frontend/src/app/page.tsx` | geändert | `MailUpload` einbinden; nach Abschluss `neuLaden()`. |
| `frontend/src/lib/batches.ts` | **neu** | Helfer: Batch-Ordner anlegen, `status.json` lesen, Kindprozess starten. |

**Kein Frontend-Umbau nötig für Anzeige/Bearbeitung:** Die neuen Ketten liegen
im selben flachen `backend/chains/`-Ordner. `listeChains`, `holeChain`,
Detailseite, Diagramm, Edit, Delete funktionieren unverändert.

## 6. `status.json`

```json
{
  "batch_id": "b20260910_1432_a1b2",
  "phase": "extract",                 // queued | parse | cluster | extract | done | error
  "phasen_text": "Extrahiere Aktionsketten",
  "fortschritt": { "aktuell": 12, "gesamt": 47 },
  "zahlen": { "mails": 1204, "cluster": 47, "rauschen": 180, "ketten": 9 },
  "fehler": null,
  "gestartet": "2026-09-10T14:32:01Z",
  "aktualisiert": "2026-09-10T14:38:22Z"
}
```

Das Frontend pollt alle 2 s, bis `phase` `done` oder `error` ist.

## 7. Frontend-Details

**Upload-Route** (`POST /api/batches`):

1. Multipart-Body entgegennehmen, Dateigröße begrenzen (z.B. 500 MB — `.pst`
   kann groß sein; ggf. höher).
2. `batch_id` erzeugen, `backend/batches/<batch_id>/upload/` anlegen, Datei(en)
   dort speichern.
3. `config.json` schreiben (gewähltes Modell etc.).
4. `child_process.spawn("python", ["run_pipeline.py", "--batch-dir", …], { detached: true })`,
   stdout/stderr in eine Logdatei im Batch-Ordner.
5. `{ batch_id }` zurückgeben (201).

**Status-Route** (`GET /api/batches/[id]/status`): liest und liefert
`status.json`.

**`MailUpload.tsx`:**

- Datei wählen/droppen → optional Modell-Dropdown (Sonnet/Opus) → "Extrahieren".
- Nach POST: `batch_id` merken, alle 2 s Status holen, Balken/Text anzeigen
  ("Phase 2/3 – 400/1204 Mails eingebettet").
- Bei `done`: Erfolgsmeldung + `neuLaden()` der Kettenliste.
- Bei `error`: `fehler`-Text anzeigen.

**Optional später:** Spalte/Filter "Batch" in der Kettenliste (Batch-ID aus dem
Slug-Präfix oder ein `batch`-Feld im Ketten-JSON).

## 8. Umsetzungsreihenfolge

1. `mail_utils.py`: `normalisiere_betreff` + `saeubere_body` herüberziehen,
   `prepare_emails.py` anpassen, mit Enron-CSV gegentesten (gleiche
   `mails.jsonl` wie vorher).
2. `parse_mailbox.py`: `.eml` + `.mbox` + `.zip`. Mit ein paar Beispiel-Mails
   testen.
3. `parse_mailbox.py`: `.pst` ergänzen (umgesetzt mit `pst-extractor` statt
   `readpst`, siehe §2).
4. `cluster_mails.py` + `extract_chains.py` auf `--batch-dir` umstellen,
   Batch-Präfix, `MAX_CLUSTER`, kleiner-Batch-Guard.
5. `run_pipeline.py` + `status.json`.
6. Ende-zu-Ende auf der Kommandozeile testen
   (`python run_pipeline.py --batch-dir backend/batches/testbatch`).
7. Frontend: API-Routen + `MailUpload.tsx` + Einbindung in `page.tsx`.
8. Ende-zu-Ende über die Weboberfläche testen.
9. `PIPELINE_DOKUMENTATION.md` um den Batch-/Upload-Weg ergänzen.

## 9. Grenzen & offene Punkte

- **Kleiner Batch (umgesetzt):** Bei weniger als 15 Mails wird UMAP
  übersprungen und HDBSCAN (metric cosine) direkt auf den 4096-dim Embeddings
  ausgeführt, sonst `n_neighbors = min(15, n_mails − 1)`. Bei 2–3 Mails
  entsteht ggf. nur ein Cluster oder alles ist Rauschen; die Rauschen-Mails
  werden dann trotzdem einzeln geprüft (§4). Im Test lieferten 5 Mails, die
  alle Rauschen waren, 2 Ketten.
- **`.pst`-Abhängigkeit (gelöst):** statt der externen Binary `readpst` wird
  `pst-extractor` (Node) genutzt; nur Node.js muss installiert sein.
  `readpst` bleibt als Rückfall, falls es im `PATH` liegt.
- **Kosten:** Kein Kosten-Gate (bewusst). `MAX_CLUSTER` verhindert Ausreißer;
  Standard-Modell auf Sonnet lassen, Opus nur auf Wunsch.
- **Kein Dedup zwischen Batches:** überlappende Uploads → doppelte Ketten.
  Bewusste Vereinfachung dieses Modells.
- **Embedding-Kosten bei Wieder-Upload:** jeder Batch embeddet frisch. Optionale
  spätere Optimierung: globaler Embedding-Cache mit Schlüssel = Hash(Betreff +
  Body), spart Geld ohne das Batch-Prinzip zu verletzen.
- **Nebenläufige Uploads:** v1 nimmt an, dass ein Lauf zur Zeit läuft. Bei
  Bedarf eine einfache Queue (nächster Batch startet, wenn der vorige `done`
  ist).
- **`prozess_wahrscheinlichkeit`-Semantik** wurde gerade auf "Menge/Klarheit
  des prozeduralen Wissens" umgestellt — das Frontend-Badge
  (`WahrscheinlichkeitBadge.tsx`, Schwellen 0.3/0.6, Text "% Prozess") sollte
  passend angepasst werden (0.4/0.7, "prozed. Wissen"). Noch offen.
