#!/bin/bash
# Compiles and runs a Spark probe (needs JDK 17): bash probe/spark_run.sh <Class> [args]
set -e
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
J17="${JAVA17_HOME:-$(/usr/libexec/java_home -v 17 2>/dev/null || true)}/bin"
OUT="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}/sparkprobe"; mkdir -p "$OUT"
CP="$OUT:$(bash "$D/cp.sh" spark):$(bash "$D/cp.sh" core)"
CLASS="$1"; shift
"$J17/javac" -nowarn -cp "$CP" -d "$OUT" "$D/$CLASS.java"
"$J17/java" --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED \
  --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED \
  -cp "$CP" "$CLASS" "$@" 2>/dev/null | grep -vE "^WARNING|SLF4J|log4j|^[0-9]{2}/"
