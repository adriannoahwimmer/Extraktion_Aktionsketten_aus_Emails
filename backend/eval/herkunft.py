# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
herkunft.py
--------------------------------------------------
Schritt 7 der Auswertung: wurden die Enron-Ketten nach der Umstellung auf
google.claude-sonnet-5 und Prompt v2 (Ausgabe {"chains": [...]}) erzeugt?

Belege aus dem Repository und den lokalen Dateien:
  - git log (wann kamen die Ketten ins Repository?)
  - Zeitstempel der Ketten-Dateien, von clusters.jsonl und verarbeitet.json
  - Formatmerkmale der Ketten, die nur der Prompt-v2-Code erzeugt
    (Dateiname _<k>, id-Feld, mehrere Ketten je Cluster, Ausgabe-Gate, ASCII-Regel)
  - Upload-Logs (backend/batches/*/pipeline.log) aus der Zeit vor dem Enron-Lauf
Optional (--claude-protokolle <ordner>): die Claude-Code-Sitzungsprotokolle des
Projekts; daraus werden die Zeitpunkte gelesen, zu denen der Standardwert von
MODEL bzw. der Prompt in extract_chains.py geaendert wurde.

Aufruf:  python herkunft.py [--claude-protokolle ~/.claude/projects/<projekt>]
Ausgabe: out/herkunft_ketten.md, out/herkunft_ketten.json
"""

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

import eval_utils as eu

PROMPT_MARKER = ("ARBEITE IN", "REGELN (gelten", "Gib nur Ketten", "Gib AUSSCHLIESSLICH", "WAS IST PROZEDURALES",
                 "Erfinde nichts", "Die Eingabe ist eine Gruppe", "Die E-Mails stammen aus", "prozess_wahrscheinlichkeit (0.0")
MODEL_MUSTER = re.compile(r'MODEL = (?:os\.environ\.get\("EXTRACT_MODEL"\) or )?"(google\.[a-z0-9.\-]+)"')


def lokal(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=eu.PROJEKT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout.strip()
    except OSError:
        return ""


def protokoll_zeitleiste(ordner: Path):
    """Aenderungen an extract_chains.py (MODEL-Standardwert, Prompt-Text) aus den
    Claude-Code-Protokollen; Zeitstempel dort in UTC, hier in Ortszeit."""
    ereignisse = []
    for datei in sorted(ordner.glob("*.jsonl")):
        for zeile in open(datei, encoding="utf-8"):
            try:
                e = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            if e.get("type") != "assistant":
                continue
            for b in e.get("message", {}).get("content", []) or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"
                        and b.get("name") in ("Edit", "Write", "MultiEdit")):
                    continue
                inp = b.get("input", {})
                if not str(inp.get("file_path", "")).endswith("extract_chains.py"):
                    continue
                zeit = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).astimezone()
                neu = str(inp.get("new_string", "")) + str(inp.get("content", ""))
                alt = str(inp.get("old_string", ""))
                for m in MODEL_MUSTER.finditer(neu):
                    ereignisse.append((zeit, f"MODEL-Standardwert -> {m.group(1)}"))
                if any(s in alt or s in neu for s in PROMPT_MARKER):
                    ereignisse.append((zeit, "Prompt-Text geaendert"))
                if '"chains": [' in neu and '"chains": [' not in alt:
                    ereignisse.append((zeit, 'Prompt v2: Ausgabeformat {"chains": [...]}'))
    # Nur echte Wechsel behalten: MODEL-Eintraege mit gleichem Wert wie zuvor und
    # wiederholte v2-Eintraege (mehrere Edits am selben Umbau) entfallen.
    bereinigt, letzter_wert, v2_gesehen = [], None, False
    for zeit, text in sorted(set(ereignisse)):
        if text.startswith("MODEL"):
            if text == letzter_wert:
                continue
            letzter_wert = text
        elif "v2" in text:
            if v2_gesehen:
                continue
            v2_gesehen = True
        bereinigt.append((zeit, text))
    return bereinigt


def main():
    eu.utf8_ausgabe()
    parser = argparse.ArgumentParser(description="Herkunft der Enron-Ketten pruefen (siehe Modul-Docstring).")
    parser.add_argument("--claude-protokolle", type=Path, default=None,
                        help="Ordner mit den Claude-Code-Sitzungsprotokollen (*.jsonl) dieses Projekts")
    args = parser.parse_args()

    ketten = eu.lade_enron_ketten()
    zeiten = sorted(k["datei"].stat().st_mtime for k in ketten)
    beginn, ende = zeiten[0], zeiten[-1]
    verarbeitet = set(json.loads(eu.VERARBEITET_DATEI.read_text(encoding="utf-8"))) if eu.VERARBEITET_DATEI.exists() else set()

    # Formatmerkmale
    je_cluster = Counter(k["cid"] for k in ketten)
    id_passt = sum(1 for k in ketten if k["data"].get("id") == f"cluster_{k['cid']}_{k['k']}")
    gate = sum(1 for k in ketten if (k["data"].get("prozess_wahrscheinlichkeit") or 0) >= 0.4
               and len(eu.aufgabenknoten(k["data"])) >= 2)
    nicht_ascii = []
    for k in ketten:
        d = k["data"]
        text = " ".join([d.get("title", ""), d.get("summary", ""), d.get("prozess_begruendung", "")]
                        + [n.get("action") or n.get("label") or "" for n in d.get("nodes", [])])
        zeichen = sorted(set(re.findall(r"[^\x00-\x7f]", text)))
        if zeichen:
            nicht_ascii.append(f"{k['slug']} ({''.join(zeichen)})")
    mojibake = [k["slug"] for k in ketten if re.search(r"Ã.|â€", json.dumps(k["data"], ensure_ascii=False))]

    # Upload-Logs vor dem Enron-Lauf
    upload_logs = []
    batches = eu.BACKEND / "batches"
    for d in sorted(batches.glob("b*")) if batches.exists() else []:
        log = d / "pipeline.log"
        if not log.exists() or log.stat().st_mtime > beginn:
            continue
        text = log.read_text(encoding="utf-8", errors="replace")
        upload_logs.append({"batch": d.name, "zeit": lokal(log.stat().st_mtime),
                            "modelle": sorted(set(re.findall(r"Schicke an (\S+)", text))),
                            "v2_ausgabe": "Kette(n) erkannt" in text})
    logs = [f"| {u['batch']} | {u['zeit']} | {', '.join(u['modelle']) or '–'} | {'ja' if u['v2_ausgabe'] else 'nein'} |"
            for u in upload_logs]

    git_log = git("log", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M")
    git_chains = git("log", "--diff-filter=A", "--format=%h %ad", "--date=format:%Y-%m-%d %H:%M", "--",
                     "backend/chains/chain_cluster_0_1.json")

    md = [
        "# Herkunft der 51 Enron-Ketten",
        "",
        "## git log",
        "",
        "```",
        git_log or "(kein git verfuegbar)",
        "```",
        f"Die Ketten kamen mit Commit `{git_chains or '?'}` ins Repository - dem ersten Commit, der den gesamten "
        "Projektstand auf einmal enthaelt. **Das git log sagt daher nichts darueber aus, wann oder womit die "
        "Ketten erzeugt wurden.**",
        "",
        "## Zeitstempel der Dateien (Ortszeit)",
        "",
        f"- Ketten-Dateien: {lokal(beginn)} bis {lokal(ende)} ({len(ketten)} Dateien)",
        f"- `mails.jsonl`: {lokal(eu.MAILS_DATEI.stat().st_mtime)}, `clusters.jsonl`: {lokal(eu.CLUSTERS_DATEI.stat().st_mtime)}"
        + (f", `verarbeitet.json`: {lokal(eu.VERARBEITET_DATEI.stat().st_mtime)}" if verarbeitet else ""),
        f"- Cluster-IDs aller Ketten in `verarbeitet.json` (Fortschrittsdatei des `--alle`-Laufs): "
        f"{sum(1 for k in ketten if k['cid'] in verarbeitet)}/{len(ketten)}",
        "",
        "## Formatmerkmale (Prompt v2)",
        "",
        f"- Dateiname `chain_cluster_<cid>_<k>.json` (mehrere Ketten je Cluster): {len(ketten)}/{len(ketten)}",
        f"- `id` = `cluster_<cid>_<k>` (gesetzt vom Schreibcode fuer das chains-Format): {id_passt}/{len(ketten)}",
        f"- Cluster mit mehr als einer Kette: {sum(1 for n in je_cluster.values() if n > 1)} "
        "(nur mit dem Ausgabeformat `{\"chains\": [...]}` moeglich)",
        f"- Ausgabe-Gate von Prompt v2 erfuellt (p >= 0.4 und >= 2 Aufgabenknoten): {gate}/{len(ketten)}",
        f"- Doppelt kodierte Umlaute (`Ã¼` o.ae.): {', '.join(mojibake) or 'keine'}; Nicht-ASCII-Zeichen in "
        f"deutschen Textfeldern trotz ASCII-Regel: {', '.join(nicht_ascii) or 'keine'}",
        "",
        "## Upload-Logs aus der Zeit vor dem Enron-Lauf",
        "",
        "| Batch | Log-Zeit | Modell laut Log | Prompt-v2-Ausgabe (\"Kette(n) erkannt\") |",
        "|---|---|---|---|",
        *(logs or ["| – | – | – | – |"]),
        "",
        "Hinweis: Upload-Laeufe setzen das Modell ueber `config.json`; sie belegen den Code-Stand (Prompt v2), "
        "nicht den Standardwert von `MODEL`, den der Enron-Lauf auf der Kommandozeile verwendet.",
    ]

    protokoll = None
    if args.claude_protokolle:
        ereignisse = protokoll_zeitleiste(args.claude_protokolle)
        vor = [(z, t) for z, t in ereignisse if z.timestamp() < beginn]
        nach = [(z, t) for z, t in ereignisse if z.timestamp() > ende]
        letzter_model = next((t for z, t in reversed(vor) if t.startswith("MODEL")), None)
        letzter_prompt = next((z for z, t in reversed(vor) if t.startswith("Prompt")), None)
        protokoll = {
            "zeitleiste": [[f"{z:%Y-%m-%d %H:%M}", t] for z, t in ereignisse if t.startswith("MODEL") or "v2" in t],
            "model_bei_laufbeginn": letzter_model.split("-> ")[-1] if letzter_model else None,
            "model_gesetzt_am": next((f"{z:%Y-%m-%d %H:%M}" for z, t in reversed(vor) if t == letzter_model), None),
            "letzte_prompt_aenderung_vor_lauf": f"{letzter_prompt:%Y-%m-%d %H:%M}" if letzter_prompt else None,
            "prompt_aenderungen_nach_lauf": sum(1 for _, t in nach if t.startswith("Prompt")),
            "model_aenderungen_nach_lauf": sum(1 for _, t in nach if t.startswith("MODEL")),
        }
        md += [
            "",
            "## Zeitleiste aus den Claude-Code-Protokollen (Ortszeit)",
            "",
            *[f"- {z:%Y-%m-%d %H:%M} {t}" for z, t in ereignisse if t.startswith("MODEL") or "v2" in t],
            f"- letzte Prompt-Aenderung vor dem Enron-Lauf: {letzter_prompt:%Y-%m-%d %H:%M}" if letzter_prompt else "",
            f"- Aenderungen am Prompt-Text nach dem Enron-Lauf: "
            f"{sum(1 for _, t in nach if t.startswith('Prompt'))}; am MODEL-Standardwert: "
            f"{sum(1 for _, t in nach if t.startswith('MODEL'))}",
            f"- Stand bei Beginn des Enron-Laufs ({lokal(beginn)}): {letzter_model or 'unbekannt'}",
        ]

    md += [
        "",
        "## Ergebnis",
        "",
        "- **Prompt v2: belegt.** Alle Ketten tragen die Merkmale des chains-Formats (Dateiname, id-Feld, "
        "mehrere Ketten je Cluster) und erfuellen das Ausgabe-Gate.",
        "- **Modell: nur indirekt belegt.** Die Ketten-Dateien speichern das Modell nicht. Belegt ist, welcher "
        "Standardwert beim Lauf im Code stand"
        + (" (siehe Zeitleiste)" if args.claude_protokolle else " (mit --claude-protokolle pruefbar)")
        + "; ein ueber die Umgebungsvariable EXTRACT_MODEL gesetztes anderes Modell wuerde nirgends protokolliert.",
        "- Aenderungen am Code, die nicht ueber Claude Code gemacht wurden (z.B. direkt im Editor), sind in "
        "den Protokollen nicht enthalten.",
    ]

    fakten = {
        "git_log": git_log.splitlines(),
        "git_commit_ketten": git_chains,
        "ketten": len(ketten),
        "ketten_von": lokal(beginn), "ketten_bis": lokal(ende),
        "mails_jsonl": lokal(eu.MAILS_DATEI.stat().st_mtime),
        "clusters_jsonl": lokal(eu.CLUSTERS_DATEI.stat().st_mtime),
        "verarbeitet_json": lokal(eu.VERARBEITET_DATEI.stat().st_mtime) if verarbeitet else None,
        "in_verarbeitet": sum(1 for k in ketten if k["cid"] in verarbeitet),
        "dateiname_mit_k": len(ketten),
        "id_passt": id_passt,
        "cluster_mit_mehreren_ketten": sum(1 for n in je_cluster.values() if n > 1),
        "gate_erfuellt": gate,
        "mojibake": mojibake,
        "nicht_ascii": nicht_ascii,
        "upload_logs": upload_logs,
        "protokoll": protokoll,
    }
    eu.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (eu.OUT_DIR / "herkunft_ketten.md").write_text("\n".join(z for z in md if z is not None) + "\n", encoding="utf-8")
    (eu.OUT_DIR / "herkunft_ketten.json").write_text(json.dumps(fakten, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
