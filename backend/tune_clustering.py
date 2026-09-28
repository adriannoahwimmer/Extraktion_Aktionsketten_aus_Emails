"""
tune_clustering.py
--------------------------------------------------
Probiert mehrere UMAP/HDBSCAN-Parameter-Kombinationen auf den bereits
gecachten Embeddings durch (kein neuer API-Call noetig) und vergleicht sie
rein quantitativ: Anzahl Cluster, Rauschen-Quote, Burnet-Akzeptanztest.

Dient nur zum Screening, um ungeeignete Kombinationen auszusortieren, bevor
man sich die vielversprechendsten von Hand anschaut (cluster_mails.py mit
den final gewaehlten Werten erneut ausfuehren).

Ausfuehren (aus backend/, Embedding-Cache muss existieren):
    python tune_clustering.py
"""

from pathlib import Path

import numpy as np

try:
    from sklearn.cluster import HDBSCAN
except ImportError:
    from hdbscan import HDBSCAN

import umap

from mail_utils import lade_mails, dedupliziere, BURNET_PHRASEN

MAILS_DATEI = Path("mails.jsonl")
EMBEDDINGS_CACHE = Path("embeddings.npy")
EMBEDDINGS_IDS_CACHE = Path("embeddings_ids.json")

UMAP_N_COMPONENTS = 5
UMAP_METRIC = "cosine"
UMAP_RANDOM_STATE = 42

# Stellschraube: welche Kombinationen sollen verglichen werden?
N_NEIGHBORS_OPTIONEN = [15]
MIN_CLUSTER_SIZE_OPTIONEN = [2, 3]
# "eom" (Standard) klettert die HDBSCAN-Hierarchie hoch und waehlt oft
# groessere, "stabilere" Cluster - kann kleine, schwache Gruppen mit
# groesseren verschmelzen (siehe Cluster 48 im Testlauf: Sammelbecken aus
# unzusammenhaengenden Themen). "leaf" nimmt die untersten Hierarchie-Ebenen
# und tendiert eher dazu, Unpassendes als Rauschen zu belassen statt es
# hochzumergen.
SELECTION_METHOD_OPTIONEN = ["eom", "leaf"]


def lade_daten():
    import json
    mails = dedupliziere(lade_mails(MAILS_DATEI))
    cache_ids = json.loads(EMBEDDINGS_IDS_CACHE.read_text(encoding="utf-8"))
    cache_vektoren = np.load(EMBEDDINGS_CACHE)
    cache = dict(zip(cache_ids, cache_vektoren))
    vektoren = np.array([cache[m["id"]] for m in mails])
    return mails, vektoren


def burnet_ok(mails, labels):
    treffer_cluster = set()
    for mail, label in zip(mails, labels):
        if any(p in mail.get("body", "") for p in BURNET_PHRASEN):
            treffer_cluster.add(int(label))
    return len(treffer_cluster) == 1 and -1 not in treffer_cluster, treffer_cluster


def main():
    mails, vektoren = lade_daten()
    print(f"{len(mails)} Mails, Embeddings geladen.\n")
    header = f"{'n_neighbors':>11} | {'min_cluster':>11} | {'method':>6} | {'Cluster':>7} | {'Rauschen':>10} | Burnet-Test"
    print(header)
    print("-" * len(header))

    ergebnisse = {}
    for n_neighbors in N_NEIGHBORS_OPTIONEN:
        reducer = umap.UMAP(
            n_components=UMAP_N_COMPONENTS,
            metric=UMAP_METRIC,
            n_neighbors=n_neighbors,
            random_state=UMAP_RANDOM_STATE,
        )
        reduziert = reducer.fit_transform(vektoren)

        for min_cluster_size in MIN_CLUSTER_SIZE_OPTIONEN:
            for method in SELECTION_METHOD_OPTIONEN:
                modell = HDBSCAN(min_cluster_size=min_cluster_size, cluster_selection_method=method)
                labels = modell.fit_predict(reduziert)

                anzahl_cluster = len(set(labels.tolist()) - {-1})
                anzahl_rauschen = int(np.sum(labels == -1))
                rauschen_quote = anzahl_rauschen / len(mails)

                ok, treffer_cluster = burnet_ok(mails, labels)
                status = "OK" if ok else f"FEHLGESCHLAGEN {treffer_cluster}"

                print(
                    f"{n_neighbors:>11} | {min_cluster_size:>11} | {method:>6} | {anzahl_cluster:>7} | "
                    f"{anzahl_rauschen:>4} ({rauschen_quote:.0%}) | {status}"
                )
                ergebnisse[(n_neighbors, min_cluster_size, method)] = labels

    return mails, ergebnisse


def zeige_groesste_cluster(mails, labels, n=6, beispiele=4):
    cluster_ids = sorted(set(labels.tolist()) - {-1})
    groessen = sorted(cluster_ids, key=lambda c: -int(np.sum(labels == c)))
    for c in groessen[:n]:
        indizes = [i for i, l in enumerate(labels) if l == c]
        print(f"  Cluster {c} ({len(indizes)} Mails):")
        for i in indizes[:beispiele]:
            print(f"    - {mails[i].get('subject', '')!r} | {mails[i].get('from', '')}")


if __name__ == "__main__":
    mails, ergebnisse = main()

    print("\n--- Stichprobe: groesste Cluster bei min_cluster_size=3, method=leaf ---")
    zeige_groesste_cluster(mails, ergebnisse[(15, 3, "leaf")])

    print("\n--- Stichprobe: groesste Cluster bei min_cluster_size=3, method=eom (zum Vergleich) ---")
    zeige_groesste_cluster(mails, ergebnisse[(15, 3, "eom")])

    print("\n--- Volle Liste: groesster leaf-Cluster (Cluster 53, 19 Mails) ---")
    labels_leaf = ergebnisse[(15, 3, "leaf")]
    for i, l in enumerate(labels_leaf):
        if l == 53:
            print(f"    - {mails[i].get('subject', '')!r} | {mails[i].get('from', '')} -> {mails[i].get('to', '')}")
