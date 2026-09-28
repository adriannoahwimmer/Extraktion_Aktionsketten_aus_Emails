// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
import { NextRequest, NextResponse } from "next/server";
import { holeChain, speichereChain, loescheChain } from "@/lib/chains";
import type { ActionChain } from "@/lib/types";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const kette = await holeChain(slug);
  if (!kette) {
    return NextResponse.json({ fehler: "Nicht gefunden." }, { status: 404 });
  }
  return NextResponse.json(kette);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const data = (await request.json()) as ActionChain;

  if (!data.title || !Array.isArray(data.nodes)) {
    return NextResponse.json(
      { fehler: "title und nodes (Array) sind Pflichtfelder." },
      { status: 400 }
    );
  }

  await speichereChain(slug, data);
  return NextResponse.json({ ok: true });
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const geloescht = await loescheChain(slug);
  if (!geloescht) {
    return NextResponse.json({ fehler: "Nicht gefunden." }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
