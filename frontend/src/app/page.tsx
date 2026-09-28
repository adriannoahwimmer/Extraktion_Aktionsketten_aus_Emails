// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { StoredChain } from "@/lib/types";
import WahrscheinlichkeitBadge from "@/components/WahrscheinlichkeitBadge";
import MailUpload from "@/components/MailUpload";

export default function StartSeite() {
  const [ketten, setKetten] = useState<StoredChain[]>([]);
  const [suche, setSuche] = useState("");
  const [ladend, setLadend] = useState(true);

  const neuLaden = useCallback(async () => {
    setLadend(true);
    const res = await fetch("/api/chains");
    const daten: StoredChain[] = await res.json();
    daten.sort((a, b) => a.data.title.localeCompare(b.data.title));
    setKetten(daten);
    setLadend(false);
  }, []);

  useEffect(() => {
    let abbruch = false;
    (async () => {
      const res = await fetch("/api/chains");
      const daten: StoredChain[] = await res.json();
      if (abbruch) return;
      daten.sort((a, b) => a.data.title.localeCompare(b.data.title));
      setKetten(daten);
      setLadend(false);
    })();
    return () => {
      abbruch = true;
    };
  }, []);

  const gefiltert = useMemo(() => {
    const q = suche.trim().toLowerCase();
    if (!q) return ketten;
    return ketten.filter(({ data }) => {
      const heuhaufen = [
        data.title,
        data.summary,
        ...(data.tags ?? []),
        ...(data.actors ?? []).map((a) => a.name),
        ...data.nodes.map((n) => n.action ?? n.label ?? ""),
      ]
        .join(" ")
        .toLowerCase();
      return heuhaufen.includes(q);
    });
  }, [ketten, suche]);

  async function loeschen(slug: string, titel: string) {
    if (!confirm(`"${titel}" wirklich löschen?`)) return;
    await fetch(`/api/chains/${slug}`, { method: "DELETE" });
    neuLaden();
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Aktionsketten</h1>
        <Link
          href="/chains/new"
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
        >
          + Neue Aktionskette
        </Link>
      </div>

      <MailUpload onFertig={neuLaden} />

      <input
        type="text"
        placeholder="Suchen nach Titel, Zusammenfassung, Tags, Akteuren, Aktionen..."
        value={suche}
        onChange={(e) => setSuche(e.target.value)}
        className="mb-6 w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none"
      />

      {ladend && <p className="text-gray-500">Lade...</p>}
      {!ladend && gefiltert.length === 0 && (
        <p className="text-gray-500">Keine Aktionsketten gefunden.</p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {gefiltert.map(({ slug, data }) => (
          <div
            key={slug}
            className="flex flex-col justify-between rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div>
              <div className="mb-2 flex items-start justify-between gap-2">
                <h2 className="font-medium text-gray-900">{data.title}</h2>
                <WahrscheinlichkeitBadge wert={data.prozess_wahrscheinlichkeit} />
              </div>
              <p className="mb-3 text-sm text-gray-600">{data.summary}</p>
              <div className="mb-3 flex flex-wrap gap-1">
                {(data.tags ?? []).map((t) => (
                  <span
                    key={t}
                    className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
                  >
                    {t}
                  </span>
                ))}
              </div>
              <p className="text-xs text-gray-400">
                {data.nodes.length} Knoten · {(data.actors ?? []).length} Akteure
              </p>
            </div>
            <div className="mt-4 flex gap-2 border-t border-gray-100 pt-3 text-sm">
              <Link href={`/chains/${slug}`} className="text-indigo-600 hover:underline">
                Ansehen
              </Link>
              <Link href={`/chains/${slug}/edit`} className="text-gray-600 hover:underline">
                Bearbeiten
              </Link>
              <button
                onClick={() => loeschen(slug, data.title)}
                className="ml-auto text-red-600 hover:underline"
              >
                Löschen
              </button>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
