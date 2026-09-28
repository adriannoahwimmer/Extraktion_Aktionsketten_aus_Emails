export default function WahrscheinlichkeitBadge({ wert }: { wert?: number }) {
  if (wert === undefined || wert === null) {
    return (
      <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
        unbekannt
      </span>
    );
  }

  const farbe =
    wert >= 0.6
      ? "bg-green-100 text-green-800"
      : wert >= 0.3
      ? "bg-yellow-100 text-yellow-800"
      : "bg-red-100 text-red-800";

  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${farbe}`}>
      {(wert * 100).toFixed(0)}% Prozess
    </span>
  );
}
