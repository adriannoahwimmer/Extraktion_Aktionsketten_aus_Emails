# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
laufpruefung.py
--------------------------------------------------
Laufpruefung des Enron-Extraktionslaufs (extract_chains.py --alle, 11.09.2026):

  1. Wie begrenzt prepare_emails.py die CSV-Zeilen? Zeilenzahlen von mails.jsonl
     und clusters.jsonl.
  2. verarbeitet.json gegen die 300 groessten Gruppen (Auswahl mit denselben
     Funktionen aus extract_chains.py nachgerechnet, ohne LLM-Aufruf).
  3. Suche nach erhaltener Laufausgabe in den Claude-Code-Protokollen und den
     Upload-Logs vom 11.09. (Fehler, leere Antworten, Retries, Kontingent/402/429).
     Treffer in Quelltext-Ansichten und Code-Aenderungen werden ausgefiltert.
  4. Rekonstruktion des Ablaufs aus der Verarbeitungsreihenfolge und den
     Zeitstempeln der Ketten-Dateien: Wie lange brauchte eine Gruppe, und ab wann
     wurden Gruppen so schnell "verarbeitet", dass keine echte LLM-Antwort
     vorliegen kann? (verarbeitet.json markiert auch fehlgeschlagene Gruppen.)

Aufruf:  python laufpruefung.py [--claude-protokolle <ordner>]
Ausgabe: out/LAUFPRUEFUNG.md
"""

import argparse
import contextlib
import io
import json
import re
import statistics as st
from datetime import datetime
from pathlib import Path

import eval_utils as eu

LAUFTAG = "2026-09-11"
# Zeilen, die nur in der Ausgabe von extract_chains.py vorkommen
RE_GRUPPE = re.compile(r"^=+ Cluster (\S+) \((\d+) Mails")
SUCHBEGRIFFE = ["FEHLER bei diesem Cluster", "LEERE Antwort", "transienter Fehler", "quota", "budget", "credit",
                "402", "429"]
NICHT_LAUFAUSGABE = ("Read", "Edit", "Write", "MultiEdit", "Grep", "Glob")   # Tools mit Quelltext statt Ausgabe


def lokal(ts: float) -> datetime:
    return datetime.fromtimestamp(ts)


# ------------------------------------------------------------------
# 1. prepare_emails.py und Zeilenzahlen
# ------------------------------------------------------------------
def pruefe_vorverarbeitung():
    import prepare_emails as pe
    zeilen_mails, hoechste = 0, -1
    with open(eu.MAILS_DATEI, encoding="utf-8") as f:
        for z in f:
            if z.strip():
                zeilen_mails += 1
                hoechste = max(hoechste, int(json.loads(z)["id"].split("_")[1]))
    zeilen_cluster = sum(1 for z in open(eu.CLUSTERS_DATEI, encoding="utf-8") if z.strip())
    return {"max_mails": pe.MAX_MAILS, "min_body_len": pe.MIN_BODY_LEN, "mails_jsonl": zeilen_mails,
            "hoechste_id": hoechste, "clusters_jsonl": zeilen_cluster,
            "mails_zeit": lokal(eu.MAILS_DATEI.stat().st_mtime), "clusters_zeit": lokal(eu.CLUSTERS_DATEI.stat().st_mtime)}


# ------------------------------------------------------------------
# 2. Auswahl der 300 groessten Gruppen nachrechnen
# ------------------------------------------------------------------
def rechne_auswahl_nach():
    import extract_chains as ec
    ec.MAILS_DATEI, ec.CLUSTERS_DATEI = eu.MAILS_DATEI, eu.CLUSTERS_DATEI
    ec.ALLE_VERARBEITEN = True
    mails = eu.lade_mails_dedup()
    zuordnung, scores = ec.lade_cluster_zuordnung(eu.CLUSTERS_DATEI)
    gruppen = ec.gruppiere_nach_cluster(mails, zuordnung)
    with contextlib.redirect_stdout(io.StringIO()):
        gruppen = ec.ergaenze_einzelmails(gruppen, mails, zuordnung)
        auswahl, _ = ec.waehle_cluster(gruppen, scores, ec.TOP_N_CLUSTERS, ec.CHAIN_SCORE_MIN)
    return gruppen, auswahl, ec.MAX_CLUSTER


# ------------------------------------------------------------------
# 3. Erhaltene Laufausgabe suchen
# ------------------------------------------------------------------
def protokoll_texte(ordner: Path):
    """(Zeit, Quelle, Text) aller Nutzertexte und Kommandozeilen-Ausgaben vom Lauftag
    (Ortszeit). Ausgaben von Datei-Tools (Quelltext mit Zeilennummern) werden uebersprungen."""
    for datei in sorted(ordner.glob("*.jsonl")):
        tool_namen = {}
        for zeile in open(datei, encoding="utf-8"):
            try:
                e = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            ts = e.get("timestamp")
            if not ts:
                continue
            zeit = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            inhalt = (e.get("message") or {}).get("content")
            if isinstance(inhalt, str):
                inhalt = [{"type": "text", "text": inhalt}]
            for b in inhalt or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    tool_namen[b.get("id")] = b.get("name")
                if zeit.strftime("%Y-%m-%d") != LAUFTAG:
                    continue
                if b.get("type") == "text" and e.get("type") == "user":
                    yield zeit, f"Nutzernachricht ({datei.stem[:8]})", b.get("text", "")
                elif b.get("type") == "tool_result" and tool_namen.get(b.get("tool_use_id")) not in NICHT_LAUFAUSGABE:
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                    yield zeit, f"Kommandoausgabe ({datei.stem[:8]})", str(c)


def werte_ausgabe_aus(zeit, quelle, text):
    """Laufausgabe in einem Text erkennen und auswerten."""
    zeilen = text.splitlines()
    gruppen = [m.group(1) for z in zeilen if (m := RE_GRUPPE.match(z.strip()))]
    if not gruppen and "Schicke an" not in text:
        return None
    simuliert = "simulierter Fehler" in text
    return {
        "zeit": zeit, "quelle": quelle, "simuliert": simuliert,
        "gruppen": gruppen,
        "ketten_erkannt": sum(1 for z in zeilen if "Kette(n) erkannt" in z),
        "treffer": {b: sum(1 for z in zeilen if b in z) for b in SUCHBEGRIFFE},
        "http_fehler": re.findall(r"Error code: (\d{3}) - (.{0,80})", text),
        "traceback": "Traceback" in text,
    }


def suche_upload_logs():
    ergebnisse = []
    batches = eu.BACKEND / "batches"
    for log in sorted(batches.glob("b*/pipeline.log")) if batches.exists() else []:
        if lokal(log.stat().st_mtime).strftime("%Y-%m-%d") != LAUFTAG:
            continue
        text = log.read_text(encoding="utf-8", errors="replace")
        ergebnisse.append({"batch": log.parent.name, "zeit": lokal(log.stat().st_mtime),
                           "treffer": {b: text.count(b) for b in SUCHBEGRIFFE if text.count(b)},
                           "status": json.loads((log.parent / "status.json").read_text(encoding="utf-8")).get("phase")
                           if (log.parent / "status.json").exists() else "?"})
    return ergebnisse


# ------------------------------------------------------------------
# 4. Ablauf aus Reihenfolge und Zeitstempeln
# ------------------------------------------------------------------
def rekonstruiere(auswahl, absturz_gruppe, absturz_zeit):
    reihenfolge = [str(c) for c in sorted(auswahl, key=str)]       # wie in extract_chains.main()
    ketten_zeit = {}
    for datei in eu.CHAINS_DIR.glob("chain_cluster_*.json"):
        cid = eu.KETTEN_MUSTER.match(datei.name).group(1)
        ketten_zeit[cid] = max(ketten_zeit.get(cid, 0), datei.stat().st_mtime)
    # Gruppen, deren Ketten vor dem Absturz entstanden, wurden beim Neustart uebersprungen
    # (verarbeitet.json wurde nach dem Absturz aus den vorhandenen Ketten-Dateien befuellt).
    lauf1 = {c for c, t in ketten_zeit.items() if absturz_zeit and t < absturz_zeit.timestamp()}
    lauf2 = [c for c in reihenfolge if c not in lauf1]
    p2 = {c: i for i, c in enumerate(lauf2)}
    ereignisse = sorted((p2[c], lokal(t)) for c, t in ketten_zeit.items() if c in p2)
    ende = lokal(eu.VERARBEITET_DATEI.stat().st_mtime)
    abschnitte = []
    for (pa, ta), (pb, tb) in zip(ereignisse, ereignisse[1:]):
        abschnitte.append({"von": pa, "bis": pb, "t_von": ta, "t_bis": tb,
                           "sek_je_gruppe": (tb - ta).total_seconds() / (pb - pa)})
    p_letzt, t_letzt = ereignisse[-1]
    rest = len(lauf2) - 1 - p_letzt
    schluss = {"von": p_letzt, "bis": len(lauf2) - 1, "t_von": t_letzt, "t_bis": ende,
               "sek_je_gruppe": (ende - t_letzt).total_seconds() / rest if rest else None, "gruppen": rest}
    normal = [a["sek_je_gruppe"] for a in abschnitte if a["sek_je_gruppe"] < 600]
    luecken = [a for a in abschnitte if a["sek_je_gruppe"] >= 600]
    return {"reihenfolge": reihenfolge, "absturz_pos": reihenfolge.index(absturz_gruppe) if absturz_gruppe in reihenfolge else None,
            "lauf1_ketten": sorted(lauf1, key=lambda c: reihenfolge.index(c)), "lauf2": lauf2,
            "ereignisse": ereignisse, "normal_median": st.median(normal) if normal else None,
            "luecken": luecken, "schluss": schluss, "ketten_zeit": ketten_zeit,
            "letzte_kette_gesamtpos": reihenfolge.index(lauf2[p_letzt])}


def main():
    eu.utf8_ausgabe()
    parser = argparse.ArgumentParser(description="Laufpruefung des Enron-Laufs (siehe Modul-Docstring).")
    parser.add_argument("--claude-protokolle", type=Path, default=None,
                        help="Ordner mit den Claude-Code-Sitzungsprotokollen (*.jsonl) dieses Projekts")
    args = parser.parse_args()

    vor = pruefe_vorverarbeitung()
    gruppen, auswahl, max_cluster = rechne_auswahl_nach()
    verarbeitet_text = eu.VERARBEITET_DATEI.read_text(encoding="utf-8")
    verarbeitet = json.loads(verarbeitet_text)
    # markiere_verarbeitet() schreibt json.dumps(sorted(...)) (Trenner ", "); der Nachtrag nach dem
    # Absturz wurde per PowerShell (ConvertTo-Json -Compress, ohne Leerzeichen) geschrieben.
    vom_lauf_geschrieben = verarbeitet_text.strip() == json.dumps(sorted(set(verarbeitet)), ensure_ascii=False)
    auswahl_s = {str(c) for c in auswahl}
    groessen = sorted((len(v) for v in gruppen.values()), reverse=True)
    kleinste = min(len(gruppen[c]) for c in auswahl)

    # Laufausgabe suchen
    funde, roh_treffer = [], {}
    if args.claude_protokolle:
        for zeit, quelle, text in protokoll_texte(args.claude_protokolle):
            for b in SUCHBEGRIFFE:
                if b in text:
                    roh_treffer[b] = roh_treffer.get(b, 0) + 1
            f = werte_ausgabe_aus(zeit, quelle, text)
            if f:
                funde.append(f)
    echte = [f for f in funde if not f["simuliert"] and f["gruppen"]]
    absturz = next((f for f in echte if f["traceback"]), None)
    absturz_gruppe = absturz["gruppen"][-1] if absturz else None
    absturz_zeit = absturz["zeit"] if absturz else None
    uploads = suche_upload_logs()
    r = rekonstruiere(auswahl, absturz_gruppe, absturz_zeit)
    s = r["schluss"]

    md = [
        "# Laufpruefung: Enron-Extraktion vom 11.09.2026",
        "",
        "## 1. Datengrundlage",
        "",
        f"- `prepare_emails.py` liest die **ersten {vor['max_mails']:,} Zeilen** der CSV (`MAX_MAILS`, Abbruch bei "
        f"Zeilenindex >= {vor['max_mails']:,}); Mails mit weniger als {vor['min_body_len']} Zeichen Body nach der "
        f"Bereinigung werden uebersprungen. Die Mail-ID ist der Zeilenindex (`mail_<index>`), hoechste ID: "
        f"`mail_{vor['hoechste_id']:05d}`. `MAX_MAILS` wurde am 11.09. von 2.000 auf 30.000 erhoeht.",
        f"- `mails.jsonl`: **{vor['mails_jsonl']:,} Zeilen** (Stand {vor['mails_zeit']:%d.%m. %H:%M}); "
        f"{vor['max_mails'] - vor['mails_jsonl']:,} der {vor['max_mails']:,} CSV-Zeilen fielen durch den Laengenfilter.",
        f"- `clusters.jsonl`: **{vor['clusters_jsonl']:,} Zeilen** (Stand {vor['clusters_zeit']:%d.%m. %H:%M}) – nach "
        f"Deduplizierung nach Body ({vor['mails_jsonl'] - vor['clusters_jsonl']:,} Dubletten entfernt).",
        "",
        "## 2. verarbeitet.json und die 300 groessten Gruppen",
        "",
        f"- Eintraege in `verarbeitet.json`: **{len(verarbeitet)}** (Stand {lokal(eu.VERARBEITET_DATEI.stat().st_mtime):%d.%m. %H:%M}).",
        f"- Gruppen im `--alle`-Modus: {len(gruppen):,} ({sum(1 for c in gruppen if not str(c).startswith('e')):,} Cluster "
        f"+ {sum(1 for c in gruppen if str(c).startswith('e')):,} Einzelmails). Die {max_cluster} groessten "
        f"(nachgerechnet mit `extract_chains.waehle_cluster`) haben mindestens {kleinste} Mails; "
        f"{sum(1 for g in groessen if g >= kleinste)} Gruppen haben diese Groesse, die Grenze liegt also innerhalb der "
        f"{kleinste}-Mail-Cluster.",
        f"- Davon in `verarbeitet.json`: **{len(auswahl_s & set(verarbeitet))} von {len(verarbeitet)}**"
        + (" – identisch mit der Auswahl der 300 groessten Gruppen." if auswahl_s == set(verarbeitet) else
           f"; nicht in der Auswahl: {sorted(set(verarbeitet) - auswahl_s)}"),
        "- Wichtig: `verarbeitet.json` markiert jede Gruppe nach dem Aufruf – auch bei Fehler, leerer Antwort oder "
        "ohne Kette. Der Eintrag belegt also nicht, dass eine gueltige LLM-Antwort vorlag.",
        f"- Format der Datei: {'entspricht' if vom_lauf_geschrieben else 'entspricht NICHT'} der Ausgabe von "
        "`markiere_verarbeitet()` (sortiert, `json.dumps`) – "
        + ("sie wurde zuletzt vom Lauf selbst geschrieben, nicht von Hand oder durch den Nachtrag nach dem Absturz."
           if vom_lauf_geschrieben else "sie wurde zuletzt auf anderem Weg geschrieben."),
        "",
        "## 3. Erhaltene Laufausgabe",
        "",
    ]
    if not args.claude_protokolle:
        md.append("Claude-Code-Protokolle nicht durchsucht (Aufruf ohne `--claude-protokolle`).")
    else:
        md += [
            f"Durchsucht: Claude-Code-Protokolle (`{args.claude_protokolle.name}`), Nutzernachrichten und "
            f"Kommandoausgaben vom {LAUFTAG}, sowie `backend/batches/*/pipeline.log` vom selben Tag. Im Projekt gibt "
            "es keine Logdatei des Enron-Laufs (die Ausgabe ging nur auf die Konsole).",
            "",
            f"- Rohtreffer der Suchbegriffe in Nutzernachrichten und Kommandoausgaben: "
            + (", ".join(f"„{b}“ {n}×" for b, n in roh_treffer.items()) or "keine") + ".",
        ]
        for f in funde:
            art = "Testausgabe mit simuliertem Fehler (kein Laufergebnis)" if f["simuliert"] else "Ausgabe des Enron-Laufs"
            http = "; ".join(f"HTTP {c}: {t.strip()}" for c, t in f["http_fehler"])
            md.append(f"- {f['zeit']:%d.%m. %H:%M} – {f['quelle']}: {art}. Gruppen im Ausschnitt: "
                      f"{', '.join(f['gruppen']) or '–'}; „Kette(n) erkannt“ {f['ketten_erkannt']}×"
                      + (f"; Absturz mit Traceback ({http})" if f["traceback"] else "")
                      + (f"; {http}" if http and not f["traceback"] else "") + ".")
        md += [
            "",
            "**Ergebnis der Suche:** Von der Laufausgabe ist nur der Ausschnitt erhalten, den der Nutzer nach dem "
            "ersten Absturz in die Sitzung kopiert hat" + (f" (Gruppe {absturz_gruppe}, {absturz_zeit:%H:%M} Uhr)" if absturz else "")
            + ". Er enthaelt keinen der Begriffe „FEHLER bei diesem Cluster“, „LEERE Antwort“, „transienter Fehler“, "
            "quota, budget, credit, 402 oder 429; der Absturz war ein HTTP-400-Verbindungsfehler der KIT-Toolbox. "
            "Die Rohtreffer stammen aus einem Funktionstest mit simuliertem Fehler. **Fuer den Neustart ab 18:25 Uhr "
            "existiert keine Ausgabe mehr** – wie viele Gruppen eine gueltige Antwort bekamen und ob bzw. wann ein "
            "Guthaben- oder Kontingentfehler auftrat, laesst sich daraus nicht direkt belegen.",
        ]
    md += ["", "Upload-Logs vom 11.09. (Upload-Laeufe, nicht der Enron-Lauf):", ""]
    md += [f"- {u['batch']} ({u['zeit']:%H:%M}, Status `{u['status']}`): "
           + (", ".join(f"„{b}“ {n}×" for b, n in u["treffer"].items()) or "keine Treffer") for u in uploads] or ["- keine"]

    # Rekonstruktion
    e = r["ereignisse"]
    md += [
        "",
        "## 4. Rekonstruktion aus Verarbeitungsreihenfolge und Dateizeiten",
        "",
        "`extract_chains.py` verarbeitet die ausgewaehlten Gruppen in der Reihenfolge ihrer Cluster-ID als Text "
        "(`sorted(..., key=str)`); jede Ketten-Datei traegt den Zeitpunkt, zu dem ihre Gruppe fertig war. Daraus "
        "ergibt sich die Dauer je Gruppe zwischen zwei Gruppen mit Kette.",
        "",
        f"- **Lauf 1** (ab ca. {vor['clusters_zeit']:%H:%M}): Positionen 0–{r['absturz_pos']} der Reihenfolge; Ketten "
        f"fuer {len(r['lauf1_ketten'])} Gruppen ({', '.join(r['lauf1_ketten'])}); Absturz bei Gruppe {absturz_gruppe} "
        f"(Position {r['absturz_pos']}). Diese {len(r['lauf1_ketten'])} Gruppen wurden danach in `verarbeitet.json` "
        "nachgetragen und beim Neustart uebersprungen.",
        f"- **Neustart** mit Fortsetzungslogik: {len(r['lauf2'])} Gruppen. Ketten entstanden an den Positionen "
        f"{e[0][0]}–{e[-1][0]} ({e[0][1]:%H:%M}–{e[-1][1]:%H:%M} Uhr); typische Dauer je Gruppe (Median der Abschnitte "
        f"zwischen zwei Ketten): **{r['normal_median']:.0f} s**.",
    ]
    for l in r["luecken"]:
        md.append(f"- Unterbrechung: zwischen Position {l['von']} ({l['t_von']:%H:%M}) und {l['bis']} ({l['t_bis']:%H:%M}) "
                  f"liegen nur {l['bis'] - l['von'] - 1} Gruppe(n) in {(l['t_bis'] - l['t_von']).total_seconds() / 3600:.1f} h – "
                  "der Lauf war in dieser Zeit angehalten (z.B. Rechner im Ruhezustand oder manueller Neustart).")
    md += [
        f"- **Schlussphase:** Nach der letzten Kette (Gruppe {r['lauf2'][s['von']]}, Position {s['von']}, "
        f"{s['t_von']:%H:%M:%S}) wurden die restlichen **{s['gruppen']} Gruppen** bis {s['t_bis']:%H:%M:%S} als verarbeitet "
        f"markiert – **{s['sek_je_gruppe']:.1f} s je Gruppe** statt ~{r['normal_median']:.0f} s. In dieser Zeit ist keine "
        "LLM-Antwort moeglich; die Anfragen wurden sehr wahrscheinlich sofort abgelehnt und als „FEHLER bei diesem "
        "Cluster“ uebersprungen. Voruebergehende Fehler scheiden aus: Rate-Limits (429), Ueberlastung (502/503/504), "
        "Timeouts und Verbindungsfehler wiederholt `frage_llm()` mit zusammen 50 s Wartezeit. Passend sind sofort "
        "endgueltige Ablehnungen wie 401 (Schluessel ungueltig/abgelaufen), 402/403 (Guthaben, Kontingent, Berechtigung).",
        "",
        "## Ergebnis",
        "",
        "| | Gruppen | Beleg |",
        "|---|---|---|",
        f"| ausgewaehlt und in `verarbeitet.json` | {len(verarbeitet)} | nachgerechnete Top-{max_cluster}-Auswahl = verarbeitet.json |",
        f"| in normalem Tempo verarbeitet (LLM-Antwort anzunehmen) | {r['letzte_kette_gesamtpos'] + 1} | Positionen "
        f"0–{r['letzte_kette_gesamtpos']} der Reihenfolge |",
        f"| davon mit mindestens einer Kette | {len(r['ketten_zeit'])} | Ketten-Dateien |",
        f"| davon ohne Kette (keine belegbare Kette oder einzelner Fehler – nicht unterscheidbar) | "
        f"{r['letzte_kette_gesamtpos'] + 1 - len(r['ketten_zeit'])} | Differenz |",
        f"| sehr wahrscheinlich mit Fehler uebersprungen | {s['gruppen']} | {s['sek_je_gruppe']:.1f} s je Gruppe nach {s['t_von']:%H:%M} |",
        "",
        f"- **Erster Fehler (vermutlich):** unmittelbar nach {s['t_von']:%H:%M:%S} Uhr bei Gruppe "
        f"{r['lauf2'][s['von'] + 1] if s['gruppen'] else '–'}. Die Fehlermeldung ist nicht erhalten; ob es ein Guthaben- bzw. "
        "Kontingentfehler war oder z.B. ein abgelaufener Schluessel (die Upload-Logs vom 22. und 24.09. zeigen "
        "HTTP 401 „session has expired or the token is invalid“), laesst sich nicht belegen.",
        f"- **Folge fuer die Auswertung:** Die Aussage „36 von 300 Clustern ergaben eine Kette (12 %)“ ist nicht haltbar; "
        f"belastbar ist etwa {len(r['ketten_zeit'])} von {r['letzte_kette_gesamtpos'] + 1} tatsaechlich beantworteten Gruppen "
        f"({len(r['ketten_zeit']) / (r['letzte_kette_gesamtpos'] + 1):.0%}). Die uebrigen {s['gruppen']} der 300 groessten Gruppen "
        "wurden faktisch nicht extrahiert; ein erneuter Lauf mit geleerter bzw. bereinigter `verarbeitet.json` wuerde "
        "sie nachholen.",
    ]

    eu.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (eu.OUT_DIR / "LAUFPRUEFUNG.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
