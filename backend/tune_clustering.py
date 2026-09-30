# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
tune_clustering.py
--------------------------------------------------
Hilfsskript (nicht Teil der Pipeline): vergleicht mehrere UMAP/HDBSCAN-
Parameterkombinationen auf den bereits gecachten Embeddings (kein API-Aufruf)
- Anzahl Cluster, Rauschen-Quote und Burnet-Akzeptanztest - und zeigt fuer
jede Kombination die groessten Cluster zur qualitativen Pruefung.

Grundlage der Parameterwahl in cluster_mails.py, Ergebnisse siehe
docs/archiv/PIPELINE_DOKUMENTATION.md, Abschnitt 5.3.

Aufruf (aus backend/, nachdem cluster_mails.py den Embedding-Cache angelegt hat):
    python tune_clustering.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN

import umap

from mail_utils import lade_mails, dedupliziere, BURNET_PHRASEN

MAILS_DATEI = Path("mails.jsonl")
EMBEDDINGS_CACHE = Path("embeddings.npy")
EMBEDDINGS_IDS_CACHE = Path("embeddings_ids.json")

UMAP_N_COMPONENTS = 5
UMAP_METRIC = "cosine"
UMAP_RANDOM_STATE = 42

# Zu vergleichende Kombinationen.
N_NEIGHBORS_OPTIONEN = [10, 15, 30, 50]
MIN_CLUSTER_SIZE_OPTIONEN = [2, 3, 4]
# "eom" (Standard) waehlt eher groessere, stabile Cluster aus der
# HDBSCAN-Hierarchie; "leaf" nimmt die untersten Ebenen und laesst
# Unpassendes eher als Rauschen stehen.
SELECTION_METHOD_OPTIONEN = ["eom", "leaf"]

# Fuer die qualitative Stichprobe: so viele der groessten Cluster anzeigen.
STICHPROBE_CLUSTER = 3
STICHPROBE_BETREFFS = 4


def lade_daten():
    mails = dedupliziere(lade_mails(MAILS_DATEI))
    cache_ids = json.loads(EMBEDDINGS_IDS_CACHE.read_text(encoding="utf-8"))
    cache = dict(zip(cache_ids, np.load(EMBEDDINGS_CACHE)))
    vektoren = np.array([cache[m["id"]] for m in mails])
    return mails, vektoren


def burnet_ok(mails, labels):
    treffer_cluster = set()
    for mail, label in zip(mails, labels):
        if any(p in mail.get("body", "") for p in BURNET_PHRASEN):
            treffer_cluster.add(int(label))
    return len(treffer_cluster) == 1 and -1 not in treffer_cluster, treffer_cluster


def zeige_groesste_cluster(mails, labels):
    cluster_ids = sorted(set(labels.tolist()) - {-1})
    groessen = sorted(cluster_ids, key=lambda c: -int(np.sum(labels == c)))
    for c in groessen[:STICHPROBE_CLUSTER]:
        indizes = [i for i, l in enumerate(labels) if l == c]
        print(f"    Cluster {c} ({len(indizes)} Mails):")
        for i in indizes[:STICHPROBE_BETREFFS]:
            print(f"      - {mails[i].get('subject', '')!r} | {mails[i].get('from', '')}")


def main():
    if not (MAILS_DATEI.exists() and EMBEDDINGS_CACHE.exists() and EMBEDDINGS_IDS_CACHE.exists()):
        print("mails.jsonl oder Embedding-Cache fehlt - erst prepare_emails.py und "
              "cluster_mails.py ausfuehren.")
        sys.exit(1)

    mails, vektoren = lade_daten()
    print(f"{len(mails)} Mails, Embeddings geladen.\n")
    header = (f"{'n_neighbors':>11} | {'min_cluster':>11} | {'method':>6} | "
              f"{'Cluster':>7} | {'Rauschen':>10} | Burnet-Test")

    ergebnisse = {}
    for n_neighbors in N_NEIGHBORS_OPTIONEN:
        reduziert = umap.UMAP(
            n_components=UMAP_N_COMPONENTS,
            metric=UMAP_METRIC,
            n_neighbors=n_neighbors,
            random_state=UMAP_RANDOM_STATE,
        ).fit_transform(vektoren)

        for min_cluster_size in MIN_CLUSTER_SIZE_OPTIONEN:
            for method in SELECTION_METHOD_OPTIONEN:
                labels = HDBSCAN(
                    min_cluster_size=min_cluster_size, cluster_selection_method=method
                ).fit_predict(reduziert)
                ergebnisse[(n_neighbors, min_cluster_size, method)] = labels

    print(header)
    print("-" * len(header))
    for (n_neighbors, min_cluster_size, method), labels in ergebnisse.items():
        anzahl_cluster = len(set(labels.tolist()) - {-1})
        anzahl_rauschen = int(np.sum(labels == -1))
        ok, treffer_cluster = burnet_ok(mails, labels)
        status = "OK" if ok else f"FEHLGESCHLAGEN {sorted(treffer_cluster)}"
        print(
            f"{n_neighbors:>11} | {min_cluster_size:>11} | {method:>6} | {anzahl_cluster:>7} | "
            f"{anzahl_rauschen:>4} ({anzahl_rauschen / len(mails):.0%}) | {status}"
        )

    print("\nGroesste Cluster je Kombination (qualitative Pruefung):")
    for (n_neighbors, min_cluster_size, method), labels in ergebnisse.items():
        print(f"\n  n_neighbors={n_neighbors}, min_cluster_size={min_cluster_size}, method={method}")
        zeige_groesste_cluster(mails, labels)


if __name__ == "__main__":
    main()
