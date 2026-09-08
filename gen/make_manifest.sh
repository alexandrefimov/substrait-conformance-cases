#!/bin/bash
# Rebuilds derived-schema/manifest.json from the generators themselves.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> bash gen/make_manifest.sh [output file]
#
# Each generator is run into a directory of its own so that the manifest can say which one writes a
# case, and its output is kept so that the one line it prints per case becomes that case's note.
# Nothing here is written by hand except gen/sources.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$ROOT/derived-schema/manifest.json}"
[ -s "$ROOT/gen/classpath.txt" ] || bash "$ROOT/gen/make_classpath.sh" >&2
CP="$(cat "$ROOT/gen/classpath.txt")"
GENS="GenCases GenDisputed GenSetOps GenJoins GenNarrowing GenEmit GenProjection GenSetData GenStringLen GenPhase GenDecimal GenControl GenWindow GenExpand"

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
rm -rf "$ROOT/gen/out"; mkdir -p "$ROOT/gen/out"
SRCS=""; for g in $GENS JsonToBin Tables; do SRCS="$SRCS $ROOT/gen/$g.java"; done
javac -nowarn -cp "$CP" -d "$ROOT/gen/out" $SRCS
for g in $GENS; do
  mkdir -p "$OUT/$g"
  java -cp "$ROOT/gen/out:$CP" "$g" "$OUT/$g" > "$OUT/$g.out" 2>/dev/null
done
python3 "$ROOT/gen/make_manifest.py" "$OUT" > "$DEST"
echo "$DEST: $(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$DEST") entries"
