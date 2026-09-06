#!/bin/bash
# Runs every case through substrait-validator, from a venv holding a package built from main:
# see probe/README.md (needs cargo and protoc, python >= 3.10, protobuf runtime 7.x).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
VAL="${SUBSTRAIT_VALIDATOR_ENV:-$SP/val}"
CASES="${1:-$ROOT/derived-schema}"
PROBE="$(dirname "$0")/validator_one.py"
[ -x "$VAL/bin/python" ] || { echo "no validator venv: $VAL"; exit 1; }
for f in "$CASES"/*.json; do
  n=$(basename "$f" .json); case "$n" in *manifest) continue;; esac
  printf "##### %s\n" "$n"
  "$VAL/bin/python" "$PROBE" "$f" 2>&1 || echo "VALIDATOR CRASH"
done
