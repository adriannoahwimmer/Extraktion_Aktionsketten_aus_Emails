# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
burnet.py
--------------------------------------------------
Schritt 4 der Auswertung: Vergleich mit der manuell annotierten Referenzkette
(examples/gold_burnet.json).

  1. Findet die Burnet-Mails ueber mail_utils.BURNET_PHRASEN und ihre Cluster in
     clusters.jsonl; ordnet zusaetzlich die Quellen der Gold-Kette Mails zu.
  2. Prueft, ob es zu diesen Clustern Ketten in backend/chains/ gibt.
  3. Falls nicht: extrahiert genau diese Cluster ueber extract_chains.NUR_CLUSTER.
     Die Ausgabe landet in out/burnet/ (backend/chains/ bleibt unveraendert).
     Ein erneuter Aufruf verwendet vorhandene Ergebnisse; --neu extrahiert neu.
  4. Schreibt out/burnet_vergleich.md: Gold-Kette und extrahierte Kette(n)
     nebeneinander und eine VORGESCHLAGENE Zuordnung der Knoten und Kanten
     (automatisch ueber Textaehnlichkeit von Belegen, Aktionen und Akteuren),
     die manuell zu bestaetigen ist; die Befunde zusaetzlich als out/burnet.json.

Aufruf:  python burnet.py [--neu]
"""

import argparse
import contextlib
import difflib
import json
import re
import sys
from datetime import datetime

import eval_utils as eu
from mail_utils import BURNET_PHRASEN

GOLD_DATEI = eu.PROJEKT / "examples" / "gold_burnet.json"
BURNET_OUT = eu.OUT_DIR / "burnet"
SCHWELLE = 0.30          # Mindestaehnlichkeit fuer einen Zuordnungsvorschlag

STOPPWOERTER = {"der", "die", "das", "den", "dem", "des", "und", "oder", "fuer", "von", "an", "zu", "zur",
                "zum", "mit", "auf", "ein", "eine", "einen", "einer", "im", "in", "ist", "wird", "werden",
                "sich", "bei", "nach", "vor", "ueber", "aus", "als", "the", "a", "an", "to", "of", "and"}


# ------------------------------------------------------------------
# 1.-3. Burnet-Mails finden, Ketten suchen, ggf. extrahieren
# ------------------------------------------------------------------
def finde_burnet(index):
    treffer = []
    for mid, m in index.mails.items():
        roh = [p for p in BURNET_PHRASEN if p in m.get("body", "")]
        normalisiert = [p for p in BURNET_PHRASEN if p in index.body_ws(mid)]
        if roh or normalisiert:
            treffer.append({"mail_id": mid, "cluster": index.zuordnung.get(mid), "phrasen_roh": roh,
                            "phrasen_ws": normalisiert, "mail": m})
    return treffer


class _Tee:
    def __init__(self, *ziele):
        self.ziele = ziele

    def write(self, text):
        for z in self.ziele:
            z.write(text)

    def flush(self):
        for z in self.ziele:
            z.flush()


def extrahiere(cluster_ids):
    """Extraktion ueber extract_chains.py mit NUR_CLUSTER, Ausgabe nach out/burnet/."""
    import extract_chains as ec

    BURNET_OUT.mkdir(parents=True, exist_ok=True)
    ec.MAILS_DATEI = eu.MAILS_DATEI
    ec.CLUSTERS_DATEI = eu.CLUSTERS_DATEI
    ec.AUSGABE_ORDNER = BURNET_OUT
    ec.NUR_CLUSTER = set(cluster_ids)
    argv = sys.argv
    sys.argv = ["extract_chains.py"]
    try:
        with open(BURNET_OUT / "extraktion.log", "w", encoding="utf-8") as log, \
                contextlib.redirect_stdout(_Tee(sys.stdout, log)):
            print(f"Modell: {ec.MODEL}; NUR_CLUSTER = {sorted(cluster_ids)}")
            ec.main()
    finally:
        sys.argv = argv


def lade_ketten(ordner, cluster_ids):
    ketten = []
    for cid in cluster_ids:
        for datei in sorted(ordner.glob(f"chain_cluster_{cid}_*.json")):
            ketten.append({"slug": datei.stem, "cid": str(cid), "data": json.loads(datei.read_text(encoding="utf-8"))})
    return ketten


# ------------------------------------------------------------------
# 4. Vergleich und Zuordnungsvorschlag
# ------------------------------------------------------------------
def woerter(text):
    return {w for w in re.findall(r"\w+", eu.ws(text).casefold()) if len(w) > 2 and w not in STOPPWOERTER}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def text_aehnlichkeit(a, b):
    a_n, b_n = eu.ws(a).casefold(), eu.ws(b).casefold()
    if not a_n or not b_n:
        return 0.0
    return max(jaccard(woerter(a), woerter(b)), difflib.SequenceMatcher(None, a_n, b_n).ratio() * 0.8)


def beleg_aehnlichkeit(knoten_a, knoten_b):
    spans_a = [eu.ws(e.get("span")).casefold() for e in knoten_a.get("evidence", []) or []]
    spans_b = [eu.ws(e.get("span")).casefold() for e in knoten_b.get("evidence", []) or []]
    beste = 0.0
    for a in spans_a:
        for b in spans_b:
            if a and b and (a in b or b in a):
                return 1.0
            beste = max(beste, jaccard(woerter(a), woerter(b)))
    return beste


def akteur_name(kette, aid):
    return next((a.get("name", "") for a in kette.get("actors", []) if a.get("id") == aid), aid or "")


def akteur_aehnlichkeit(gold, kg, ext, ke):
    def gleich(x, y):
        tx, ty = woerter(x), woerter(y)
        return bool(tx & ty)
    punkte = []
    for feld in ("actor", "recipient"):
        if kg.get(feld):
            punkte.append(1.0 if ke.get(feld) and gleich(akteur_name(gold, kg[feld]), akteur_name(ext, ke[feld])) else 0.0)
    return sum(punkte) / len(punkte) if punkte else 0.0


def aehnlichkeit(gold, kg, ext, ke):
    if kg.get("type") != ke.get("type"):
        return 0.0, ""
    if kg.get("type") == "gateway":
        s = text_aehnlichkeit(kg.get("label"), ke.get("label"))
        return s, f"Label {s:.2f}"
    b = beleg_aehnlichkeit(kg, ke)
    t = text_aehnlichkeit(kg.get("action"), ke.get("action"))
    a = akteur_aehnlichkeit(gold, kg, ext, ke)
    if kg.get("evidence"):
        return 0.5 * b + 0.35 * t + 0.15 * a, f"Beleg {b:.2f}, Aktion {t:.2f}, Akteure {a:.2f}"
    return 0.8 * t + 0.2 * a, f"Aktion {t:.2f}, Akteure {a:.2f} (Gold ohne Beleg)"


def zuordnung_vorschlagen(gold, ext_ketten):
    """Gierige 1:1-Zuordnung Gold-Knoten -> Knoten der extrahierten Ketten nach Aehnlichkeit."""
    paare = []
    for kg in gold.get("nodes", []):
        for ek in ext_ketten:
            for ke in ek["data"].get("nodes", []):
                s, grund = aehnlichkeit(gold, kg, ek["data"], ke)
                paare.append((s, kg["id"], (ek["slug"], ke["id"]), grund))
    paare.sort(key=lambda p: -p[0])
    zuordnung, vergeben = {}, set()
    for s, g, e, grund in paare:
        if s < SCHWELLE or g in zuordnung or e in vergeben:
            continue
        zuordnung[g] = (e, s, grund)
        vergeben.add(e)
    # Zweitbeste Kandidatin je Gold-Knoten (oberhalb der Schwelle), als Hinweis fuer die Bestaetigung
    alternativen = {}
    for s, g, e, _ in paare:
        if s >= SCHWELLE and g not in alternativen and (g not in zuordnung or zuordnung[g][0] != e):
            alternativen[g] = (e, s)
    return zuordnung, alternativen


def erreichbar(flows, start, ziel):
    """Kuerzester Pfad (Anzahl Kanten) von start nach ziel, sonst None."""
    nachbarn = {}
    for f in flows:
        nachbarn.setdefault(f.get("from"), []).append(f.get("to"))
    front, gesehen, tiefe = [start], {start}, 0
    while front:
        tiefe += 1
        neu = []
        for k in front:
            for n in nachbarn.get(k, []):
                if n == ziel:
                    return tiefe
                if n not in gesehen:
                    gesehen.add(n)
                    neu.append(n)
        front = neu
    return None


def knoten_text(kette, n):
    if n.get("type") == "gateway":
        return f"◇ {n.get('label', '?')}"
    akt = akteur_name(kette, n.get("actor"))
    emp = akteur_name(kette, n.get("recipient")) if n.get("recipient") else ""
    return f"{n.get('action', '')} ({akt}{' → ' + emp if emp else ''})"


def kette_als_zelle(kette, slug=None):
    zeilen = []
    if slug:
        zeilen.append(f"**{slug}**")
    zeilen.append(f"**{eu.md_zelle(kette.get('title'))}**")
    zeilen.append(eu.md_zelle(kette.get("summary")))
    zeilen.append("*Akteure:* " + ", ".join(eu.md_zelle(a.get("name")) for a in kette.get("actors", [])))
    zeilen.append("*Knoten:*")
    for n in kette.get("nodes", []):
        zeilen.append(f"{n['id']}: {eu.md_zelle(knoten_text(kette, n))}")
    zeilen.append("*Kanten:*")
    for f in kette.get("flows", []):
        bed = f" [{eu.md_zelle(f['condition'])}]" if f.get("condition") else ""
        zeilen.append(f"{f.get('from')} → {f.get('to')}{bed}")
    return "<br>".join(zeilen)


def main():
    eu.utf8_ausgabe()
    parser = argparse.ArgumentParser(description="Burnet-Vergleich (siehe Modul-Docstring).")
    parser.add_argument("--neu", action="store_true", help="Burnet-Cluster erneut extrahieren")
    args = parser.parse_args()

    index = eu.MailIndex(eu.lade_mails_dedup(), eu.lade_cluster_zuordnung())
    gold = json.loads(GOLD_DATEI.read_text(encoding="utf-8"))
    treffer = finde_burnet(index)
    cluster_ids = sorted({t["cluster"] for t in treffer if t["cluster"] not in (None, -1)})
    im_rauschen = [t["mail_id"] for t in treffer if t["cluster"] == -1]

    vorhandene = lade_ketten(eu.CHAINS_DIR, cluster_ids)
    if vorhandene:
        ext_ketten, herkunft = vorhandene, "backend/chains/ (vorhandene Enron-Ketten)"
    else:
        ext_ketten = [] if args.neu else lade_ketten(BURNET_OUT, cluster_ids)
        if not ext_ketten and not (BURNET_OUT / "extraktion.log").exists() or args.neu:
            print(f"Keine Ketten zu den Burnet-Clustern {cluster_ids} - extrahiere ueber NUR_CLUSTER ...")
            extrahiere(cluster_ids)
            ext_ketten = lade_ketten(BURNET_OUT, cluster_ids)
        herkunft = "eval/out/burnet/ (per NUR_CLUSTER nachtraeglich extrahiert)"

    # Gold-Quellen im Korpus verorten
    gold_quellen = []
    for q in gold.get("sources", []):
        z = eu.ordne_quelle_zu(q, "", index)
        gold_quellen.append((q, z, [index.zuordnung.get(m) for m in z["mail_ids"]]))

    zuordnung, alternativen = zuordnung_vorschlagen(gold, ext_ketten)
    ext_nach_slug = {k["slug"]: k["data"] for k in ext_ketten}

    md = [
        "# Burnet: Gold-Kette vs. extrahierte Kette",
        "",
        "## 1. Lage der Burnet-Mails im Clustering",
        "",
        "Suche ueber `BURNET_PHRASEN` (`mail_utils.py`) in den deduplizierten Mails. Die Pipeline sucht ohne "
        "Whitespace-Normalisierung (Spalte *roh*); mit Normalisierung werden Zeilenumbrueche im Satz toleriert.",
        "",
        "| Mail | Datum | Betreff | Cluster | Phrasen (roh) | Phrasen (normalisiert) |",
        "|---|---|---|---|---|---|",
        *[f"| {t['mail_id']} | {eu.md_zelle(t['mail'].get('date'))} | {eu.md_zelle(t['mail'].get('subject'))} | "
          f"{t['cluster']} | {', '.join(t['phrasen_roh']) or '–'} | {', '.join(t['phrasen_ws']) or '–'} |" for t in treffer],
        "",
        f"Burnet-Cluster: {', '.join(map(str, cluster_ids)) or 'keine'}"
        + (f"; als Rauschen markiert: {', '.join(im_rauschen)}" if im_rauschen else "")
        + (". **Die Burnet-Mails liegen in verschiedenen Clustern** (Akzeptanztest nicht bestanden)."
           if len(cluster_ids) > 1 else "."),
        "",
        "Quellen der Gold-Kette im Korpus:",
        "",
        "| Gold-Quelle | Betreff | Datum | → Mail | Cluster |",
        "|---|---|---|---|---|",
        *[f"| {q['id']} | {eu.md_zelle(q.get('subject'))} | {q.get('date')} | {', '.join(z['mail_ids']) or 'nicht gefunden'} | "
          f"{', '.join(map(str, cl)) or '–'} |" for q, z, cl in gold_quellen],
        "",
        "Inhalt der Burnet-Cluster:",
        "",
    ]
    for cid in cluster_ids:
        md.append(f"- Cluster {cid}: " + "; ".join(
            f"{mid} ({eu.md_zelle(index.mails[mid].get('from'), 30)}, {eu.md_zelle(index.mails[mid].get('subject'), 50)})"
            for mid in index.cluster_mail_ids(str(cid))))
    md += [
        "",
        f"Ketten zu den Burnet-Clustern: {len(ext_ketten)} aus {herkunft}.",
        "",
        "## 2. Gegenueberstellung",
        "",
    ]
    if ext_ketten:
        md += ["| Gold (examples/gold_burnet.json) | Extrahiert |", "|---|---|"]
        for i, k in enumerate(ext_ketten):
            md.append(f"| {kette_als_zelle(gold) if i == 0 else '(siehe oben)'} | {kette_als_zelle(k['data'], k['slug'])} |")
    else:
        md.append("Die Extraktion lieferte fuer die Burnet-Cluster **keine Kette** (siehe out/burnet/extraktion.log). "
                  "Gold-Kette zum Vergleich:")
        md += ["", "| Gold (examples/gold_burnet.json) |", "|---|", f"| {kette_als_zelle(gold)} |"]

    md += [
        "",
        "## 3. VORGESCHLAGENE Zuordnung (bitte bestaetigen)",
        "",
        f"Automatischer Vorschlag ueber Textaehnlichkeit (Belegzitat 50 %, Aktion 35 %, Akteure 15 %; "
        f"Gateways ueber das Label), gierig 1:1, Mindestaehnlichkeit {SCHWELLE}. Kein Urteil - bitte je Zeile "
        "bestaetigen oder korrigieren. Vorschlaege unter 0.5 sind unsicher. Kantenbedingungen der extrahierten "
        "Ketten (Abschnitt 2, in eckigen Klammern) koennen Inhalte von Gold-Knoten enthalten.",
        "",
        "### Knoten",
        "",
        "| Gold-Knoten | Vorschlag (Kette: Knoten) | Aehnlichkeit | Grundlage | Alternative | bestaetigt? |",
        "|---|---|---|---|---|---|",
    ]

    def ext_text(e):
        slug, eid = e
        ke = next(x for x in ext_nach_slug[slug]["nodes"] if x["id"] == eid)
        return f"{slug}: {eid}: {eu.md_zelle(knoten_text(ext_nach_slug[slug], ke))}"

    for n in gold.get("nodes", []):
        g_txt = f"{n['id']}: {eu.md_zelle(knoten_text(gold, n))}"
        alt = f"{ext_text(alternativen[n['id']][0])} ({alternativen[n['id']][1]:.2f})" if n["id"] in alternativen else "–"
        if n["id"] in zuordnung:
            e, s, grund = zuordnung[n["id"]]
            unsicher = " (unsicher)" if s < 0.5 else ""
            md.append(f"| {g_txt} | {ext_text(e)} | {s:.2f}{unsicher} | {grund} | {alt} | [ ] |")
        else:
            md.append(f"| {g_txt} | – keine Entsprechung gefunden | – | – | {alt} | [ ] |")

    zugeordnet = {e for (e, _, _) in zuordnung.values()}
    uebrig = [(k["slug"], n) for k in ext_ketten for n in k["data"].get("nodes", []) if (k["slug"], n["id"]) not in zugeordnet]
    md += ["", "Extrahierte Knoten ohne Gold-Entsprechung: "
           + ("; ".join(f"{s}: {n['id']} ({eu.md_zelle(knoten_text(ext_nach_slug[s], n), 70)})" for s, n in uebrig) or "keine"),
           "", "### Kanten", "",
           "| Gold-Kante | Entsprechung in der extrahierten Kette | bestaetigt? |", "|---|---|---|"]
    abgedeckt, kanten_status = set(), []
    for f in gold.get("flows", []):
        a, b = f.get("from"), f.get("to")
        bed = f" [{f['condition']}]" if f.get("condition") else ""
        if a in zuordnung and b in zuordnung:
            (sa, ea), (sb, eb) = zuordnung[a][0], zuordnung[b][0]
            if sa != sb:
                status = f"Knoten liegen in verschiedenen Ketten ({sa}: {ea}, {sb}: {eb}) – fehlt"
            else:
                flows = ext_nach_slug[sa].get("flows", [])
                tiefe = erreichbar(flows, ea, eb)
                if tiefe == 1:
                    status = f"direkt: {sa}: {ea} → {eb}"
                    abgedeckt.add((sa, ea, eb))
                elif tiefe:
                    status = f"indirekt ueber {tiefe - 1} Zwischenknoten: {sa}: {ea} → … → {eb}"
                else:
                    status = f"fehlt ({sa}: kein Pfad {ea} → {eb})"
        else:
            status = "fehlt (mindestens ein Knoten ohne Entsprechung)"
        md.append(f"| {a} → {b}{bed} | {status} | [ ] |")
        kanten_status.append({"kante": f"{a} → {b}", "status": status})
    zusaetzlich = [f"{k['slug']}: {f.get('from')} → {f.get('to')}" for k in ext_ketten for f in k["data"].get("flows", [])
                   if (k["slug"], f.get("from"), f.get("to")) not in abgedeckt]
    md += ["", "Extrahierte Kanten ohne direkte Gold-Entsprechung: " + ("; ".join(zusaetzlich) or "keine"), ""]

    def umfang(kette):
        nodes = kette.get("nodes", [])
        return {"knoten": len(nodes), "aufgaben": sum(1 for n in nodes if n.get("type") == "task"),
                "gateways": sum(1 for n in nodes if n.get("type") == "gateway"), "kanten": len(kette.get("flows", []))}

    log = BURNET_OUT / "extraktion.log"
    modell_log = next((z.split(";")[0].replace("Modell:", "").strip()
                       for z in log.read_text(encoding="utf-8").splitlines() if z.startswith("Modell:")), None) if log.exists() else None
    fakten = {
        "burnet_mails": [{"mail_id": t["mail_id"], "cluster": t["cluster"], "betreff": t["mail"].get("subject"),
                          "phrasen_roh": t["phrasen_roh"], "phrasen_ws": t["phrasen_ws"]} for t in treffer],
        "cluster_ids": cluster_ids,
        "im_rauschen": im_rauschen,
        "cluster_groessen": {str(c): len(index.cluster_mail_ids(str(c))) for c in cluster_ids},
        "gold_quellen": [{"id": q["id"], "betreff": q.get("subject"), "mail_ids": z["mail_ids"], "cluster": cl}
                         for q, z, cl in gold_quellen],
        "kette_vorhanden_in_chains": bool(vorhandene),
        "quelle_der_ketten": herkunft,
        "extraktion": None if vorhandene else {
            "modell": modell_log,
            "zeit": datetime.fromtimestamp(log.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if log.exists() else None,
        },
        "gold": umfang(gold),
        "extrahiert": [{"kette": k["slug"], "cluster": k["cid"], "p": k["data"].get("prozess_wahrscheinlichkeit"),
                        **umfang(k["data"])} for k in ext_ketten],
        "zuordnung_vorschlag": {g: {"kette": e[0], "knoten": e[1], "aehnlichkeit": round(s, 2)}
                                for g, (e, s, _) in zuordnung.items()},
        "gold_kanten": kanten_status,
    }

    eu.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (eu.OUT_DIR / "burnet_vergleich.md").write_text("\n".join(md), encoding="utf-8")
    (eu.OUT_DIR / "burnet.json").write_text(json.dumps(fakten, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
