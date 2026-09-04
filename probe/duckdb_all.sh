#!/bin/bash
# Runs every case through DuckDB. A separate process per case: the extension takes a signal on
# some plans, and one of those must not take the whole run with it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
CASES="${1:-$ROOT/derived-schema}"
PROBE="$(dirname "$0")/duckdb_one.py"
for f in "$CASES"/*.json; do
  n=$(basename "$f" .json); case "$n" in *manifest) continue;; esac
  printf "##### %s\n" "$n"
  out=$("$SP/venv/bin/python" "$PROBE" "$f" 2>&1); rc=$?
  if [ $rc -ne 0 ]; then echo "DUCKDB CRASH     signal/exit $rc"; else echo "$out"; fi
done
