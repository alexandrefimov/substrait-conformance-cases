#!/bin/bash
# Compiles and runs an Isthmus probe:  bash probe/isthmus_run.sh <Class>|<path/Class.java> [args]
# The exit code is java's, not that of the grep at the end of the pipe (see PIPESTATUS).
set -e -o pipefail
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
OUT="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}/javaprobe"; mkdir -p "$OUT"
CP="$(bash "$D/cp.sh" isthmus)"
# A probe here is named by its class; one elsewhere (producers/) by the path of its source.
SRC="$D/$1.java"; case "$1" in *.java) SRC="$1" ;; esac
CLASS="$(basename "$1" .java)"; shift
javac -nowarn -cp "$CP" -d "$OUT" "$SRC"
java -cp "$OUT:$CP" "$CLASS" "$@" 2>&1 | grep -vE "SLF4J|^WARNING"
