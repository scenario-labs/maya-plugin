#!/usr/bin/env bash
# Scripted checks in a real Maya GUI session (spec 13, layer 3). 0 CU.
# Opens Maya windows on screen: run it from an interactive session, never from a background agent.
# Maya runs with a throwaway prefs folder copied from your Maya 2027 prefs; your own prefs are never written.
# Usage: tools/test_maya_gui.sh [stage...]   stages: install generate restart oauth (default: install restart)
#        generate runs one live generation with a cheap image model: it spends a few CU.
#        oauth opens your browser and waits up to 5 minutes for you to approve the sign-in.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAYA_BIN="${MAYA_BIN:-/Applications/Autodesk/maya2027/Maya.app/Contents/bin/maya}"
OUT="${SCENARIO_GUI_OUT:-$ROOT/tests/reports/tmp/gui-$(date +%Y%m%d-%H%M%S)}"
APP_DIR="${SCENARIO_GUI_APP_DIR:-$OUT/maya_app_dir}"
mkdir -p "$OUT"
if [ ! -d "$APP_DIR" ]; then
  mkdir -p "$APP_DIR"
  USER_PREFS="$HOME/Library/Preferences/Autodesk/maya/2027"
  if [ -d "$USER_PREFS" ]; then cp -R "$USER_PREFS" "$APP_DIR/2027"; fi
fi
STAGES="${*:-install restart}"
for STAGE in $STAGES; do
  echo "== Maya GUI stage: $STAGE (a Maya window opens, runs the checks and closes by itself)"
  SCENARIO_GUI_STAGE="$STAGE" SCENARIO_GUI_OUT="$OUT" SCENARIO_GUI_REPO="$ROOT" MAYA_APP_DIR="$APP_DIR" MAYA_DISABLE_CER=1 \
    "$MAYA_BIN" -command "python(\"import runpy, os; runpy.run_path(os.path.join(os.environ['SCENARIO_GUI_REPO'], 'tests', 'gui', 'gui_checks.py'))\")" \
    > "$OUT/maya_$STAGE.log" 2>&1 &
  PID=$!
  LIMIT=300; case "$STAGE" in oauth|generate) LIMIT=600 ;; esac
  for _ in $(seq 1 "$LIMIT"); do
    if ! kill -0 "$PID" 2>/dev/null; then break; fi
    sleep 1
  done
  QUIT_OK=1
  if kill -0 "$PID" 2>/dev/null; then
    QUIT_OK=0
    echo "   Maya still running after ${LIMIT}s: asking it to quit"
    kill -TERM "$PID" 2>/dev/null || true
    sleep 10
  fi
  if [ -f "$OUT/results_$STAGE.json" ]; then
    python3 -c "import json,sys; p=sys.argv[1]; r=json.load(open(p)); r['checks'].append({'name': 'Maya quit by itself', 'ok': sys.argv[2] == '1', 'detail': '' if sys.argv[2] == '1' else 'stopped by the runner; see quit_' + r['stage'] + '.txt'}); json.dump(r, open(p, 'w'), indent=1)" "$OUT/results_$STAGE.json" "$QUIT_OK"
    python3 -c "import json,sys; r=json.load(open(sys.argv[1])); [print('   ' + ('PASS' if c['ok'] else 'FAIL') + '  ' + c['name'] + ('  (' + c['detail'] + ')' if c['detail'] and not c['ok'] else '')) for c in r['checks']]; [print('   modal: ' + repr(m['title']) + ' answered ' + repr(m['answered'])) for m in r['modals']]" "$OUT/results_$STAGE.json"
  else
    echo "   no results for $STAGE (see $OUT/maya_$STAGE.log)"
  fi
done
echo "Output: $OUT"
