#!/bin/bash
# Runs every case through substrait-python (infer_plan_schema).
# Environment: probe/setup.sh builds the venv; see probe/README.md.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
PY="${SUBSTRAIT_PYTHON_ENV:-$SP/pysub}"
CASES="${1:-$ROOT/derived-schema}"
PROBE="$(dirname "$0")/python_one.py"
[ -x "$PY/bin/python" ] || { echo "no substrait-python venv: $PY"; exit 1; }
for f in "$CASES"/*.json; do
  n=$(basename "$f" .json); case "$n" in *manifest) continue;; esac
  "$PY/bin/python" "$PROBE" "$f"
done
