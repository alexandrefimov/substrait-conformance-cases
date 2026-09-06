#!/bin/bash
# Compiles and runs a Spark probe (needs JDK 17): bash probe/spark_run.sh <Class> [args]
set -e
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
# An unset JAVA17_HOME used to collapse this to /bin, so the guard checked /bin/java - which exists
# on most Linux boxes and is rarely a JDK 17. Spark then ran under whatever java that was and died in
# Subject.getSubject, and the column came out empty. With nothing resolved the path cannot exist, so
# the probe is skipped instead.
J17_HOME="${JAVA17_HOME:-$(/usr/libexec/java_home -v 17 2>/dev/null || true)}"
J17="${J17_HOME:-/nonexistent}/bin"
OUT="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}/sparkprobe"; mkdir -p "$OUT"
CP="$OUT:$(bash "$D/cp.sh" spark):$(bash "$D/cp.sh" core)"
CLASS="$1"; shift
"$J17/javac" -nowarn -cp "$CP" -d "$OUT" "$D/$CLASS.java"
"$J17/java" --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED \
  --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED \
  -cp "$CP" "$CLASS" "$@" 2>/dev/null | grep -vE "^WARNING|SLF4J|log4j|^[0-9]{2}/"
