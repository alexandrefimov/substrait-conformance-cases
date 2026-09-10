#!/bin/bash
# The whole relations corpus through substrait-java, as a column.
#
#     SUBSTRAIT_JAVA_DIR=<checkout> bash probe/relations/java_all.sh > results/relations/JAVA.txt
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
OUT="$SP/reljava"
SJ="${SUBSTRAIT_JAVA_DIR:-$SP/substrait-java}"

if [ ! -s "$OUT/cp.txt" ] || [ ! -s "$OUT/java_home.txt" ]; then
  echo "no substrait-java runner in $OUT - build it with probe/relations/setup.sh JAVA" >&2
  exit 1
fi
JH="$(cat "$OUT/java_home.txt")"
CP="$(cat "$OUT/cp.txt"):$OUT/out"

# Three things decide the answer and none of them is the other: the commit of substrait-java that
# derives the schema, the release of the Substrait protos it resolves - which is the release the
# cases were authored against, unlike substrait-go's - and the JDK it runs on.
sha="$(git -C "$SJ" rev-parse --short HEAD 2>/dev/null)"
protos="$(tr ':' '\n' <<< "$CP" | sed -n 's#.*/io\.substrait/protobuf/\([^/]*\)/.*#\1#p' | head -1)"
jdk="$("$JH/bin/java" -version 2>&1 | head -1 | sed 's/.*version "\([^"]*\)".*/\1/')"
rev="substrait-java ${sha:-revision unknown}, substrait protos ${protos:-unknown}, JDK ${jdk:-unknown}"

bash "$ROOT/probe/relations/drive.sh" JAVA "$rev" "$JH/bin/java" -cp "$CP" RelationCase
