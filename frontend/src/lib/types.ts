// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
// Entspricht dem Schema aus backend/extract_chains.py (SYSTEM_PROMPT).

export interface ChainActor {
  id: string;
  name: string;
  type?: string;
}

export interface ChainEvidence {
  source: string;
  span: string;
}

export interface ChainNode {
  id: string;
  type: "task" | "gateway" | string;
  action?: string;
  label?: string;
  gateway_type?: string;
  actor?: string;
  recipient?: string;
  inputs?: string[];
  outputs?: string[];
  evidence?: ChainEvidence[];
}

export interface ChainFlow {
  from: string;
  to: string;
  condition?: string;
}

export interface ChainSource {
  id: string;
  type?: string;
  from?: string;
  to?: string;
  date?: string;
  subject?: string;
}

export interface ActionChain {
  id: string;
  title: string;
  summary?: string;
  prozess_wahrscheinlichkeit?: number;
  prozess_begruendung?: string;
  tags?: string[];
  actors?: ChainActor[];
  nodes: ChainNode[];
  flows?: ChainFlow[];
  sources?: ChainSource[];
}

// Eine Aktionskette, wie sie im UI gehandhabt wird: Dateiname (slug, eindeutig)
// + die eigentlichen Daten. Das "id"-Feld in den Daten ist nicht garantiert
// eindeutig (z.B. bei manuell angelegten oder kopierten Ketten).
export interface StoredChain {
  slug: string;
  data: ActionChain;
}

export function leereChain(): ActionChain {
  return {
    id: `chain_manuell_${Date.now()}`,
    title: "Neue Aktionskette",
    summary: "",
    tags: [],
    actors: [],
    nodes: [],
    flows: [],
    sources: [],
  };
}
