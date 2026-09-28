# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
run_pipeline.py
--------------------------------------------------
Orchestriert die Pipeline fuer einen hochgeladenen Batch (wird vom Frontend
gestartet, laesst sich aber auch direkt aufrufen):

    parse_mailbox.py  ->  cluster_mails.py  ->  extract_chains.py

Aufruf:
    python run_pipeline.py --batch-dir batches/<batch_id>

Erwartet <batch-dir>/upload/ mit den Rohdateien (.eml/.mbox/.pst/.zip).
Schreibt fortlaufend <batch-dir>/status.json und protokolliert die
Unterprozess-Ausgaben nach <batch-dir>/pipeline.log.

Ketten landen (mit <batch_id>-Praefix) im gemeinsamen Ordner backend/chains/.
Bestehende Ketten anderer Batches / des Enron-Laufs werden nie angefasst.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import env_laden  # noqa: F401  - liest OPENAI_API_KEY aus <Projekt>/.env

HIER = Path(__file__).parent


def jetzt() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Status:
    def __init__(self, batch_dir: Path):
        self.pfad = batch_dir / "status.json"
        self.daten = {
            "batch_id": batch_dir.name,
            "phase": "queued",
            "phasen_text": "In Warteschlange",
            "fortschritt": {"aktuell": 0, "gesamt": 0},
            "zahlen": {"mails": 0, "cluster": 0, "rauschen": 0, "ketten": 0},
            "fehler": None,
            "gestartet": jetzt(),
            "aktualisiert": jetzt(),
        }
        self.schreibe()

    def schreibe(self):
        self.daten["aktualisiert"] = jetzt()
        self.pfad.write_text(
            json.dumps(self.daten, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def phase(self, phase: str, text: str, gesamt: int = 0):
        self.daten["phase"] = phase
        self.daten["phasen_text"] = text
        self.daten["fortschritt"] = {"aktuell": 0, "gesamt": gesamt}
        self.schreibe()

    def fortschritt(self, aktuell: int, gesamt: int | None = None):
        self.daten["fortschritt"]["aktuell"] = aktuell
        if gesamt is not None:
            self.daten["fortschritt"]["gesamt"] = gesamt
        self.schreibe()

    def zahlen(self, **kw):
        self.daten["zahlen"].update(kw)
        self.schreibe()

    def fehler(self, text: str):
        self.daten["phase"] = "error"
        self.daten["phasen_text"] = "Fehler"
        self.daten["fehler"] = text
        self.schreibe()

    def fertig(self):
        self.daten["phase"] = "done"
        self.daten["phasen_text"] = "Fertig"
        self.schreibe()


def lauf(skript: str, batch_dir: Path, log, status: Status, zeilen_hook, extra_env=None):
    """Fuehrt ein Pipeline-Skript aus, streamt stdout in Log + Hook."""
    # "-u": Kindprozess unbuffered starten. Sobald stdout in eine Pipe geht
    # (statt an ein Terminal), puffert Python sonst blockweise statt
    # zeilenweise - der Fortschritt in status.json wuerde erst beim
    # Prozessende ankommen, nicht laufend.
    cmd = [sys.executable, "-u", str(HIER / skript), "--batch-dir", str(batch_dir)]
    log.write(f"\n$ {' '.join(cmd)}\n")
    log.flush()
    # PYTHONIOENCODING: an eine Pipe schreibt Python auf Windows sonst in cp1252,
    # und Zeichen ausserhalb davon (z.B. Emojis im Betreff) liessen print()
    # mit UnicodeEncodeError abbrechen.
    env = {**os.environ, **(extra_env or {}), "PYTHONUNBUFFERED": "1",
           "PYTHONIOENCODING": "utf-8"}
    # Windows: run_pipeline.py laeuft (vom Frontend gestartet) ohne Konsole;
    # ohne CREATE_NO_WINDOW oeffnete jeder Kindprozess ein leeres Konsolenfenster.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd, cwd=HIER, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
        creationflags=creationflags,
    )
    for zeile in proc.stdout:
        log.write(zeile)
        log.flush()
        zeilen_hook(zeile.rstrip("\n"))
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"{skript} endete mit Code {proc.returncode} (siehe pipeline.log)")


def zaehle_zeilen(pfad: Path) -> int:
    if not pfad.exists():
        return 0
    with open(pfad, "r", encoding="utf-8") as f:
        return sum(1 for z in f if z.strip())


def zaehle_cluster(clusters_datei: Path):
    cluster, rauschen = set(), 0
    if not clusters_datei.exists():
        return 0, 0
    with open(clusters_datei, "r", encoding="utf-8") as f:
        for z in f:
            z = z.strip()
            if not z:
                continue
            c = json.loads(z)["cluster"]
            if c == -1:
                rauschen += 1
            else:
                cluster.add(c)
    return len(cluster), rauschen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", required=True, type=Path)
    args = parser.parse_args()
    # Absolut aufloesen: die Unterprozesse laufen mit cwd=backend/.
    batch_dir: Path = args.batch_dir.resolve()
    batch_dir.mkdir(parents=True, exist_ok=True)

    status = Status(batch_dir)
    log = open(batch_dir / "pipeline.log", "w", encoding="utf-8")

    try:
        # Vorab: ohne KIT-Key koennen weder Embedding noch Extraktion laufen.
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY nicht gefunden. KIT-Toolbox-Key in die Datei .env "
                "im Projektordner eintragen (Zeile: OPENAI_API_KEY=<key>, Vorlage: "
                ".env.example)."
            )

        # 1) PARSE ----------------------------------------------------------
        status.phase("parse", "Postfach einlesen")

        re_fertig = re.compile(r"Fertig\. (\d+) Mails")

        def parse_hook(zeile: str):
            m = re_fertig.search(zeile)
            if m:
                status.zahlen(mails=int(m.group(1)))

        lauf("parse_mailbox.py", batch_dir, log, status, parse_hook)
        mails = zaehle_zeilen(batch_dir / "mails.jsonl")
        status.zahlen(mails=mails)
        if mails == 0:
            raise RuntimeError("Keine verwertbaren Mails im Upload gefunden.")

        # 2) CLUSTER ------------------------------------------------------------
        status.phase("cluster", "Mails einbetten und clustern", gesamt=mails)

        re_embed = re.compile(r"^\s*(\d+)/(\d+)\s*$")

        def cluster_hook(zeile: str):
            m = re_embed.match(zeile)
            if m:
                status.fortschritt(int(m.group(1)), int(m.group(2)))

        lauf("cluster_mails.py", batch_dir, log, status, cluster_hook)
        if not (batch_dir / "clusters.jsonl").exists():
            raise RuntimeError("Clustering hat keine clusters.jsonl erzeugt (siehe pipeline.log).")
        n_cluster, n_rauschen = zaehle_cluster(batch_dir / "clusters.jsonl")
        status.zahlen(cluster=n_cluster, rauschen=n_rauschen)
        # 0 echte Cluster ist ok: extract_chains prueft Rauschen-Mails einzeln.

        # 3) EXTRACT ----------------------------------------------------------
        status.phase("extract", "Aktionsketten extrahieren", gesamt=n_cluster)

        # Modellwahl aus config.json (vom Frontend gesetzt), optional.
        extra_env = {}
        config_datei = batch_dir / "config.json"
        if config_datei.exists():
            cfg = json.loads(config_datei.read_text(encoding="utf-8"))
            if cfg.get("modell"):
                extra_env["EXTRACT_MODEL"] = str(cfg["modell"])

        re_verarbeite = re.compile(r"Verarbeite (\d+) (?:Cluster|Gruppen)")
        re_cluster = re.compile(r"^=== Cluster ")
        zaehler = {"n": 0}

        def extract_hook(zeile: str):
            m = re_verarbeite.search(zeile)
            if m:
                status.fortschritt(0, int(m.group(1)))
            elif re_cluster.match(zeile):
                zaehler["n"] += 1
                status.fortschritt(zaehler["n"])

        lauf("extract_chains.py", batch_dir, log, status, extract_hook, extra_env)

        praefix = f"chain_{batch_dir.name}_cluster_"
        chains_dir = HIER / "chains"
        n_ketten = len(list(chains_dir.glob(f"{praefix}*.json"))) if chains_dir.exists() else 0
        status.zahlen(ketten=n_ketten)

        status.fertig()
        log.write(f"\nFertig: {n_ketten} Ketten.\n")

    except Exception as e:
        status.fehler(str(e))
        log.write(f"\nFEHLER: {e}\n")
        raise
    finally:
        log.close()


if __name__ == "__main__":
    main()
