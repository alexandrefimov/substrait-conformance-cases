#!/bin/bash
# Retakes the substrait-python column from scratch and compares it with the saved one.
#
#   bash probe/replay_python.sh
#
# Everything else in this repository is measured on one workstation and saved; CI only reads the
# result files against each other. This is the one participant whose environment is a pip install,
# so it is also the one column a machine that is not mine can produce from nothing and check. It
# proves one column out of nine - not the sweep - and that is still the difference between a saved
# number and a reproduced one.
#
# The version comes from versions.env, like every other participant: pinning it here as well would
# be a second place to forget.
set -uo pipefail
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$PROBE/.." && pwd)"
cd "$ROOT"
# shellcheck source=versions.env
. "$PROBE/versions.env"

SAVED="results/PYTHON.txt"
[ -s "$SAVED" ] || { echo "FAILED: no $SAVED to compare against" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Installed by setup.sh rather than by a pip line of its own: substrait-python needs the antlr
# runtime and the packaged extensions beside it, and a second copy of that list here would be one
# more thing to keep in step.
echo "== substrait-python $SUBSTRAIT_PYTHON_VERSION into a fresh environment"
SETUP_ONLY=substrait-python bash "$PROBE/setup.sh" "$WORK" > "$WORK/setup.log" 2>&1
# The venv is the thing this needs, so that is what is checked. setup.sh reports on every piece of
# the environment, and treating its exit code as the answer made this fail wherever another piece -
# the validator, which wants cargo - was absent, even though nothing here asks for that piece.
[ -x "$WORK/pysub/bin/python" ] || {
  echo "FAILED: setup.sh built no venv at $WORK/pysub" >&2; tail -8 "$WORK/setup.log" >&2; exit 1; }

# The saved column was taken over the virtual-table variant of the corpus, as reverify.sh does; over
# the canonical corpus substrait-python would answer about named tables it cannot resolve, and the
# comparison would be against a different measurement.
echo "== the corpus through infer_plan_schema"
SUBSTRAIT_PYTHON_ENV="$WORK/pysub" bash "$PROBE/python_all.sh" \
  "$ROOT/derived-schema-virtual-tables" > "$WORK/raw" 2>"$WORK/raw.err"
RC=$?
[ "$RC" -eq 0 ] || { echo "FAILED: the probe returned $RC: $(head -1 "$WORK/raw.err")" >&2; exit 1; }

python3 "$PROBE/normalize.py" "$WORK/raw" line \
  "PYTHON: replayed $(date +%Y-%m-%dT%H:%M), substrait $SUBSTRAIT_PYTHON_VERSION" > "$WORK/PYTHON.txt" \
  || { echo "FAILED: normalization did not yield a whole column" >&2; exit 1; }

# Headers differ by construction - the saved one names the day it was taken - so the answers are
# compared and the header is not. An empty comparison would pass silently, so the line count is
# checked first.
body() { sed '1,/^$/d' "$1" | grep -v '^$' | sort; }
NEW=$(body "$WORK/PYTHON.txt" | wc -l | tr -d ' ')
OLD=$(body "$SAVED" | wc -l | tr -d ' ')
if [ "$NEW" -lt 70 ] || [ "$NEW" != "$OLD" ]; then
  echo "FAILED: replayed $NEW answers against $OLD saved ones" >&2
  exit 1
fi
if ! diff <(body "$SAVED") <(body "$WORK/PYTHON.txt") > "$WORK/diff"; then
  echo "FAILED: the replayed column differs from $SAVED" >&2
  head -20 "$WORK/diff" >&2
  exit 1
fi
echo "ok      $NEW answers, identical to $SAVED (substrait $SUBSTRAIT_PYTHON_VERSION)"
