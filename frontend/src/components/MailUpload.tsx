"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { BatchStatus } from "@/lib/batches";

const PHASEN: Record<BatchStatus["phase"], string> = {
  queued: "In Warteschlange",
  parse: "Postfach einlesen",
  cluster: "Einbetten & Clustern",
  extract: "Aktionsketten extrahieren",
  done: "Fertig",
  error: "Fehler",
};

export default function MailUpload({ onFertig }: { onFertig: () => void }) {
  const [datei, setDatei] = useState<File | null>(null);
  const [modell, setModell] = useState("google.claude-sonnet-5");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [status, setStatus] = useState<BatchStatus | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [sende, setSende] = useState(false);
  const fertigGemeldet = useRef(false);
  const dateiInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!batchId) return;
    let aktiv = true;
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/batches/${batchId}/status`);
        if (!res.ok) return;
        const s: BatchStatus = await res.json();
        if (!aktiv) return;
        setStatus(s);
        if (s.phase === "done" && !fertigGemeldet.current) {
          fertigGemeldet.current = true;
          onFertig();
        }
        if (s.phase === "done" || s.phase === "error") clearInterval(timer);
      } catch {
        /* transient - nächster Tick */
      }
    }, 2000);
    return () => {
      aktiv = false;
      clearInterval(timer);
    };
  }, [batchId, onFertig]);

  const absenden = useCallback(async () => {
    if (!datei) return;
    setSende(true);
    setFehler(null);
    setStatus(null);
    fertigGemeldet.current = false;
    try {
      const fd = new FormData();
      fd.append("files", datei);
      fd.append("modell", modell);
      const res = await fetch("/api/batches", { method: "POST", body: fd });
      const daten = await res.json();
      if (!res.ok) throw new Error(daten.fehler ?? "Upload fehlgeschlagen.");
      setBatchId(daten.batch_id);
    } catch (e) {
      setFehler(e instanceof Error ? e.message : "Upload fehlgeschlagen.");
    } finally {
      setSende(false);
    }
  }, [datei, modell]);

  const laeuft =
    !!status && status.phase !== "done" && status.phase !== "error";
  const prozent =
    status && status.fortschritt.gesamt > 0
      ? Math.round((status.fortschritt.aktuell / status.fortschritt.gesamt) * 100)
      : null;

  return (
    <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-1 font-medium text-gray-900">Postfach hochladen</h2>
      <p className="mb-3 text-sm text-gray-500">
        {".eml"}, {".mbox"}, {".pst"} oder {".zip"}. Es werden nur die Mails
        dieses Uploads verarbeitet; bestehende Aktionsketten bleiben unverändert.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={dateiInput}
          type="file"
          accept=".eml,.mbox,.pst,.zip"
          onChange={(e) => setDatei(e.target.files?.[0] ?? null)}
          disabled={sende || laeuft}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => dateiInput.current?.click()}
          disabled={sende || laeuft}
          className="rounded-md border border-gray-300 bg-gray-50 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-40"
        >
          Datei wählen…
        </button>
        <span className="max-w-[16rem] truncate text-sm text-gray-500">
          {datei ? datei.name : "keine Datei ausgewählt"}
        </span>
        <select
          value={modell}
          onChange={(e) => setModell(e.target.value)}
          disabled={sende || laeuft}
          className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
        >
          <option value="google.claude-sonnet-5">Sonnet 5 (günstiger)</option>
          <option value="google.claude-opus-4.8">Opus 4.8 (stärker)</option>
        </select>
        <button
          onClick={absenden}
          disabled={!datei || sende || laeuft}
          className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {sende ? "Starte…" : "Aktionsketten extrahieren"}
        </button>
      </div>

      {fehler && (
        <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{fehler}</p>
      )}

      {status && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-gray-700">
              {PHASEN[status.phase]}
              {laeuft && status.fortschritt.gesamt > 0 && (
                <span className="ml-2 text-gray-500">
                  {status.fortschritt.aktuell}/{status.fortschritt.gesamt}
                </span>
              )}
            </span>
            <span className="text-gray-400">
              {status.zahlen.mails > 0 && `${status.zahlen.mails} Mails`}
              {status.zahlen.cluster > 0 && ` · ${status.zahlen.cluster} Cluster`}
              {status.phase === "done" && ` · ${status.zahlen.ketten} Ketten`}
            </span>
          </div>

          {laeuft && (
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-100">
              <div
                className="h-full bg-indigo-500 transition-all"
                style={{ width: prozent !== null ? `${prozent}%` : "33%" }}
              />
            </div>
          )}

          {status.phase === "error" && (
            <p className="mt-2 rounded-md bg-red-50 p-2 text-sm text-red-700">
              {status.fehler ?? "Unbekannter Fehler."}
            </p>
          )}
          {status.phase === "done" && (
            <p className="mt-2 text-sm text-green-700">
              Fertig – {status.zahlen.ketten} neue Aktionskette(n) unten in der Liste.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
