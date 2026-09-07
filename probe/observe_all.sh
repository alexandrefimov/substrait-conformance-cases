#!/bin/bash
# Retakes results/ISTHMUS-OBSERVE.txt: what substrait-java's TypeObserver sees while Isthmus
# converts each case, per case.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> bash probe/observe_all.sh > results/ISTHMUS-OBSERVE.txt
#
# This measurement sits outside the matrix - it compares a declared type with what Calcite derives
# for the same expression, rather than a final schema with an expectation - and it used to be taken
# by running ObserveOf by hand. Kept here so the file has a command behind it like every other.
set -uo pipefail
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$PROBE/.." && pwd)"
SJ="${SUBSTRAIT_JAVA_DIR:-}"
[ -n "$SJ" ] || { echo "set SUBSTRAIT_JAVA_DIR to a substrait-java checkout" >&2; exit 1; }
REV="$(git -C "$SJ" rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo "Isthmus/Calcite: declared against derived, $(date +%Y-%m-%d), substrait-java $REV."
echo "Command: SUBSTRAIT_JAVA_DIR=<checkout> bash probe/observe_all.sh, which runs probe/ObserveOf.java"
echo "The observer is attached through ConverterProvider.builder().typeObserver(...)."
echo

# Compiled once, then one JVM per case. Handing the whole corpus to a single JVM looks cheaper and
# is wrong: Isthmus throws on the cases it cannot convert - the mark and single joins, the
# precisions Calcite has no type for - and the first of them ends the run, taking every case after
# it with it. A case that Isthmus refuses has no observation to report and is simply absent here.
OUT="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}/javaprobe"
mkdir -p "$OUT"
CP="$(bash "$PROBE/cp.sh" isthmus)" || { echo "could not resolve the Isthmus classpath" >&2; exit 1; }
javac -nowarn -cp "$CP" -d "$OUT" "$PROBE/ObserveOf.java" \
  || { echo "ObserveOf.java did not compile" >&2; exit 1; }

RAN=0
for c in "$ROOT"/derived-schema/*.json; do
  case "$(basename "$c")" in manifest.json) continue;; esac
  java -cp "$OUT:$CP" ObserveOf "$c" 2>/dev/null | grep -vE "SLF4J|^WARNING" && RAN=$((RAN + 1))
done
# A run where nothing converted at all would otherwise leave a file with a header and no rows,
# which reads like a measurement rather than a broken classpath.
[ "$RAN" -gt 20 ] || { echo "only $RAN cases produced observations; that is a broken probe" >&2; exit 1; }
