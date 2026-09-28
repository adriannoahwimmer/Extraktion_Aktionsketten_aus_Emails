// Erstellt mit Unterstuetzung von Claude Code (Anthropic).

// Zeigt prozess_wahrscheinlichkeit als farbiges Badge. Der Wert misst, wie viel
// klar erkennbares prozedurales Wissen eine Kette enthaelt; die Schwellen
// entsprechen den Stufen im Extraktions-Prompt (niedrig < 0.4 <= mittel < 0.7 <= hoch).
export default function WahrscheinlichkeitBadge({ wert }: { wert?: number }) {
  if (wert === undefined || wert === null) {
    return (
      <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
        unbewertet
      </span>
    );
  }

  const farbe =
    wert >= 0.7
      ? "bg-green-100 text-green-800"
      : wert >= 0.4
      ? "bg-yellow-100 text-yellow-800"
      : "bg-red-100 text-red-800";

  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${farbe}`}
      title="Menge und Klarheit des prozeduralen Wissens (Selbsteinschaetzung des LLM)"
    >
      {(wert * 100).toFixed(0)}% Prozesswissen
    </span>
  );
}
