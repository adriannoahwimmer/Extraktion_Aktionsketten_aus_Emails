# backend/eval/ – Auswertung der Enron-Ketten

Skripte zur Evaluation der 51 Enron-Aktionsketten (`backend/chains/chain_cluster_*.json`).
Alle Skripte lesen `backend/chains/` nur; Ergebnisse landen in `out/`.

**Voraussetzungen:** die lokalen Daten des Enron-Laufs (`backend/mails.jsonl`,
`backend/clusters.jsonl`, `backend/verarbeitet.json`; nicht im Repository, siehe
Haupt-README zur Reproduktion) und `pip install -r backend/eval/requirements.txt`
(tiktoken). Aufruf jeweils aus `backend/eval/`.

| Schritt | Skript | Ergebnis in `out/` |
|---|---|---|
| 1 Kennzahlen | `kennzahlen.py` | `kennzahlen.md/.json` – Ketten- und Cluster-Kennzahlen, Abgleich mit dem Bericht |
| 2 Belegpruefung | `belegpruefung.py` | `belegpruefung.md/.csv` – strikte Pruefung der Belegzitate, Liste der Fehlschlaege |
| 3 Token-Kompression | `token_kompression.py` | `token_kompression.md/.csv` – Tokens Kette vs. Quellmails (tiktoken cl100k_base als Naeherung) |
| 4 Burnet | `burnet.py [--neu]` | `burnet_vergleich.md`, `burnet/` – Gold-Kette vs. Extraktion, Zuordnungsvorschlag (**API-Kosten** bei der ersten Extraktion) |
| 4b Burnet-Bestaetigung | `burnet_bestaetigung.py` | `burnet_bestaetigung.md` – Liste zum Bestaetigen der Zuordnung (Knoten, Ketten, Kanten) |
| 5 Bewertungsbogen | `bewertungsbogen.py [--ueberschreiben]` | `bewertung.csv`, `bewertung/NN_<chain_id>.md` – Blindbewertung, Seed 42 |
| 6 Auswertung | `auswertung.py [--datei …]` | `auswertung.md` – Anzahl je Urteil, Anteil korrekt (U+E), Median p je Urteil |
| 7 Herkunft | `herkunft.py [--claude-protokolle <ordner>]` | `herkunft_ketten.md` – Modell und Prompt-Stand der Ketten |
| 8 Smoke-Test | `bash smoke_test.sh [zielordner]` | Protokoll auf der Konsole; Ergebnis des letzten Laufs: `smoke_test.md` (**API-Kosten**) |
| Laufpruefung | `laufpruefung.py [--claude-protokolle <ordner>]` | `LAUFPRUEFUNG.md` – Datengrundlage, `verarbeitet.json` vs. Top-300, erhaltene Laufausgabe, Rekonstruktion des Ablaufs |
| Zusammenfassung | `zusammenfassung.py` | `ZUSAMMENFASSUNG.md` – Schritte 1–4, 7, 8 auf einen Blick (liest nur die Dateien in `out/`) |

`burnet.py` und `herkunft.py` legen ihre Befunde zusaetzlich als `burnet.json` bzw.
`herkunft_ketten.json` ab; daraus erzeugt `zusammenfassung.py` die Zusammenfassung.

Gemeinsame Funktionen (Laden, Zuordnung `sources[]` → Mail ueber Absender, Datum,
Betreff und bei Gleichstand Empfaenger) liegen in `eval_utils.py`.

**Bewerten:** `out/bewertung.csv` in Excel oder einem Editor ausfuellen (Trennzeichen `;`),
dabei je Kette die Datei `out/bewertung/NN_<chain_id>.md` lesen (NN = Zeile). Urteil in Spalte
`k1`: `U` = korrekt, uebertragbares Verfahren; `E` = korrekt, einmaliger Vorgang; `F` = fehlerhaft;
`tasks_korrekt`, `edges_korrekt` und `notiz` optional. Danach `python auswertung.py` (wertet nur
Zeilen mit Urteil aus). `bewertungsbogen.py` ueberschreibt eine vorhandene `bewertung.csv` nur mit
`--ueberschreiben`.
