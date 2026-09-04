#!/bin/bash
# Compiles and runs an Isthmus probe:  bash probe/isthmus_run.sh <Class> [args]
# The exit code is java's, not that of the grep at the end of the pipe (see PIPESTATUS).
set -e -o pipefail
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
OUT="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}/javaprobe"; mkdir -p "$OUT"
CP="$(bash "$D/cp.sh" isthmus)"
CLASS="$1"; shift
javac -nowarn -cp "$CP" -d "$OUT" "$D/$CLASS.java"
java -cp "$OUT:$CP" "$CLASS" "$@" 2>&1 | grep -vE "SLF4J|^WARNING"
