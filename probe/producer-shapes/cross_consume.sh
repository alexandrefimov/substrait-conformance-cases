#!/bin/bash
# Hands plans that producers wrote (run_all.sh) to the consumers, at the builds the columns use.
#
#   bash probe/producer-shapes/cross_consume.sh <producer>/<query> ...
#
# The plans are read from the directory run_all.sh wrote, DF_VENV is the same virtualenv, and a
# consumer that is not built is reported as skipped rather than silently left out.
set -u -o pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$D/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
PLANS="${PLANS:-$SP/producer-shapes}"
SEL=("$@")
[ ${#SEL[@]} -gt 0 ] || { echo "usage: cross_consume.sh <producer>/<query> ..." >&2; exit 2; }

echo "== substrait-go"
for s in "${SEL[@]}"; do printf "%-28s " "$s"; "$SP/gosub9/probe_go9" "$PLANS/$s.pb" 2>&1 | head -1; done
echo "== substrait-python"
for s in "${SEL[@]}"; do printf "%-28s " "$s"; "$SP/pysub/bin/python" -W ignore "$ROOT/probe/python_one.py" "$PLANS/$s.json" 2>&1 | tail -1; done
echo "== substrait-validator"
for s in "${SEL[@]}"; do printf "%-28s " "$s"; "${SUBSTRAIT_VALIDATOR_ENV:-$SP/val}/bin/python" -W ignore "$ROOT/probe/validator_one.py" "$PLANS/$s.json" 2>&1 | tr '\n' ' '; echo; done
echo "== substrait-java"
CP="$(bash "$ROOT/probe/cp.sh" core)" || exit 1
javac -nowarn -cp "$CP" -d "$SP/javaprobe" "$ROOT/probe/SchemaOfBin.java" || exit 1
( cd "$PLANS" && java -cp "$SP/javaprobe:$CP" SchemaOfBin $(for s in "${SEL[@]}"; do echo "$s.pb"; done) 2>/dev/null )
echo "== DuckDB, one process per plan: an unsupported operation can kill it"
for s in "${SEL[@]}"; do
  out=$("$SP/venv/bin/python" "$D/consume_engines.py" duckdb "$PLANS/$s.pb" 2>&1); rc=$?
  [ $rc -gt 128 ] && out="$(printf '%-32s CRASHED with signal %d' "$s.pb" $((rc - 128)))"
  echo "$out" | tail -1
done
if [ -n "${DF_VENV:-}" ]; then
  echo "== DataFusion"
  "$DF_VENV/bin/python" "$D/consume_engines.py" datafusion $(for s in "${SEL[@]}"; do echo "$PLANS/$s.pb"; done)
else
  echo "== DataFusion: DF_VENV unset, skipped" >&2
fi
