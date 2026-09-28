// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
import { NextRequest, NextResponse } from "next/server";
import { leseStatus } from "@/lib/batches";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const status = await leseStatus(id);
  if (!status) {
    return NextResponse.json({ fehler: "Batch nicht gefunden." }, { status: 404 });
  }
  return NextResponse.json(status);
}
