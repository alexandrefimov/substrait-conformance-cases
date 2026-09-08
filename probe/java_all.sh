#!/bin/bash
# Runs every case through substrait-java: the schema its own POJO conversion derives from the plan
# on disk. One JVM for the whole corpus, unlike the engines - nothing here dies in a way that would
# take the rest of the run with it - so the output is one line per case, not blocks.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> bash probe/java_all.sh [corpus]
#
# The checkout defaults to the one probe/setup.sh clones under the probe environment, so a machine
# that has never seen substrait-java needs nothing but the setup.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
CACHE="${PROBE_CACHE:-$SP}"
CASES="${1:-$ROOT/derived-schema}"
D="$(cd "$(dirname "$0")" && pwd)"
OUT="$CACHE/javaprobe"; mkdir -p "$OUT"
CP="$(bash "$D/cp.sh" core)" || exit 1
javac -nowarn -cp "$CP" -d "$OUT" "$D/SchemaOf.java" || exit 1
# stderr is dropped: substrait-java logs through SLF4J, whose "no provider" notice would otherwise
# be read as part of an answer. A case it cannot convert prints its own ERROR line on stdout.
java -cp "$OUT:$CP" SchemaOf $(ls "$CASES"/*.json | grep -v manifest) 2>/dev/null
