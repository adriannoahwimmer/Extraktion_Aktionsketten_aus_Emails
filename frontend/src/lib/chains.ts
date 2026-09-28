// Liest/schreibt Aktionsketten direkt als JSON-Dateien in backend/chains/.
// Bewusst kein separates DB-System - fuer ein lokales Seminar-Projekt reicht
// das Dateisystem, und es ist derselbe Ordner, in den extract_chains.py
// (Python-Pipeline) seine Ergebnisse schreibt.

import { promises as fs } from "fs";
import path from "path";
import { randomUUID } from "crypto";
import type { ActionChain, StoredChain } from "./types";

const CHAINS_DIR = path.join(process.cwd(), "..", "backend", "chains");

async function stelleOrdnerSicher() {
  await fs.mkdir(CHAINS_DIR, { recursive: true });
}

function slugZuDateipfad(slug: string): string {
  // Schutz gegen Path-Traversal: nur erlaubte Zeichen im Slug zulassen.
  if (!/^[a-zA-Z0-9_-]+$/.test(slug)) {
    throw new Error(`Ungueltiger Slug: ${slug}`);
  }
  return path.join(CHAINS_DIR, `${slug}.json`);
}

export async function listeChains(): Promise<StoredChain[]> {
  await stelleOrdnerSicher();
  const dateien = await fs.readdir(CHAINS_DIR);
  const ketten: StoredChain[] = [];

  for (const datei of dateien) {
    if (!datei.endsWith(".json")) continue;
    const slug = datei.replace(/\.json$/, "");
    try {
      const inhalt = await fs.readFile(path.join(CHAINS_DIR, datei), "utf-8");
      ketten.push({ slug, data: JSON.parse(inhalt) });
    } catch (fehler) {
      console.error(`Konnte ${datei} nicht laden:`, fehler);
    }
  }

  return ketten;
}

export async function holeChain(slug: string): Promise<StoredChain | null> {
  try {
    const inhalt = await fs.readFile(slugZuDateipfad(slug), "utf-8");
    return { slug, data: JSON.parse(inhalt) };
  } catch {
    return null;
  }
}

export async function speichereChain(slug: string, data: ActionChain): Promise<void> {
  await stelleOrdnerSicher();
  await fs.writeFile(slugZuDateipfad(slug), JSON.stringify(data, null, 2), "utf-8");
}

export async function erstelleChain(data: ActionChain): Promise<string> {
  await stelleOrdnerSicher();
  const slug = `chain_manuell_${randomUUID().slice(0, 8)}`;
  await speichereChain(slug, data);
  return slug;
}

export async function loescheChain(slug: string): Promise<boolean> {
  try {
    await fs.unlink(slugZuDateipfad(slug));
    return true;
  } catch {
    return false;
  }
}
