// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
// Nimmt hochgeladene Postfach-Dateien entgegen, legt einen Batch-Ordner unter
// backend/batches/<id>/ an und startet die Python-Pipeline (run_pipeline.py) als
// abgekoppelten Kindprozess. Der Fortschritt landet in status.json im Batch-Ordner.

import { promises as fs } from "fs";
import { existsSync } from "fs";
import path from "path";
import { spawn } from "child_process";

const PROJEKT_ROOT = path.join(process.cwd(), "..");
const BACKEND_DIR = path.join(PROJEKT_ROOT, "backend");
const BATCHES_DIR = path.join(BACKEND_DIR, "batches");

const BATCH_ID_RE = /^b[a-z0-9_]+$/;

export interface BatchStatus {
  batch_id: string;
  phase: "queued" | "parse" | "cluster" | "extract" | "done" | "error";
  phasen_text: string;
  fortschritt: { aktuell: number; gesamt: number };
  zahlen: { mails: number; cluster: number; rauschen: number; ketten: number };
  fehler: string | null;
  gestartet: string;
  aktualisiert: string;
}

// Gibt es einen KIT-Toolbox-Key? Entweder als Umgebungsvariable oder in
// <Projekt>/.env. Die Python-Skripte lesen die .env selbst (backend/env_laden.py);
// hier wird nur geprueft, damit ein Upload ohne Key sofort mit klarer Meldung
// abgelehnt wird statt erst mitten in der Pipeline zu scheitern.
export async function hatApiKey(): Promise<boolean> {
  if (process.env.OPENAI_API_KEY) return true;
  try {
    const roh = await fs.readFile(path.join(PROJEKT_ROOT, ".env"), "utf-8");
    return /^\s*OPENAI_API_KEY\s*=\s*["']?[^\s"']+/m.test(roh.replace(/^﻿/, ""));
  } catch {
    return false;
  }
}

function pythonPfad(): string {
  // Bevorzugt das venv des Projekts, sonst "python" vom PATH.
  const kandidaten = [
    path.join(PROJEKT_ROOT, ".venv", "Scripts", "python.exe"),
    path.join(PROJEKT_ROOT, ".venv", "bin", "python"),
  ];
  for (const k of kandidaten) if (existsSync(/*turbopackIgnore: true*/ k)) return k;
  return "python";
}

export function erzeugeBatchId(): string {
  const d = new Date();
  const z = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}_${z(
    d.getHours()
  )}${z(d.getMinutes())}${z(d.getSeconds())}`;
  const rnd = Math.random().toString(36).slice(2, 6);
  return `b${stamp}_${rnd}`;
}

export async function starteBatch(
  batchId: string,
  dateien: { name: string; buffer: Buffer }[],
  modell?: string
): Promise<void> {
  if (!BATCH_ID_RE.test(batchId)) throw new Error("Ungueltige Batch-ID.");

  const batchDir = path.join(BATCHES_DIR, batchId);
  const uploadDir = path.join(batchDir, "upload");
  await fs.mkdir(uploadDir, { recursive: true });

  for (const d of dateien) {
    // nur der Basisname, kein Pfad-Anteil aus dem Upload
    const sicher = path.basename(d.name).replace(/[^a-zA-Z0-9._-]/g, "_");
    await fs.writeFile(path.join(uploadDir, sicher || "upload.bin"), d.buffer);
  }

  if (modell) {
    await fs.writeFile(
      path.join(batchDir, "config.json"),
      JSON.stringify({ modell }, null, 2),
      "utf-8"
    );
  }

  // Ohne "detached": auf Windows oeffnet detached trotz windowsHide ein
  // Konsolenfenster. Dank stdio "ignore" + unref() laeuft der Kindprozess
  // trotzdem unabhaengig vom Request weiter.
  const kind = spawn(
    /*turbopackIgnore: true*/ pythonPfad(),
    [path.join(BACKEND_DIR, "run_pipeline.py"), "--batch-dir", batchDir],
    {
      cwd: BACKEND_DIR,
      stdio: "ignore",
      windowsHide: true,
      env: process.env,
    }
  );
  kind.unref();
}

export async function leseStatus(batchId: string): Promise<BatchStatus | null> {
  if (!BATCH_ID_RE.test(batchId)) return null;
  try {
    const roh = await fs.readFile(
      path.join(BATCHES_DIR, batchId, "status.json"),
      "utf-8"
    );
    return JSON.parse(roh) as BatchStatus;
  } catch {
    return null;
  }
}
