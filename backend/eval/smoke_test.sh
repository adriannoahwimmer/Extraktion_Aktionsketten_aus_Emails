#!/usr/bin/env bash
# Erstellt mit Unterstuetzung von Claude Code (Anthropic).
#
# smoke_test.sh
# --------------------------------------------------
# Schritt 8 der Auswertung: prueft, ob das Projekt aus einem frischen Klon
# heraus laeuft - so, wie es ein Dritter nach der README einrichtet:
#   git clone -> python -m venv -> pip install -r requirements.txt
#   -> npm install + npm run build (frontend/) -> run_pipeline.py auf dem
#   Beispiel-Postfach (examples/beispiel_postfach.mbox).
# Jeder Schritt wird mit Exit-Code und Dauer protokolliert (log_<schritt>.txt).
# Der API-Key wird aus der .env dieses Projekts in den Klon kopiert und am Ende
# wieder geloescht. Der Pipeline-Lauf verursacht geringe API-Kosten.
#
# Aufruf (Git Bash oder Linux/macOS):
#   bash backend/eval/smoke_test.sh [zielordner]
# Umgebungsvariablen: REPO_URL (Standard: GitHub-Repo), PYTHON (Standard: python)

set -u
REPO_URL="${REPO_URL:-https://github.com/adriannoahwimmer/Extraktion_Aktionsketten_aus_Emails.git}"
PROJEKT="$(cd "$(dirname "$0")/../.." && pwd)"
ZIEL="${1:-$(mktemp -d)}"
PYTHON="${PYTHON:-python}"
BATCH="b$(date +%Y%m%d_%H%M%S)_smok"
FEHLER=0

schritt() {
  local name="$1"; shift
  local t0; t0=$(date +%s)
  "$@" > "$ZIEL/log_${name}.txt" 2>&1
  local rc=$?
  echo "SCHRITT $name: exit=$rc, $(( $(date +%s) - t0 )) s"
  if [ $rc -ne 0 ]; then FEHLER=1; tail -25 "$ZIEL/log_${name}.txt"; fi
  return $rc
}

mkdir -p "$ZIEL" && cd "$ZIEL" || exit 1
rm -rf repo
echo "Zielordner: $ZIEL - Start $(date '+%Y-%m-%d %H:%M:%S')"
schritt clone git clone "$REPO_URL" repo || exit 1
cd repo || exit 1
echo "Commit: $(git log --oneline -1)"

schritt venv "$PYTHON" -m venv .venv || exit 1
if [ -x .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe; else VPY=.venv/bin/python; fi
schritt pip "$VPY" -m pip install --disable-pip-version-check -r requirements.txt
schritt npm_install bash -c "cd frontend && npm install"
schritt npm_build bash -c "cd frontend && npm run build"

if [ -f "$PROJEKT/.env" ]; then
  cp "$PROJEKT/.env" .env
  mkdir -p "backend/batches/$BATCH/upload"
  cp examples/beispiel_postfach.mbox "backend/batches/$BATCH/upload/"
  schritt pipeline bash -c "cd backend && ../$VPY run_pipeline.py --batch-dir batches/$BATCH"
  echo "status.json:"; cat "backend/batches/$BATCH/status.json"; echo
  grep -E "Kette\(n\) erkannt|-> chain|FEHLER|Traceback" "backend/batches/$BATCH/pipeline.log"
  rm -f .env
else
  echo "Keine .env im Projekt gefunden - Pipeline-Lauf uebersprungen."
fi

echo "Warnungen:"
grep -hiE "npm warn|warning" "$ZIEL"/log_*.txt "backend/batches/$BATCH/pipeline.log" 2>/dev/null | sort -u | head -20
echo "Ende $(date '+%Y-%m-%d %H:%M:%S') - $( [ $FEHLER -eq 0 ] && echo 'alle Schritte erfolgreich' || echo 'mit Fehlern' )"
exit $FEHLER
