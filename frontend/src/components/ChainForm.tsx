// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ActionChain } from "@/lib/types";

// Formular zum Anlegen/Bearbeiten einer Aktionskette. Titel, Zusammenfassung,
// Tags und Bewertung sind normale Formularfelder; Akteure, Knoten, Flows und
// Quellen (verschachtelt, viele optionale Felder) werden als JSON bearbeitet
// und vor dem Speichern geprueft. Die grafische Darstellung zeigt die
// Ansichtsseite.

export default function ChainForm({
  initial,
  onSubmit,
  submitLabel,
}: {
  initial: ActionChain;
  onSubmit: (data: ActionChain) => Promise<void>;
  submitLabel: string;
}) {
  const router = useRouter();
  const [titel, setTitel] = useState(initial.title);
  const [summary, setSummary] = useState(initial.summary ?? "");
  const [tags, setTags] = useState((initial.tags ?? []).join(", "));
  const [wahrscheinlichkeit, setWahrscheinlichkeit] = useState(
    initial.prozess_wahrscheinlichkeit?.toString() ?? ""
  );
  const [begruendung, setBegruendung] = useState(initial.prozess_begruendung ?? "");

  const [actorsJson, setActorsJson] = useState(JSON.stringify(initial.actors ?? [], null, 2));
  const [nodesJson, setNodesJson] = useState(JSON.stringify(initial.nodes ?? [], null, 2));
  const [flowsJson, setFlowsJson] = useState(JSON.stringify(initial.flows ?? [], null, 2));
  const [sourcesJson, setSourcesJson] = useState(JSON.stringify(initial.sources ?? [], null, 2));

  const [fehler, setFehler] = useState<string | null>(null);
  const [speichert, setSpeichert] = useState(false);

  function parseJsonFeld<T>(text: string, feldname: string): T {
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new Error(`${feldname}: kein gültiges JSON.`);
    }
  }

  async function absenden(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);

    if (!titel.trim()) {
      setFehler("Titel ist ein Pflichtfeld.");
      return;
    }

    let data: ActionChain;
    try {
      data = {
        ...initial,
        title: titel.trim(),
        summary: summary.trim(),
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        prozess_wahrscheinlichkeit: wahrscheinlichkeit
          ? Number(wahrscheinlichkeit)
          : undefined,
        prozess_begruendung: begruendung.trim() || undefined,
        actors: parseJsonFeld(actorsJson, "Akteure"),
        nodes: parseJsonFeld(nodesJson, "Knoten"),
        flows: parseJsonFeld(flowsJson, "Flows"),
        sources: parseJsonFeld(sourcesJson, "Quellen"),
      };
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Ungültige Eingabe.");
      return;
    }

    setSpeichert(true);
    try {
      await onSubmit(data);
    } finally {
      setSpeichert(false);
    }
  }

  return (
    <form onSubmit={absenden} className="space-y-6">
      {fehler && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{fehler}</div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-700">Titel *</label>
        <input
          value={titel}
          onChange={(e) => setTitel(e.target.value)}
          className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700">Zusammenfassung</label>
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          rows={2}
          className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Tags (Komma-getrennt)</label>
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">
            Prozess-Wahrscheinlichkeit (0–1)
          </label>
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={wahrscheinlichkeit}
            onChange={(e) => setWahrscheinlichkeit(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700">Begründung</label>
        <textarea
          value={begruendung}
          onChange={(e) => setBegruendung(e.target.value)}
          rows={2}
          className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </div>

      <details className="rounded-md border border-gray-200 p-4" open>
        <summary className="cursor-pointer text-sm font-medium text-gray-700">
          Akteure, Knoten, Flows, Quellen (als JSON)
        </summary>
        <div className="mt-4 space-y-4">
          <JsonFeld label="Akteure" value={actorsJson} onChange={setActorsJson} />
          <JsonFeld label="Knoten" value={nodesJson} onChange={setNodesJson} />
          <JsonFeld label="Flows" value={flowsJson} onChange={setFlowsJson} />
          <JsonFeld label="Quellen" value={sourcesJson} onChange={setSourcesJson} />
        </div>
      </details>

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={speichert}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {speichert ? "Speichert..." : submitLabel}
        </button>
        <button
          type="button"
          onClick={() => router.back()}
          className="rounded-md border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
        >
          Abbrechen
        </button>
      </div>
    </form>
  );
}

function JsonFeld({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-500">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={8}
        spellCheck={false}
        className="mt-1 w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 font-mono text-xs"
      />
    </div>
  );
}
