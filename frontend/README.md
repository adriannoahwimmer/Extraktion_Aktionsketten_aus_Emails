# frontend/ – Weboberfläche

Next.js-Anwendung zum Anzeigen, Durchsuchen, Bearbeiten und Hochladen von
Aktionsketten. Installation und Start: siehe [README im Projektordner](../README.md).

```bash
npm install
npm run dev      # Entwicklung, http://localhost:3000
npm run build    # Produktions-Build, danach: npm start
```

Der Server muss aus diesem Ordner gestartet werden: Die Ketten liegen in
`../backend/chains/`, und Uploads starten `../backend/run_pipeline.py` (bevorzugt mit
dem Python aus `../.venv`).

| Pfad | Inhalt |
|---|---|
| `src/app/page.tsx` | Startseite: Upload, Suche, Kettenliste |
| `src/app/chains/[slug]/` | Detailansicht (Diagramm, Akteure, Belege) und Bearbeiten |
| `src/app/chains/new/` | Kette manuell anlegen |
| `src/app/api/chains/` | REST-Routen: Ketten lesen, anlegen, ändern, löschen |
| `src/app/api/batches/` | Upload entgegennehmen, Pipeline starten, Status abfragen |
| `src/components/` | Ablaufdiagramm (React Flow + dagre), Formular, Upload, Badge |
| `src/lib/` | Dateizugriff auf die Ketten, Batch-Verwaltung, Typen |
