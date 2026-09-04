#!/bin/bash
# Runs every case through Acero. One process per case, as for DuckDB.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
CASES="${1:-$ROOT/derived-schema}"
PROBE="$(dirname "$0")/acero_one.py"
for f in "$CASES"/*.bin; do
  n=$(basename "$f" .bin)
  printf "##### %s\n" "$n"
  out=$("$SP/venv/bin/python" "$PROBE" "$f" 2>&1); rc=$?
  if [ $rc -ne 0 ]; then echo "ACERO CRASH      signal/exit $rc"; else echo "$out"; fi
done
