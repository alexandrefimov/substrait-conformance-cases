#!/bin/bash
# Runs every case through :spark (ToLogicalPlan). Needs JDK 17: on 18+ Hadoop dies in
# Subject.getSubject. The classpath comes from Gradle via probe/cp.sh.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
D="$(cd "$(dirname "$0")" && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
# An unset JAVA17_HOME used to collapse this to /bin, so the guard checked /bin/java - which exists
# on most Linux boxes and is rarely a JDK 17. Spark then ran under whatever java that was and died in
# Subject.getSubject, and the column came out empty. With nothing resolved the path cannot exist, so
# the probe is skipped instead.
J17_HOME="${JAVA17_HOME:-$(/usr/libexec/java_home -v 17 2>/dev/null || true)}"
J17="${J17_HOME:-/nonexistent}/bin"
OUT="${PROBE_OUT:-$SP/sparkprobe}"; mkdir -p "$OUT"
CASES="${1:-$ROOT/derived-schema}"
CP="$OUT:$(bash "$D/cp.sh" spark):$(bash "$D/cp.sh" core)"
# Spark 3.5 needs JDK 17: on 18 and later Hadoop dies in Subject.getSubject. Checked here rather
# than assumed, because the failure that follows names Subject and not the JDK.
VER="$("$J17/java" -version 2>&1 | head -1)"
case "$VER" in
  *\"17.*) ;;
  *) echo "the Spark probe needs JDK 17; $J17/java reports: $VER" >&2; exit 1 ;;
esac

"$J17/javac" -nowarn -cp "$CP" -d "$OUT" "$D/SparkSchemaOf.java" || exit 1

# Spark's own logging goes to stderr and so does the reason it failed, and sending both to /dev/null
# meant a run where Spark produced no column at all said nothing about why. The noise is filtered by
# pattern; whatever is left is printed, and a non-zero exit is passed on.
ERR="$(mktemp)"
"$J17/java" --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED \
  --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED \
  -cp "$CP" SparkSchemaOf $(ls "$CASES"/*.json | grep -v manifest) 2>"$ERR" |
  grep -vE "^WARNING|SLF4J|log4j|^$|^[0-9]{2}/"
RC="${PIPESTATUS[0]}"
grep -vE "^WARNING|SLF4J|log4j|^$|^[0-9]{2}/|^Using Spark|^Setting default log level" "$ERR" >&2 || true
rm -f "$ERR"
exit "$RC"
