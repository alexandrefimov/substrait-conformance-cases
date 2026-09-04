#!/bin/bash
# Runs every case through substrait-go. One process per case: the library panics on some plans.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
CASES="${1:-$ROOT/derived-schema}"
BIN="$SP/gosub9/probe_go9"   # substrait-go main (v9 alpha); v4/v8 kept around to compare versions
for f in "$CASES"/*.bin; do
  n=$(basename "$f" .bin)
  printf "##### %s\n" "$n"
  out=$("$BIN" "$f" 2>&1); rc=$?
  if [ $rc -ne 0 ]; then
    first=$(echo "$out" | head -1 | cut -c1-120)
    echo "SUBSTRAITGO CRASH     $first"
  else
    echo "$out" | head -1
  fi
done
