#!/bin/bash
# Observes whether a consumer resolves the function a call names, and how.
#
#   bash probe/binding_matrix.sh [output directory]
#
# Run setup.sh and reverify.sh first, as for probe/lie_matrix.sh: the same nine participants and the
# same environments. Where the declaration swap asks whether the answer is the declared output type
# read back, this asks whether the call is bound at all. Only the name in
# Plan.extensions[].extensionFunction is rewritten - arguments, schema and declared output type are
# untouched - so a refusal cannot be about a shape the plan no longer has.
#
#   control    add becomes subtract and back, equal becomes not_equal, is_null becomes is_not_null:
#              same signature, same return. Every answer should be the answer to the original plan.
#              A refusal here means the rewrite itself is what the participant objects to, and that
#              participant's other two columns say nothing.
#   signature  add:dec_dec becomes add:str_str. A refusal means the argument types in the compound
#              name are checked; an unchanged answer means the short name is resolved against the
#              real arguments instead, which is a different way of binding rather than none.
#   unknown    the short name becomes one no extension file declares. A refusal means names are
#              resolved; an unchanged answer means the call is carried through unbound.
set -uo pipefail
FAILED=0
fail() { echo "FAILED: $*" >&2; FAILED=1; }
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$PROBE/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
CASES="$ROOT/derived-schema"

for mode in control signature unknown; do
  python3 "$PROBE/make_unbound_corpus.py" "$CASES" "$OUT/$mode" "$mode" || exit 1
done

# substrait-go and Acero read the binary protobuf, so each rewritten corpus needs its own, exactly
# as the declaration swap does.
if CP="$(bash "$PROBE/cp.sh" core 2>/dev/null)"; then
  javac -nowarn -cp "$CP" -d "$OUT/bincls" "$ROOT/gen/JsonToBin.java" 2>/dev/null || CP=""
fi
for mode in control signature unknown; do
  [ -n "$CP" ] && java -cp "$OUT/bincls:$CP" JsonToBin "$OUT/$mode" >/dev/null 2>&1
done
[ -n "$CP" ] || echo "no substrait-java classpath: substrait-go and Acero will be skipped"

run_one() { # <participant> <corpus> <raw path>
  case "$1" in
    JAVA)       bash "$PROBE/java_all.sh" "$2" > "$3" 2>&1 ;;
    PYTHON)     bash "$PROBE/python_all.sh" "$2" > "$3" 2>&1 ;;
    VALIDATOR)  bash "$PROBE/validator_all.sh" "$2" > "$3" 2>&1 ;;
    DUCKDB)     bash "$PROBE/duckdb_all.sh" "$2" > "$3" 2>&1 ;;
    GO)         bash "$PROBE/go_all.sh" "$2" > "$3" 2>&1 ;;
    ACERO)      bash "$PROBE/acero_all.sh" "$2" > "$3" 2>&1 ;;
    DATAFUSION) bash "$PROBE/datafusion_all.sh" "$2" > "$3" 2>&1 ;;
    ISTHMUS)    bash "$PROBE/isthmus_all.sh" "$2" > "$3" 2>&1 ;;
    SPARK)      bash "$PROBE/spark_all.sh" "$2" > "$3" 2>&1 ;;
  esac
}

for spec in "JAVA:line" "PYTHON:line" "VALIDATOR:block" "DUCKDB:block" "GO:block" \
            "ACERO:block" "DATAFUSION:block" "ISTHMUS:block" "SPARK:line"; do
  name="${spec%%:*}"; fmt="${spec##*:}"
  for variant in orig control signature unknown; do
    src="$CASES"; [ "$variant" != orig ] && src="$OUT/$variant"
    run_one "$name" "$src" "$OUT/$name.$variant.raw"
    python3 "$PROBE/normalize.py" "$OUT/$name.$variant.raw" "$fmt" "$name $variant" \
      > "$OUT/$name.$variant.txt" 2>/dev/null || rm -f "$OUT/$name.$variant.txt"
  done
done

python3 "$PROBE/binding_report.py" "$OUT" || fail "the report could not be built"
echo "raw runs and columns: $OUT"
[ "$FAILED" -eq 0 ] || { echo "RESULT: FAILED"; exit 1; }
echo "RESULT: the binding matrix was built"
