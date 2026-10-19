#!/usr/bin/env bash
# Captures the README media in a real Maya GUI session (tests/gui/showcase.py), then builds the GIFs and videos.
# Opens a Maya window: run it from an interactive session, never from a background agent.
# Spends one cheap image and one 3D generation (Meshy 7.1 at a game polycount) in SCENARIO_SHOW_PROJECT.
# Usage: tools/readme_media.sh <signed-in MAYA_APP_DIR>   (a throwaway copy is used; the source is never written)
#        SCENARIO_SHOW_STAGE=turntable tools/readme_media.sh <MAYA_APP_DIR of a capture>   (turntable only, 0 CU)
#        tools/readme_media.sh --build <output folder>   (rebuild the media from an earlier capture)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAYA_BIN="${MAYA_BIN:-/Applications/Autodesk/maya2027/Maya.app/Contents/bin/maya}"
if [ "${1:-}" = "--build" ]; then
  python3 "$ROOT/tools/readme_media_build.py" "$2" "$ROOT/docs/media"
  exit 0
fi
SOURCE="${1:?usage: tools/readme_media.sh <signed-in MAYA_APP_DIR>}"
OUT="${SCENARIO_SHOW_OUT:-$ROOT/tests/reports/tmp/showcase-$(date +%Y%m%d-%H%M%S)}"
APP_DIR="$OUT/maya_app_dir"
mkdir -p "$APP_DIR"
# Session locks belong to the Maya that wrote them; the ledger is copied through SQLite so a live one stays consistent.
rsync -a --exclude 'scenario/locks' --exclude 'scenario/ledger.sqlite3*' "$SOURCE/" "$APP_DIR/"
if [ -f "$SOURCE/scenario/ledger.sqlite3" ]; then
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" \
    "$SOURCE/scenario/ledger.sqlite3" "$APP_DIR/scenario/ledger.sqlite3"
fi
echo "== Maya opens, records the session and quits by itself (about 10 minutes)"
SCENARIO_SHOW_OUT="$OUT" SCENARIO_SHOW_REPO="$ROOT" MAYA_APP_DIR="$APP_DIR" MAYA_DISABLE_CER=1 \
  "$MAYA_BIN" -command "python(\"import runpy, os; runpy.run_path(os.path.join(os.environ['SCENARIO_SHOW_REPO'], 'tests', 'gui', 'showcase.py'))\")" \
  > "$OUT/maya.log" 2>&1 &
PID=$!
for _ in $(seq 1 1800); do
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
  echo "   Maya still running after 30 minutes: asking it to quit"
  kill -TERM "$PID" 2>/dev/null || true
  sleep 10
fi
if [ -f "$OUT/showcase.json" ]; then
  python3 -c "import json,sys; r=json.load(open(sys.argv[1])); [print('   ' + ('PASS' if c['ok'] else 'FAIL') + '  ' + c['name'] + ('  (' + c['detail'] + ')' if c['detail'] else '')) for c in r['checks']]; print('   frames:', len(r['frames']))" "$OUT/showcase.json"
  python3 "$ROOT/tools/readme_media_build.py" "$OUT" "$ROOT/docs/media"
else
  echo "   no showcase.json (see $OUT/maya.log)"
fi
echo "Output: $OUT"
