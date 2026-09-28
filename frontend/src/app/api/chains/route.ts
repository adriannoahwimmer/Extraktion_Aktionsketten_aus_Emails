// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
import { NextRequest, NextResponse } from "next/server";
import { listeChains, erstelleChain } from "@/lib/chains";
import type { ActionChain } from "@/lib/types";

export async function GET() {
  const ketten = await listeChains();
  return NextResponse.json(ketten);
}

export async function POST(request: NextRequest) {
  const data = (await request.json()) as ActionChain;

  if (!data.title || !Array.isArray(data.nodes)) {
    return NextResponse.json(
      { fehler: "title und nodes (Array) sind Pflichtfelder." },
      { status: 400 }
    );
  }

  const slug = await erstelleChain(data);
  return NextResponse.json({ slug }, { status: 201 });
}
