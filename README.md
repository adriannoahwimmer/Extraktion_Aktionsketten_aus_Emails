# Extraktion von Aktionsketten aus E-Mails

Praktisches Seminar am KIT. Das Projekt extrahiert **implizites prozedurales Wissen**
aus E-Mail-Kommunikation und macht es als **Aktionsketten** explizit: wiederkehrende
Abläufe mit Akteuren, Aufgaben, Entscheidungspunkten und wörtlichen Belegzitaten aus
den Mails. Die Anzahl der Prozesse wird nicht vorgegeben, und es wird nicht nach
Stichworten gesucht.

**Ansatz:** Mails säubern → semantisch zu Vorgängen gruppieren (Embedding, UMAP,
HDBSCAN) → pro Gruppe mit einem LLM (Claude über die KIT-Toolbox) belegte
Aktionsketten extrahieren → in einer Weboberfläche anzeigen, durchsuchen und
bearbeiten.

## Funktionen

- **Postfach hochladen** (`.eml`, `.mbox`, `.pst`, `.zip`) und daraus automatisch
  Aktionsketten extrahieren, mit Fortschrittsanzeige und Modellwahl
  (Claude Sonnet 5 oder Opus 4.8).
- **Kettenliste** mit Volltextsuche über Titel, Zusammenfassung, Tags, Akteure und
  Aktionen.
- **Detailansicht** mit Ablaufdiagramm (Aufgaben, Entscheidungs-Gateways, bedingte
  Kanten), Akteuren und Quellenmails samt Belegzitaten.
- **Ketten manuell anlegen, bearbeiten und löschen.**
- **Enron-Pipeline** auf der Kommandozeile zur Reproduktion der Ergebnisse auf dem
  Enron-Korpus. 51 extrahierte Ketten liegen bereits im Repository.

## Architektur

```
Weg A: Enron (Kommandozeile)          Weg B: Upload (Weboberfläche)
data/emails.csv                        .eml / .mbox / .pst / .zip
   │ prepare_emails.py                    │ parse_mailbox.py   (.pst: tools/pst)
   ▼                                      ▼
mails.jsonl  ◄──── gleiches Schema ────►  batches/<id>/mails.jsonl
   │ cluster_mails.py                     │ cluster_mails.py --batch-dir
   ▼   (Embedding → UMAP → HDBSCAN)       ▼
clusters.jsonl                            batches/<id>/clusters.jsonl
   │ extract_chains.py                    │ extract_chains.py --batch-dir
   ▼   (LLM pro Cluster)                  ▼   (gesteuert von run_pipeline.py)
        backend/chains/*.json  ──►  Frontend (Next.js): Liste, Diagramm, Bearbeiten
```

- **Backend** (`backend/`, Python): Pipeline-Skripte. Modelle über die
  [KIT-Toolbox](https://ki-toolbox.scc.kit.edu) (OpenAI-kompatible API):
  Embedding `kit.qwen3-embedding-8b`, Extraktion `google.claude-sonnet-5`.
- **Frontend** (`frontend/`, Next.js/React): liest und schreibt die Ketten direkt als
  JSON-Dateien in `backend/chains/` und startet für Uploads die Python-Pipeline als
  Hintergrundprozess.

## Voraussetzungen

| Software | Version | Zweck |
|---|---|---|
| Python | ≥ 3.10 (getestet mit 3.13) | Pipeline |
| Node.js | ≥ 20 (getestet mit 24) | Weboberfläche, Einlesen von `.pst` |
| KIT-Toolbox-API-Key | – | Embeddings und LLM-Extraktion |

Ohne API-Key lassen sich die vorhandenen Ketten ansehen und bearbeiten. Für Uploads
und die Pipeline ist der Key nötig.

## Installation

```bash
git clone https://github.com/adriannoahwimmer/Extraktion_Aktionsketten_aus_Emails.git
cd Extraktion_Aktionsketten_aus_Emails
```

**1. Python-Umgebung** (im Projektordner; das Frontend findet `.venv` automatisch)

```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Frontend-Abhängigkeiten**

```bash
cd frontend
npm install
cd ..
```

**3. API-Key hinterlegen:** `.env.example` nach `.env` kopieren und den
KIT-Toolbox-Key eintragen:

```
OPENAI_API_KEY=<dein-KIT-Toolbox-Key>
```

## Starten

```bash
cd frontend
npm run dev
```

Danach <http://localhost:3000> im Browser öffnen. Für einen Produktions-Build:
`npm run build` und anschließend `npm start`.

## Bedienung

**Ketten ansehen:** Die Startseite listet alle Ketten, mit Suchfeld und Badge
„Prozesswissen“: die Selbsteinschätzung des LLM, wie viel klar erkennbares
prozedurales Wissen eine Kette enthält. Farben: rot < 40 %, gelb < 70 %, grün ab 70 %.
„Ansehen“ öffnet Diagramm, Akteure und Belege.

**Postfach hochladen:** Im Kasten „Postfach hochladen“ eine Datei wählen, das Modell
auswählen und „Aktionsketten extrahieren“ klicken. Die Pipeline läuft im Hintergrund
(einlesen → einbetten und clustern → extrahieren). Anschließend erscheinen die neuen
Ketten in der Liste. Jeder Upload ist ein eigener Batch: Bestehende Ketten bleiben
unverändert.

> **Zum Ausprobieren:** [`examples/beispiel_postfach.mbox`](examples/beispiel_postfach.mbox)
> enthält 9 fiktive Mails: einen Beschaffungsvorgang über mehrere Mails, eine
> Einzelmail mit einem Reisekosten-Ablauf, einen Newsletter und Smalltalk.
> Ergebnis eines Testlaufs (Sonnet 5, ca. 5 Minuten): Der Reisekosten-Ablauf ergibt
> eine Kette mit Entscheidungspunkt. Den Beschaffungsvorgang verteilt das Clustering
> auf mehrere Gruppen, daraus entstehen Teilketten (Anfrage → Angebot → Bestellung,
> Freigabe, Einrichtung). Newsletter und Smalltalk ergeben keine Kette. Weil das
> Modell nicht deterministisch arbeitet, können einzelne Ergebnisse abweichen.

Exportformate: Gmail (Google Takeout) liefert `.mbox`, Outlook Desktop `.pst`
(Export über „Datei → Öffnen und Exportieren“), Thunderbird und Apple Mail einzelne
`.eml`-Dateien, die sich als `.zip` bündeln lassen.

> **Datenschutz:** Die Inhalte hochgeladener Mails werden zur Verarbeitung an die
> KIT-Toolbox gesendet. Uploads (`backend/batches/`) und daraus extrahierte Ketten
> sind per `.gitignore` vom Repository ausgeschlossen.

## Enron-Pipeline reproduzieren (optional)

Die Enron-Ergebnisse in `backend/chains/chain_cluster_*.json` lassen sich aus dem
Rohkorpus neu erzeugen:

1. `emails.csv` aus dem
   [Enron Email Dataset (Kaggle)](https://www.kaggle.com/datasets/wcukierski/enron-email-dataset)
   herunterladen (ca. 1,4 GB) und als `data/emails.csv` ablegen.
2. Im Ordner `backend/` bei aktivierter `.venv`:

```bash
python prepare_emails.py     # CSV säubern      -> mails.jsonl
python cluster_mails.py      # einbetten + clustern -> clusters.jsonl
python extract_chains.py     # Stichprobe: 5 größte Cluster + Burnet-Kontrolle
python extract_chains.py --alle   # oder: alle Cluster + Einzelmails (≤ 300 LLM-Aufrufe)
```

`--alle` ist fortsetzbar. Nach einem Abbruch überspringt ein erneuter Aufruf bereits
verarbeitete Cluster; zum Neustart `backend/verarbeitet.json` löschen. Die Läufe
verursachen API-Kosten, und die Ergebnisse sind nicht bitgenau reproduzierbar, weil
das Modell `temperature` nicht unterstützt.

## Projektstruktur

```
├── backend/
│   ├── prepare_emails.py      Enron-CSV -> mails.jsonl
│   ├── parse_mailbox.py       .eml/.mbox/.pst/.zip -> mails.jsonl (Upload)
│   ├── cluster_mails.py       Embedding -> UMAP -> HDBSCAN -> clusters.jsonl
│   ├── extract_chains.py      LLM-Extraktion -> chains/*.json (enthält den Prompt)
│   ├── run_pipeline.py        steuert einen Upload-Batch, schreibt status.json
│   ├── mail_utils.py          gemeinsame Reinigung, Deduplizierung, Heuristik
│   ├── env_laden.py           liest den API-Key aus .env
│   ├── tune_clustering.py     Hilfsskript: UMAP/HDBSCAN-Parameter-Sweep
│   ├── tools/pst/             Node-Werkzeug zum Lesen von .pst-Dateien
│   ├── eval/                  Auswertung der Enron-Ketten (siehe eval/README.md)
│   └── chains/                extrahierte Aktionsketten (JSON)
├── frontend/                  Next.js-Weboberfläche (src/app, src/components, src/lib)
├── docs/                      Dokumentation (siehe unten)
├── examples/                  Beispiel-Postfach, handannotierte Referenzkette (Burnet)
├── requirements.txt           Python-Abhängigkeiten
└── .env.example               Vorlage für den API-Key
```

## Dokumentation

- [docs/PROJEKT_ZUSAMMENFASSUNG.md](docs/PROJEKT_ZUSAMMENFASSUNG.md): Ziel,
  Funktionsumfang, Methodik und Entscheidungen im Überblick
- [docs/PIPELINE_DOKUMENTATION.md](docs/PIPELINE_DOKUMENTATION.md): Pipeline im
  Detail, Experimente (Modellwahl, Heuristik, Parameter-Tuning)
- [docs/UPLOAD_FEATURE_PLAN.md](docs/UPLOAD_FEATURE_PLAN.md): Konzept und Umsetzung
  des Upload-Wegs
- [docs/aktionskettenstruktur.json](docs/aktionskettenstruktur.json): Vorlage des
  Aktionsketten-Schemas
- [backend/README.md](backend/README.md): Übersicht der Skripte

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| Upload meldet „OPENAI_API_KEY nicht gefunden“ | `.env` im Projektordner anlegen (siehe Installation), Dev-Server neu starten |
| Upload bricht ab, Fehler 401 | Key ungültig oder abgelaufen, neuen Key in der KIT-Toolbox erzeugen |
| Fehlerdetails zu einem Upload | `backend/batches/<batch_id>/pipeline.log` |
| `.pst` wird nicht gelesen | Node.js muss im `PATH` liegen; beim ersten `.pst`-Upload wird `pst-extractor` automatisch installiert |
| Erster Upload dauert länger | einmalige Kompilierung von UMAP/numba (~30–60 s) |

---

Entwickelt mit Unterstützung von [Claude Code](https://claude.com/claude-code) (Anthropic).
