"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import ChainForm from "@/components/ChainForm";
import { leereChain } from "@/lib/types";

export default function ChainNeu() {
  const router = useRouter();

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <Link href="/" className="text-sm text-indigo-600 hover:underline">
        ← Zurück zur Übersicht
      </Link>
      <h1 className="mt-4 mb-6 text-2xl font-semibold text-gray-900">
        Neue Aktionskette anlegen
      </h1>

      <ChainForm
        initial={leereChain()}
        submitLabel="Anlegen"
        onSubmit={async (data) => {
          const res = await fetch("/api/chains", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          });
          if (res.ok) {
            const { slug } = await res.json();
            router.push(`/chains/${slug}`);
          } else {
            const { fehler } = await res.json();
            alert(fehler ?? "Anlegen fehlgeschlagen.");
          }
        }}
      />
    </main>
  );
}
