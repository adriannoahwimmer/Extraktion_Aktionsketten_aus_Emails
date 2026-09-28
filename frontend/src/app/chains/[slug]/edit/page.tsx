"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { use } from "react";
import Link from "next/link";
import ChainForm from "@/components/ChainForm";
import type { ActionChain } from "@/lib/types";

export default function ChainBearbeiten({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const router = useRouter();
  const [initial, setInitial] = useState<ActionChain | null>(null);
  const [nichtGefunden, setNichtGefunden] = useState(false);

  useEffect(() => {
    fetch(`/api/chains/${slug}`).then(async (res) => {
      if (!res.ok) {
        setNichtGefunden(true);
        return;
      }
      const { data } = await res.json();
      setInitial(data);
    });
  }, [slug]);

  if (nichtGefunden) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-8">
        <p className="text-gray-500">Aktionskette nicht gefunden.</p>
        <Link href="/" className="text-indigo-600 hover:underline">
          Zurück zur Übersicht
        </Link>
      </main>
    );
  }

  if (!initial) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-8">
        <p className="text-gray-500">Lade...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <Link href={`/chains/${slug}`} className="text-sm text-indigo-600 hover:underline">
        ← Zurück zur Ansicht
      </Link>
      <h1 className="mt-4 mb-6 text-2xl font-semibold text-gray-900">Aktionskette bearbeiten</h1>

      <ChainForm
        initial={initial}
        submitLabel="Speichern"
        onSubmit={async (data) => {
          const res = await fetch(`/api/chains/${slug}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          });
          if (res.ok) {
            router.push(`/chains/${slug}`);
          } else {
            const { fehler } = await res.json();
            alert(fehler ?? "Speichern fehlgeschlagen.");
          }
        }}
      />
    </main>
  );
}
