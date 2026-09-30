# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
kennzahlen.py
--------------------------------------------------
Schritt 1 der Auswertung: Kennzahlen der Enron-Ketten (chains/chain_cluster_*.json)
und des Clusterings (clusters.jsonl), verglichen mit den Werten aus dem
Berichtsentwurf (REFERENZ). Jede Abweichung wird gemeldet.

Aufruf:  python kennzahlen.py
Ausgabe: out/kennzahlen.md, out/kennzahlen.json
"""

import json
import statistics as st
from collections import Counter

import eval_utils as eu

# Werte aus dem Berichtsentwurf, gegen die geprueft wird.
REFERENZ = {
    "ketten": 51,
    "cluster_mit_ketten": 36,
    "cluster_mit_mehreren_ketten": 13,
    "p_median": 0.65, "p_min": 0.4, "p_max": 0.9,
    "knoten_median": 5, "knoten_min": 2, "knoten_max": 12,
    "ketten_mit_gateway": 9,
    "aufgabenknoten": 252,
    "clusteranzahl": 2710,
    "rauschen": 2656,
    "clustergroesse_median": 3, "clustergroesse_max": 29,
    "cluster_mit_2_mails": 1283,
}

BESCHRIFTUNG = {
    "ketten": "Anzahl Ketten",
    "cluster_mit_ketten": "Cluster mit Ketten",
    "cluster_mit_mehreren_ketten": "Cluster mit > 1 Kette",
    "p_median": "prozess_wahrscheinlichkeit Median",
    "p_min": "prozess_wahrscheinlichkeit Min",
    "p_max": "prozess_wahrscheinlichkeit Max",
    "knoten_median": "Knoten je Kette Median",
    "knoten_min": "Knoten je Kette Min",
    "knoten_max": "Knoten je Kette Max",
    "ketten_mit_gateway": "Ketten mit Gateway",
    "aufgabenknoten": "Aufgabenknoten gesamt",
    "aufgabenknoten_mit_evidence": "davon mit evidence",
    "clusteranzahl": "Clusteranzahl",
    "rauschen": "Rauschen (Mails mit Label -1)",
    "clustergroesse_median": "Clustergroesse Median",
    "clustergroesse_max": "Clustergroesse Max",
    "cluster_mit_2_mails": "Cluster mit genau 2 Mails",
}


def kennzahlen_ketten(ketten):
    p = [k["data"].get("prozess_wahrscheinlichkeit") for k in ketten]
    p = [x for x in p if isinstance(x, (int, float))]
    knoten = [len(k["data"].get("nodes", [])) for k in ketten]
    tasks = [n for k in ketten for n in eu.aufgabenknoten(k["data"])]
    je_cluster = Counter(k["cid"] for k in ketten)
    return {
        "ketten": len(ketten),
        "cluster_mit_ketten": len(je_cluster),
        "davon_einzelmail_gruppen": sum(1 for c in je_cluster if c.startswith("e")),
        "cluster_mit_mehreren_ketten": sum(1 for n in je_cluster.values() if n > 1),
        "p_median": st.median(p), "p_min": min(p), "p_max": max(p),
        "ketten_ohne_p": len(ketten) - len(p),
        "knoten_median": st.median(knoten), "knoten_min": min(knoten), "knoten_max": max(knoten),
        "ketten_mit_gateway": sum(1 for k in ketten
                                  if any(n.get("type") == "gateway" for n in k["data"].get("nodes", []))),
        "gateways_gesamt": sum(1 for k in ketten for n in k["data"].get("nodes", []) if n.get("type") == "gateway"),
        "aufgabenknoten": len(tasks),
        "aufgabenknoten_mit_evidence": sum(1 for n in tasks if n.get("evidence")),
        "aufgabenknoten_je_kette_min": min(len(eu.aufgabenknoten(k["data"])) for k in ketten),
        "kanten_gesamt": sum(len(k["data"].get("flows", [])) for k in ketten),
        "ketten_je_cluster_max": max(je_cluster.values()),
    }


def kennzahlen_clustering(zuordnung):
    labels = Counter(zuordnung.values())
    groessen = sorted((n for c, n in labels.items() if c != -1), reverse=True)
    return {
        "mails_dedupliziert": len(zuordnung),
        "clusteranzahl": len(groessen),
        "rauschen": labels.get(-1, 0),
        "clustergroesse_median": st.median(groessen),
        "clustergroesse_max": max(groessen),
        "cluster_mit_2_mails": sum(1 for g in groessen if g == 2),
    }, groessen


def abdeckung_extraktion(ketten, groessen, zuordnung):
    """Wie viele Cluster wurden an das LLM geschickt (verarbeitet.json, --alle-Lauf)?"""
    if not eu.VERARBEITET_DATEI.exists():
        return {}
    verarbeitet = set(json.loads(eu.VERARBEITET_DATEI.read_text(encoding="utf-8")))
    groesse = Counter(v for v in zuordnung.values() if v != -1)
    gr_verarbeitet = [groesse[int(c)] for c in verarbeitet if not c.startswith("e") and c.lstrip("-").isdigit()]
    mit_kette = {k["cid"] for k in ketten}
    return {
        "gruppen_verarbeitet": len(verarbeitet),
        "davon_einzelmails": sum(1 for c in verarbeitet if c.startswith("e")),
        "kleinster_verarbeiteter_cluster": min(gr_verarbeitet) if gr_verarbeitet else None,
        "cluster_mit_mind_dieser_groesse": sum(1 for g in groessen if gr_verarbeitet and g >= min(gr_verarbeitet)),
        "verarbeitete_cluster_mit_kette": len(mit_kette & verarbeitet),
        "ketten_aus_nicht_verarbeiteten_clustern": sorted(mit_kette - verarbeitet),
    }


def fmt(x):
    if isinstance(x, float):
        return f"{x:g}"
    return str(x)


def main():
    eu.utf8_ausgabe()
    ketten = eu.lade_enron_ketten()
    zuordnung = eu.lade_cluster_zuordnung()
    k_ketten = kennzahlen_ketten(ketten)
    k_cluster, groessen = kennzahlen_clustering(zuordnung)
    abdeckung = abdeckung_extraktion(ketten, groessen, zuordnung)
    werte = {**k_ketten, **k_cluster}

    zeilen, abweichungen = [], []
    for schluessel, text in BESCHRIFTUNG.items():
        ist = werte.get(schluessel)
        soll = REFERENZ.get(schluessel)
        if soll is None:
            status = "–"
        elif ist == soll:
            status = "✓"
        else:
            status = "**Abweichung**"
            abweichungen.append(f"{text}: Bericht {fmt(soll)}, berechnet {fmt(ist)}")
        zeilen.append(f"| {text} | {fmt(ist)} | {fmt(soll) if soll is not None else '–'} | {status} |")

    md = [
        "# Kennzahlen der Enron-Ketten und des Clusterings",
        "",
        f"Quelle: `backend/chains/chain_cluster_*.json` ({len(ketten)} Dateien, ohne Upload-Batches) "
        f"und `backend/clusters.jsonl` ({k_cluster['mails_dedupliziert']} deduplizierte Mails).",
        "",
        "| Kennzahl | berechnet | Bericht | Status |",
        "|---|---|---|---|",
        *zeilen,
        "",
        "**Abweichungen:** " + ("keine." if not abweichungen else ""),
        *[f"- {a}" for a in abweichungen],
        "",
        "## Weitere Werte",
        "",
        f"- Gateways gesamt: {k_ketten['gateways_gesamt']}; Kanten gesamt: {k_ketten['kanten_gesamt']}",
        f"- Aufgabenknoten je Kette mindestens: {k_ketten['aufgabenknoten_je_kette_min']}; "
        f"maximal {k_ketten['ketten_je_cluster_max']} Ketten aus einem Cluster",
        f"- Einzelmail-Gruppen unter den Clustern mit Ketten: {k_ketten['davon_einzelmail_gruppen']}",
    ]
    if abdeckung:
        md += [
            f"- Als verarbeitet markiert (`verarbeitet.json`, Lauf mit `--alle`): {abdeckung['gruppen_verarbeitet']} Gruppen, "
            f"davon {abdeckung['davon_einzelmails']} Einzelmails. Deckel `MAX_CLUSTER` = 300, Auswahl nach absteigender "
            f"Groesse: kleinster ausgewaehlter Cluster {abdeckung['kleinster_verarbeiteter_cluster']} Mails "
            f"({abdeckung['cluster_mit_mind_dieser_groesse']} Cluster haben mindestens diese Groesse).",
            f"- Davon mit mindestens einer Kette: {abdeckung['verarbeitete_cluster_mit_kette']} von "
            f"{abdeckung['gruppen_verarbeitet']}. Achtung: `verarbeitet.json` markiert auch fehlgeschlagene Aufrufe; "
            "laut `LAUFPRUEFUNG.md` bekamen nur die ersten rund 54 Gruppen eine LLM-Antwort, der Rest wurde "
            "sehr wahrscheinlich mit Fehler uebersprungen. Eine Quote „Ketten je verarbeiteter Gruppe“ ist daher "
            "nur auf die beantworteten Gruppen bezogen sinnvoll.",
            f"- Ketten aus nicht verarbeiteten Clustern (Altbestand?): {abdeckung['ketten_aus_nicht_verarbeiteten_clustern'] or 'keine'}",
        ]

    eu.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (eu.OUT_DIR / "kennzahlen.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (eu.OUT_DIR / "kennzahlen.json").write_text(
        json.dumps({"ketten": k_ketten, "clustering": k_cluster, "abdeckung": abdeckung,
                    "referenz": REFERENZ, "abweichungen": abweichungen}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n".join(md))


if __name__ == "__main__":
    main()
