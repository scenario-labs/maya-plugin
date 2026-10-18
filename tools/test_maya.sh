#!/usr/bin/env bash
# Maya-in-the-loop tests, headless in mayapy (no window, no crash reporter, 0 CU).
# Usage: tools/test_maya.sh [pytest args]   MAYAPY=/path/to/mayapy to pick a Maya.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "$(uname -s)" in
  Darwin) DEFAULT_MAYAPY=/Applications/Autodesk/maya2027/Maya.app/Contents/bin/mayapy ;;
  Linux) DEFAULT_MAYAPY=/usr/autodesk/maya2027/bin/mayapy ;;
  *) DEFAULT_MAYAPY="C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" ;;
esac
MAYAPY="${MAYAPY:-$DEFAULT_MAYAPY}"
SITE="$ROOT/.cache/mayapy-site"
if [ ! -d "$SITE/pytest" ]; then
  "$MAYAPY" -m pip install --quiet --disable-pip-version-check --target "$SITE" pytest
fi
# A throwaway Maya prefs folder in the system temp dir: tests never touch the user's prefs.
APP_DIR="$(mktemp -d -t scenario-maya-tests)"
cd "$ROOT"
PYTHONPATH="$SITE" MAYA_DISABLE_CER=1 MAYA_SKIP_USERSETUP_PY=1 MAYA_APP_DIR="$APP_DIR" \
  "$MAYAPY" -m pytest -q -p no:cacheprovider tests/maya "$@"
