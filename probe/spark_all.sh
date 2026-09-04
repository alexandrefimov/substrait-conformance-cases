#!/bin/bash
# Runs every case through :spark (ToLogicalPlan). Needs JDK 17: on 18+ Hadoop dies in
# Subject.getSubject. The classpath comes from Gradle via probe/cp.sh.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
D="$(cd "$(dirname "$0")" && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
J17="${JAVA17_HOME:-$(/usr/libexec/java_home -v 17 2>/dev/null || true)}/bin"
OUT="${PROBE_OUT:-$SP/sparkprobe}"; mkdir -p "$OUT"
CASES="${1:-$ROOT/derived-schema}"
CP="$OUT:$(bash "$D/cp.sh" spark):$(bash "$D/cp.sh" core)"
"$J17/javac" -nowarn -cp "$CP" -d "$OUT" "$D/SparkSchemaOf.java" || exit 1
"$J17/java" --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED \
  --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED \
  -cp "$CP" SparkSchemaOf $(ls "$CASES"/*.json | grep -v manifest) 2>/dev/null |
  grep -vE "^WARNING|SLF4J|log4j|^$|^[0-9]{2}/"
