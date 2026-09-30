# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"""
token_kompression.py
--------------------------------------------------
Schritt 3 der Auswertung: wie stark verdichtet eine Aktionskette ihre Quellmails?

Je Kette werden gezaehlt:
  - Quellmails: Tokens von Betreff + Body aller in sources[] genannten Mails
    (Zuordnung wie in der Belegpruefung; jede Mail pro Kette einmal; bei
    mehrdeutiger Zuordnung die erste noch nicht verwendete Kandidatin, damit
    zwei Quellen mit gleichem Absender/Betreff/Tag zwei Mails ergeben)
  - (a) die Kette als vollstaendiges JSON (kompakt, ohne Einrueckung)
  - (b) nur Titel, Zusammenfassung und die Aktionen der Aufgabenknoten
Tokenizer: tiktoken cl100k_base (OpenAI) als NAEHERUNG - Claude nutzt einen
eigenen Tokenizer, die absoluten Zahlen weichen daher ab, die Verhaeltnisse
sind als Groessenordnung aussagekraeftig.

Aufruf:  python token_kompression.py      (braucht tiktoken, siehe requirements.txt)
Ausgabe: out/token_kompression.md, out/token_kompression.csv
"""

import csv
import json
import statistics as st

import tiktoken

import eval_utils as eu

ENCODING = "cl100k_base"


def text_b(kette) -> str:
    teile = [kette.get("title", ""), kette.get("summary", "")]
    teile += [n.get("action", "") for n in eu.aufgabenknoten(kette)]
    return "\n".join(t for t in teile if t)


def main():
    eu.utf8_ausgabe()
    enc = tiktoken.get_encoding(ENCODING)
    tokens = lambda text: len(enc.encode(text, disallowed_special=()))  # noqa: E731

    ketten = eu.lade_enron_ketten()
    index = eu.MailIndex(eu.lade_mails_dedup(), eu.lade_cluster_zuordnung())

    zeilen, unvollstaendig = [], []
    alle_quellmails = set()
    for k in ketten:
        zuordnung = eu.ordne_kette_zu(k["data"], k["cid"], index)
        mail_ids = []
        for z in zuordnung.values():
            frei = [m for m in z["mail_ids"] if m not in mail_ids]
            if frei:
                mail_ids.append(frei[0])
        if any(not z["mail_ids"] for z in zuordnung.values()):
            unvollstaendig.append(k["slug"])
        alle_quellmails.update(mail_ids)
        t_quelle = sum(tokens(f"{index.mails[m].get('subject', '')}\n\n{index.mails[m].get('body', '')}")
                       for m in mail_ids)
        t_a = tokens(json.dumps(k["data"], ensure_ascii=False))
        t_b = tokens(text_b(k["data"]))
        zeilen.append({
            "kette": k["slug"], "quellmails": len(mail_ids), "tokens_quellmails": t_quelle,
            "tokens_json": t_a, "tokens_titel_zus_aktionen": t_b,
            "verhaeltnis_json": t_a / t_quelle if t_quelle else None,
            "verhaeltnis_text": t_b / t_quelle if t_quelle else None,
        })

    gueltig = [z for z in zeilen if z["tokens_quellmails"]]
    r_a = [z["verhaeltnis_json"] for z in gueltig]
    r_b = [z["verhaeltnis_text"] for z in gueltig]
    s_q = sum(z["tokens_quellmails"] for z in gueltig)
    s_a = sum(z["tokens_json"] for z in gueltig)
    s_b = sum(z["tokens_titel_zus_aktionen"] for z in gueltig)
    s_eindeutig = sum(tokens(f"{index.mails[m].get('subject', '')}\n\n{index.mails[m].get('body', '')}")
                      for m in alle_quellmails)

    md = [
        "# Token-Kompression: Aktionskette vs. Quellmails",
        "",
        f"Tokenizer: `tiktoken` {ENCODING} als **Naeherung** (Claude verwendet einen eigenen Tokenizer; "
        "absolute Werte weichen ab, die Verhaeltnisse geben die Groessenordnung an).",
        "Quellmails = Betreff + Body der in `sources[]` genannten Mails (gesaeuberter Text aus `mails.jsonl`, "
        "wie ihn das LLM gesehen hat). (a) = Kette als kompaktes JSON; (b) = nur Titel, Zusammenfassung und "
        "Aktionen der Aufgabenknoten (ohne Gateways, Akteure, Belege).",
        "",
        "| Kennzahl | (a) vollstaendiges JSON | (b) Titel + Zusammenfassung + Aktionen |",
        "|---|---|---|",
        f"| Median Verhaeltnis Kette/Quellmails (je Kette) | {st.median(r_a):.2f} | {st.median(r_b):.2f} |",
        f"| entspricht Kompressionsfaktor Quellmails/Kette (Median) | {st.median(1 / r for r in r_a):.1f}× | "
        f"{st.median(1 / r for r in r_b):.1f}× |",
        f"| Summe Tokens Kette ({len(gueltig)} Ketten) | {s_a:,} | {s_b:,} |",
        f"| Summe Tokens Quellmails | {s_q:,} | {s_q:,} |",
        f"| Verhaeltnis der Summen Kette/Quellmails | {s_a / s_q:.2f} | {s_b / s_q:.2f} |",
        "",
        (f"Keine Quellmail liegt mehreren Ketten zugrunde: {len(alle_quellmails)} verschiedene Mails, "
         f"{s_eindeutig:,} Tokens." if s_eindeutig == s_q else
         f"Die Summe der Quellmails zaehlt Mails, die mehreren Ketten zugrunde liegen, mehrfach; "
         f"jede Quellmail einmal gezaehlt: {s_eindeutig:,} Tokens in {len(alle_quellmails)} Mails."),
        f"Median Tokens je Kette: Quellmails {st.median(z['tokens_quellmails'] for z in gueltig):g}, "
        f"(a) {st.median(z['tokens_json'] for z in gueltig):g}, (b) {st.median(z['tokens_titel_zus_aktionen'] for z in gueltig):g}.",
        f"Ketten mit (a) groesser als die Quellmails: {sum(1 for r in r_a if r > 1)}; "
        f"mit (b) groesser: {sum(1 for r in r_b if r > 1)}.",
    ]
    if unvollstaendig:
        md.append(f"Ketten mit nicht zuordenbaren Quellen (Quellmails unvollstaendig gezaehlt): {', '.join(unvollstaendig)}")

    eu.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (eu.OUT_DIR / "token_kompression.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with open(eu.OUT_DIR / "token_kompression.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(zeilen[0].keys()), delimiter=";")
        w.writeheader()
        for z in zeilen:
            w.writerow({**z, "verhaeltnis_json": f"{z['verhaeltnis_json']:.3f}",
                        "verhaeltnis_text": f"{z['verhaeltnis_text']:.3f}"})
    print("\n".join(md))


if __name__ == "__main__":
    main()
