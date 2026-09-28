import { NextRequest, NextResponse } from "next/server";
import { erzeugeBatchId, hatApiKey, starteBatch } from "@/lib/batches";

// Postfach hochladen -> Batch anlegen -> Pipeline starten.
// Body: multipart/form-data mit einem oder mehreren "files" und optional "modell".
export async function POST(request: NextRequest) {
  if (!(await hatApiKey())) {
    return NextResponse.json(
      {
        fehler:
          "OPENAI_API_KEY nicht gefunden. Trage den KIT-Key einmalig in die Datei " +
          "'.env' im Projektordner ein (Zeile: OPENAI_API_KEY=dein-key) oder setze " +
          'ihn im Terminal:  $env:OPENAI_API_KEY = "<KIT-Key>"',
      },
      { status: 503 }
    );
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json(
      { fehler: "Erwarte multipart/form-data." },
      { status: 400 }
    );
  }

  const eintraege = form.getAll("files").filter((f): f is File => f instanceof File);
  if (eintraege.length === 0) {
    return NextResponse.json(
      { fehler: "Keine Datei hochgeladen (Feld 'files')." },
      { status: 400 }
    );
  }

  const erlaubt = /\.(eml|mbox|pst|zip)$/i;
  const abgelehnt = eintraege.filter((f) => f.name && !erlaubt.test(f.name));
  if (abgelehnt.length > 0) {
    return NextResponse.json(
      {
        fehler:
          "Nicht unterstuetztes Format: " +
          abgelehnt.map((f) => f.name).join(", ") +
          ". Erlaubt: .eml, .mbox, .pst, .zip",
      },
      { status: 400 }
    );
  }

  const modellFeld = form.get("modell");
  const modell = typeof modellFeld === "string" && modellFeld ? modellFeld : undefined;

  const dateien = await Promise.all(
    eintraege.map(async (f) => ({
      name: f.name || "upload.bin",
      buffer: Buffer.from(await f.arrayBuffer()),
    }))
  );

  const batchId = erzeugeBatchId();
  try {
    await starteBatch(batchId, dateien, modell);
  } catch (e) {
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Start fehlgeschlagen." },
      { status: 500 }
    );
  }

  return NextResponse.json({ batch_id: batchId }, { status: 201 });
}
