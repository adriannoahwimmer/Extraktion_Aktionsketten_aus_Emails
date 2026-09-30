# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
burnet_bestaetigung.py
--------------------------------------------------
Erzeugt out/burnet_bestaetigung.md zum manuellen Bestaetigen der Burnet-Zuordnung:

  1. Tabelle je Gold-Knoten: Gold-Aktion, vorgeschlagene Entsprechung (Kette,
     Knoten, Aktion, Beleg) oder "keine", leere Spalte "ok?".
  2. Alle Knoten der extrahierten Burnet-Ketten mit Titel und Summary der Kette.
  3. Die Gold-Kanten mit der Angabe, ob zwischen den zugeordneten Knoten eine
     extrahierte Kante in gleicher Richtung existiert.

Liest den Zuordnungsvorschlag aus out/burnet.json und die Ketten aus
out/burnet/ (bzw. backend/chains/, falls die Ketten dort lagen) - vorher
burnet.py ausfuehren.

Aufruf:  python burnet_bestaetigung.py
"""

import json
import sys

import eval_utils as eu

GOLD_DATEI = eu.PROJEKT / "examples" / "gold_burnet.json"
BURNET_OUT = eu.OUT_DIR / "burnet"


def akteur(kette, aid):
    if not aid:
        return ""
    return next((a.get("name", aid) for a in kette.get("actors", []) if a.get("id") == aid), aid)


def knoten_text(n):
    return f"◇ {n.get('label', '')}" if n.get("type") == "gateway" else n.get("action", "")


def belege(n):
    return "<br>".join(f"[{e.get('source')}] „{eu.md_zelle(e.get('span'))}“" for e in n.get("evidence", []) or []) or "–"


def lade_kette(slug, kette_vorhanden_in_chains):
    ordner = eu.CHAINS_DIR if kette_vorhanden_in_chains else BURNET_OUT
    return json.loads((ordner / f"{slug}.json").read_text(encoding="utf-8"))


def main():
    eu.utf8_ausgabe()
    burnet_json = eu.OUT_DIR / "burnet.json"
    if not burnet_json.exists():
        print("out/burnet.json fehlt - erst burnet.py ausfuehren.")
        sys.exit(1)
    b = json.loads(burnet_json.read_text(encoding="utf-8"))
    gold = json.loads(GOLD_DATEI.read_text(encoding="utf-8"))
    ketten = {e["kette"]: lade_kette(e["kette"], b["kette_vorhanden_in_chains"]) for e in b["extrahiert"]}
    zuordnung = b["zuordnung_vorschlag"]      # Gold-Knoten -> {kette, knoten, aehnlichkeit}

    def ext_knoten(g_id):
        z = zuordnung.get(g_id)
        if not z:
            return None, None
        return z["kette"], next(n for n in ketten[z["kette"]]["nodes"] if n["id"] == z["knoten"])

    md = [
        "# Burnet: Bestaetigung der Zuordnung",
        "",
        "Gold-Kette: `examples/gold_burnet.json`. Extrahierte Ketten der Burnet-Cluster "
        f"{', '.join(map(str, b['cluster_ids']))}: {', '.join(ketten)}. Der Vorschlag stammt aus `burnet.py` "
        "(automatisch ueber Textaehnlichkeit) – bitte je Zeile in „ok?“ bestaetigen (z.B. ja/nein) oder korrigieren.",
        "",
        "## Gold-Knoten und vorgeschlagene Entsprechung",
        "",
        "| Gold-Knoten | Gold-Aktion | Kette | Knoten | Aktion | Beleg | ok? |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in gold.get("nodes", []):
        slug, kn = ext_knoten(n["id"])
        g = f"| {n['id']} | {eu.md_zelle(knoten_text(n))} "
        if kn:
            md.append(g + f"| {slug} | {kn['id']} | {eu.md_zelle(knoten_text(kn))} | {belege(kn)} |  |")
        else:
            md.append(g + "| keine | – | – | – |  |")

    md += ["", "## Alle Knoten der extrahierten Ketten", ""]
    for slug, k in ketten.items():
        md += [
            f"### {slug}: {k.get('title', '')}",
            "",
            k.get("summary", ""),
            "",
            "| Knoten | Typ | Aktion / Entscheidungsfrage | Akteur → Empfaenger | Beleg |",
            "|---|---|---|---|---|",
        ]
        for n in k.get("nodes", []):
            typ = f"Gateway ({n.get('gateway_type', '?')})" if n.get("type") == "gateway" else "Aufgabe"
            wer = akteur(k, n.get("actor")) + (f" → {akteur(k, n.get('recipient'))}" if n.get("recipient") else "")
            md.append(f"| {n['id']} | {typ} | {eu.md_zelle(knoten_text(n))} | {eu.md_zelle(wer) or '–'} | {belege(n)} |")
        md.append("")

    md += [
        "## Gold-Kanten",
        "",
        "Existiert zwischen den zugeordneten Knoten eine extrahierte Kante in gleicher Richtung?",
        "",
        "| Gold-Kante | zugeordnete Knoten | extrahierte Kante in gleicher Richtung |",
        "|---|---|---|",
    ]
    for f in gold.get("flows", []):
        a, z = f.get("from"), f.get("to")
        bed = f" [{f['condition']}]" if f.get("condition") else ""
        (sa, ka), (sz, kz) = ext_knoten(a), ext_knoten(z)
        zugeordnet = " → ".join(f"{s}: {k['id']}" if k else "–" for s, k in ((sa, ka), (sz, kz)))
        fehlend = [x for x, k in ((a, ka), (z, kz)) if k is None]
        if fehlend:
            antwort = f"nein – {', '.join(fehlend)} ohne Entsprechung"
        else:
            if sa != sz:
                antwort = "nein – die Knoten liegen in verschiedenen Ketten"
            else:
                flows = ketten[sa].get("flows", [])
                hin = next((x for x in flows if x.get("from") == ka["id"] and x.get("to") == kz["id"]), None)
                rueck = any(x.get("from") == kz["id"] and x.get("to") == ka["id"] for x in flows)
                if hin:
                    antwort = "ja" + (f" [{eu.md_zelle(hin['condition'])}]" if hin.get("condition") else "")
                elif rueck:
                    antwort = "nein – nur in umgekehrter Richtung"
                else:
                    antwort = "nein – keine direkte Kante"
        md.append(f"| {a} → {z}{bed} | {zugeordnet} | {antwort} |")

    (eu.OUT_DIR / "burnet_bestaetigung.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
