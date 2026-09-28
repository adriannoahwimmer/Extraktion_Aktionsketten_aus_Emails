"""
cluster_mails.py
--------------------------------------------------
Gruppiert Mails aus mails.jsonl automatisch nach Vorgang (Clustering statt
Stichwortfilter), ohne die Anzahl der Cluster vorzugeben.

Ablauf:
  1. mails.jsonl laden und nach Body deduplizieren (Enron-Korpus enthaelt
     dieselbe Mail mehrfach in verschiedenen Postfaechern).
  2. Jede Mail ueber die KIT-Toolbox embedden (mit lokalem Cache, damit ein
     erneuter Lauf nicht alles neu embedded).
  3. Dimensionsreduktion mit UMAP, dann Clustering mit HDBSCAN.
  4. Ergebnis nach clusters.jsonl schreiben + Konsolen-Report.
  5. Akzeptanztest: liegen die bekannten Burnet-Mails im selben Cluster?

Einmalig vorbereiten:
    pip install openai numpy "scikit-learn>=1.3" umap-learn
    # KIT-Toolbox-API-Key setzen (PowerShell, gilt fuer diese Terminal-Sitzung):
    #   $env:OPENAI_API_KEY = "sk-..."

Ausfuehren (aus dem Ordner backend/):
    cd backend
    python cluster_mails.py
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
from openai import OpenAI

try:
    from sklearn.cluster import HDBSCAN
    HDBSCAN_QUELLE = "sklearn"
except ImportError:
    from hdbscan import HDBSCAN
    HDBSCAN_QUELLE = "hdbscan (Standalone-Paket)"

import umap

import env_laden  # noqa: F401  - liest OPENAI_API_KEY aus <Projekt>/.env
from mail_utils import lade_mails, dedupliziere, BURNET_PHRASEN, chain_wahrscheinlichkeit

# ------------------------------------------------------------------
# Einstellungen (Stellschrauben)
# ------------------------------------------------------------------
BASE_URL = "https://ki-toolbox.scc.kit.edu/api/v1"
EMBED_MODEL = "kit.qwen3-embedding-8b"

MAILS_DATEI = Path("mails.jsonl")
EMBEDDINGS_CACHE = Path("embeddings.npy")
EMBEDDINGS_IDS_CACHE = Path("embeddings_ids.json")
CLUSTERS_AUSGABE = Path("clusters.jsonl")

BATCH_SIZE = 32                # Mails pro Embedding-Request
MAX_BODY_CHARS = 6000          # lange Bodies kappen (Token-Limits)

UMAP_N_COMPONENTS = 5
UMAP_N_NEIGHBORS = 15          # Stellschraube: groesser = globalere Struktur
UMAP_METRIC = "cosine"
UMAP_RANDOM_STATE = 42

HDBSCAN_MIN_CLUSTER_SIZE = 2   # klein, da Burnet-Prozess nur ~3 Mails hat.
                                # Getestet: hoehere Werte (3+, auch mit
                                # cluster_selection_method="leaf") verschmelzen
                                # kleine falsche Cluster nur zu GROESSEREN
                                # falschen Clustern statt sie ins Rauschen zu
                                # verschieben (siehe tune_clustering.py).
                                # Kleine falsche Cluster sind guenstiger/
                                # harmloser - die eigentliche Qualitaetskontrolle
                                # passiert ueber prozess_wahrscheinlichkeit
                                # in extract_chains.py.


# ------------------------------------------------------------------
# Embedding mit lokalem Cache
# ------------------------------------------------------------------
def lade_embedding_cache():
    if EMBEDDINGS_CACHE.exists() and EMBEDDINGS_IDS_CACHE.exists():
        vektoren = np.load(EMBEDDINGS_CACHE)
        ids = json.loads(EMBEDDINGS_IDS_CACHE.read_text(encoding="utf-8"))
        return dict(zip(ids, vektoren))
    return {}


def speichere_embedding_cache(cache: dict):
    ids = list(cache.keys())
    vektoren = np.array([cache[i] for i in ids])
    np.save(EMBEDDINGS_CACHE, vektoren)
    EMBEDDINGS_IDS_CACHE.write_text(json.dumps(ids), encoding="utf-8")


def mail_text(mail) -> str:
    body = mail.get("body", "")[:MAX_BODY_CHARS]
    return f"{mail.get('subject', '')}\n\n{body}"


def embedde_fehlende(client: OpenAI, mails, cache: dict):
    fehlend = [m for m in mails if m["id"] not in cache]
    if not fehlend:
        print("Alle Mails bereits im Embedding-Cache.")
        return cache

    print(f"Embedde {len(fehlend)} neue Mails (Batch-Groesse {BATCH_SIZE}) ...")
    for start in range(0, len(fehlend), BATCH_SIZE):
        batch = fehlend[start:start + BATCH_SIZE]
        texte = [mail_text(m) for m in batch]

        antwort = client.embeddings.create(model=EMBED_MODEL, input=texte)
        for mail, eintrag in zip(batch, antwort.data):
            cache[mail["id"]] = np.array(eintrag.embedding, dtype=np.float32)

        speichere_embedding_cache(cache)
        fertig = min(start + BATCH_SIZE, len(fehlend))
        print(f"  {fertig}/{len(fehlend)}")

    return cache


# ------------------------------------------------------------------
# Dimensionsreduktion + Clustering
# ------------------------------------------------------------------
def reduziere_dimension(vektoren: np.ndarray):
    """UMAP auf UMAP_N_COMPONENTS Dimensionen. Bei sehr kleinen Batches (zu
    wenige Datenpunkte fuer n_neighbors) wird UMAP uebersprungen und direkt auf
    den Roh-Embeddings geclustert."""
    n = len(vektoren)
    if n < 15:
        print(f"Nur {n} Mails - UMAP uebersprungen, clustere auf Roh-Embeddings.")
        return vektoren, False

    n_neighbors = min(UMAP_N_NEIGHBORS, n - 1)
    reducer = umap.UMAP(
        n_components=min(UMAP_N_COMPONENTS, n - 2),
        metric=UMAP_METRIC,
        n_neighbors=n_neighbors,
        random_state=UMAP_RANDOM_STATE,
    )
    return reducer.fit_transform(vektoren), True


def clustere(vektoren: np.ndarray, reduziert: bool) -> np.ndarray:
    # Auf Roh-Embeddings (nicht UMAP-reduziert) ist Cosine die passende Metrik.
    metric = "euclidean" if reduziert else "cosine"
    modell = HDBSCAN(min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE, metric=metric)
    return modell.fit_predict(vektoren)


# ------------------------------------------------------------------
# Report + Akzeptanztest
# ------------------------------------------------------------------
def berechne_cluster_scores(mails, labels):
    """Chain-Wahrscheinlichkeit (Heuristik, siehe mail_utils) pro Cluster."""
    gruppen = {}
    for mail, label in zip(mails, labels):
        if label == -1:
            continue
        gruppen.setdefault(int(label), []).append(mail)
    return {cid: chain_wahrscheinlichkeit(gruppe) for cid, gruppe in gruppen.items()}


def schreibe_cluster_ausgabe(mails, labels, scores):
    with open(CLUSTERS_AUSGABE, "w", encoding="utf-8") as f:
        for mail, label in zip(mails, labels):
            score, gruende = scores.get(int(label), (None, []))
            eintrag = {
                "id": mail["id"],
                "cluster": int(label),
                "subject": mail.get("subject", ""),
                "date": mail.get("date", ""),
                "from": mail.get("from", ""),
                "to": mail.get("to", ""),
                "chain_score": score,
                "chain_gruende": gruende,
            }
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def drucke_report(mails, labels, scores):
    anzahl_rauschen = int(np.sum(labels == -1))
    cluster_ids = sorted(set(labels.tolist()) - {-1})
    print(f"\nCluster gefunden: {len(cluster_ids)}")
    print(f"Rauschen (Label -1): {anzahl_rauschen} von {len(mails)} Mails")

    groessen = sorted(cluster_ids, key=lambda c: -int(np.sum(labels == c)))
    print("\nGroesste Cluster (bis zu 10), je 3 Beispiel-Betreffs + Chain-Score:")
    for c in groessen[:10]:
        indizes = [i for i, l in enumerate(labels) if l == c]
        groesse = len(indizes)
        beispiele = [mails[i].get("subject", "") for i in indizes[:3]]
        score, gruende = scores.get(c, (None, []))
        print(f"  Cluster {c} ({groesse} Mails, Chain-Score {score}): {'; '.join(gruende)}")
        for b in beispiele:
            print(f"    - {b!r}")


def burnet_akzeptanztest(mails, labels):
    print("\n--- Burnet-Akzeptanztest ---")
    treffer_cluster = set()
    gefunden = False
    for mail, label in zip(mails, labels):
        body = mail.get("body", "")
        if any(phrase in body for phrase in BURNET_PHRASEN):
            gefunden = True
            treffer_cluster.add(int(label))
            print(f"  Cluster {label} | {mail.get('subject', '')!r} | {mail.get('date', '')}")

    if not gefunden:
        print("  Keine Mails mit den Burnet-Phrasen gefunden.")
        return

    print(f"\nBurnet-Mails liegen in Cluster(n): {treffer_cluster}")
    if len(treffer_cluster) == 1 and -1 not in treffer_cluster:
        print("Erfolg: alle Burnet-Mails liegen im selben Cluster.")
    else:
        print("Noch nicht gut: Burnet-Mails sind verstreut oder als Rauschen markiert.")


# ------------------------------------------------------------------
# Hauptprogramm
# ------------------------------------------------------------------
def _setze_batch_pfade(batch_dir: Path):
    """Lenkt alle Ein-/Ausgabepfade in ein Batch-Verzeichnis um."""
    global MAILS_DATEI, EMBEDDINGS_CACHE, EMBEDDINGS_IDS_CACHE, CLUSTERS_AUSGABE
    MAILS_DATEI = batch_dir / "mails.jsonl"
    EMBEDDINGS_CACHE = batch_dir / "embeddings.npy"
    EMBEDDINGS_IDS_CACHE = batch_dir / "embeddings_ids.json"
    CLUSTERS_AUSGABE = batch_dir / "clusters.jsonl"


def main():
    parser = argparse.ArgumentParser(description="Mails clustern (siehe Modul-Docstring).")
    parser.add_argument(
        "--batch-dir", type=Path, default=None,
        help="Batch-Verzeichnis; ohne Angabe wird im aktuellen Ordner gearbeitet (Enron).",
    )
    args = parser.parse_args()
    if args.batch_dir is not None:
        _setze_batch_pfade(args.batch_dir)

    if not MAILS_DATEI.exists():
        print(f"{MAILS_DATEI} nicht gefunden.")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Kein OPENAI_API_KEY gesetzt.")
        print('PowerShell:  $env:OPENAI_API_KEY = "sk-..."  (dein KIT-Toolbox-Key)')
        return

    print(f"HDBSCAN-Quelle: {HDBSCAN_QUELLE}")

    mails = lade_mails(MAILS_DATEI)
    mails_dedup = dedupliziere(mails)
    print(f"Mails vorher: {len(mails)}  |  nach Deduplizierung: {len(mails_dedup)}")

    client = OpenAI(base_url=BASE_URL)
    cache = lade_embedding_cache()
    cache = embedde_fehlende(client, mails_dedup, cache)

    vektoren = np.array([cache[m["id"]] for m in mails_dedup])
    print(f"\nReduziere Dimension ({vektoren.shape[1]} -> {UMAP_N_COMPONENTS}) mit UMAP ...")
    reduziert, wurde_reduziert = reduziere_dimension(vektoren)

    print("Clustere mit HDBSCAN ...")
    labels = clustere(reduziert, wurde_reduziert)

    scores = berechne_cluster_scores(mails_dedup, labels)
    schreibe_cluster_ausgabe(mails_dedup, labels, scores)
    print(f"\nErgebnis gespeichert in: {CLUSTERS_AUSGABE.resolve()}")

    drucke_report(mails_dedup, labels, scores)
    burnet_akzeptanztest(mails_dedup, labels)


if __name__ == "__main__":
    main()
