import Link from "next/link";
import { notFound } from "next/navigation";
import { holeChain } from "@/lib/chains";
import ChainFlowDiagram from "@/components/ChainFlowDiagram";
import WahrscheinlichkeitBadge from "@/components/WahrscheinlichkeitBadge";

export default async function ChainAnsicht({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const kette = await holeChain(slug);
  if (!kette) notFound();

  const { data } = kette;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/" className="text-sm text-indigo-600 hover:underline">
        ← Zurück zur Übersicht
      </Link>

      <div className="mt-4 mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">{data.title}</h1>
          <p className="mt-1 text-gray-600">{data.summary}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <WahrscheinlichkeitBadge wert={data.prozess_wahrscheinlichkeit} />
          <div className="flex gap-2 text-sm">
            <Link
              href={`/chains/${slug}/edit`}
              className="rounded-md border border-gray-300 px-3 py-1.5 hover:bg-gray-50"
            >
              Bearbeiten
            </Link>
          </div>
        </div>
      </div>

      {data.prozess_begruendung && (
        <p className="mb-6 rounded-md bg-gray-50 p-3 text-sm text-gray-600 italic">
          {data.prozess_begruendung}
        </p>
      )}

      {(data.tags ?? []).length > 0 && (
        <div className="mb-6 flex flex-wrap gap-1.5">
          {data.tags!.map((t) => (
            <span key={t} className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {t}
            </span>
          ))}
        </div>
      )}

      <h2 className="mb-2 text-lg font-medium text-gray-900">Ablauf</h2>
      <ChainFlowDiagram nodes={data.nodes} flows={data.flows ?? []} />

      {(data.actors ?? []).length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-lg font-medium text-gray-900">Akteure</h2>
          <div className="flex flex-wrap gap-2">
            {data.actors!.map((a) => (
              <div
                key={a.id}
                className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm"
              >
                <span className="font-medium">{a.name}</span>
                {a.type && <span className="ml-1 text-xs text-gray-400">({a.type})</span>}
              </div>
            ))}
          </div>
        </section>
      )}

      {(data.sources ?? []).length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-lg font-medium text-gray-900">Quellen &amp; Belege</h2>
          <div className="space-y-2">
            {data.sources!.map((s) => {
              const belege = data.nodes.flatMap((n) =>
                (n.evidence ?? [])
                  .filter((e) => e.source === s.id)
                  .map((e) => ({ span: e.span, action: n.action ?? n.label }))
              );
              return (
                <div key={s.id} className="rounded-md border border-gray-200 bg-white p-3 text-sm">
                  <div className="text-xs text-gray-400">
                    {s.date} · {s.from} → {s.to}
                  </div>
                  <div className="font-medium">{s.subject || "(kein Betreff)"}</div>
                  {belege.map((b, i) => (
                    <blockquote
                      key={i}
                      className="mt-2 border-l-2 border-indigo-200 pl-2 text-gray-600 italic"
                    >
                      &quot;{b.span}&quot;
                      <span className="ml-1 not-italic text-gray-400">— {b.action}</span>
                    </blockquote>
                  ))}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </main>
  );
}
