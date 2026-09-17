#!/bin/bash
# Observes output-schema sensitivity to changed function output_type declarations.
#
#   bash probe/lie_matrix.sh [output directory]
#
# Run setup.sh and reverify.sh first: they prepare the environments, gen/classpath.txt and SchemaOf.
# All nine column participants are asked. A participant whose environment is not up is skipped with
# a line naming it, not silently dropped and not a failure of the run: a machine without cargo still
# measures the other eight. Gluten is outside this, as it is outside reverify.sh - its column is
# taken in a cluster by hand.
#
#   follows      the output changed and matched the script's type-swap pattern
#   changed      the output changed without matching that pattern
#   held         the output did not change; this says nothing about types absent from that output
#   NOTICED      the modified plan errors where the original does not; the cause needs inspection
#   both fail    neither plan produced a comparable schema
#
# These categories describe final outputs, not expression-level inference or validation. In
# particular a join predicate's declared type can be copied while the join's output schema holds.
set -uo pipefail
FAILED=0
fail() { echo "FAILED: $*" >&2; FAILED=1; }
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$PROBE/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
OUT="${1:-$(mktemp -d)}"
CASES="$ROOT/derived-schema"
LIED="$OUT/lied"

python3 "$PROBE/make_lied_corpus.py" "$CASES" "$LIED" >/dev/null || exit 1
echo "swapped corpus: $LIED ($(ls "$LIED"/*.json | wc -l | tr -d ' ') cases)"

# substrait-go and Acero read the binary protobuf, not the JSON, and make_lied_corpus.py writes only
# JSON. Without this step those two answer "read: no such file" on every swapped case, which the
# table would report as no answer - a participant that looks unmeasured rather than one that was
# never given the corpus. This is why the matrix covered four participants and not nine.
if CP="$(bash "$PROBE/cp.sh" core 2>/dev/null)"; then
  javac -nowarn -cp "$CP" -d "$OUT/bincls" "$ROOT/gen/JsonToBin.java" 2>/dev/null \
    && java -cp "$OUT/bincls:$CP" JsonToBin "$LIED" >/dev/null 2>&1 \
    && echo "swapped binaries: $(ls "$LIED"/*.bin 2>/dev/null | wc -l | tr -d ' ')" \
    || echo "no swapped binaries: substrait-go and Acero will be skipped"
else
  echo "no substrait-java classpath: substrait-go and Acero will be skipped"
fi

declare -a NAMES=() FMTS=()
add() { NAMES+=("$1"); FMTS+=("$2"); }

# The format is the one reverify.sh writes each column with: one line per case, or a block per case
# that normalize.py reduces to one. Getting it wrong yields a column that is not whole, which is
# caught below rather than quietly mis-parsed.
for spec in "JAVA:line" "PYTHON:line" "VALIDATOR:block" "DUCKDB:block" "GO:block" \
            "ACERO:block" "DATAFUSION:block" "ISTHMUS:block" "SPARK:line"; do
  add "${spec%%:*}" "${spec##*:}"
done
declare -a SKIPPED=()

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"; fmt="${FMTS[$i]}"
  for variant in orig lied; do
    src=$CASES; [ "$variant" = lied ] && src=$LIED
    raw="$OUT/$name.$variant.raw"
    case "$name" in
      JAVA)      bash "$PROBE/java_all.sh" "$src" > "$raw" 2>&1 ;;
      PYTHON)    bash "$PROBE/python_all.sh" "$src" > "$raw" 2>&1 ;;
      VALIDATOR) bash "$PROBE/validator_all.sh" "$src" > "$raw" 2>&1 ;;
      DUCKDB)    bash "$PROBE/duckdb_all.sh" "$src" > "$raw" 2>&1 ;;
      GO)        bash "$PROBE/go_all.sh" "$src" > "$raw" 2>&1 ;;
      ACERO)     bash "$PROBE/acero_all.sh" "$src" > "$raw" 2>&1 ;;
      DATAFUSION) bash "$PROBE/datafusion_all.sh" "$src" > "$raw" 2>&1 ;;
      ISTHMUS)   bash "$PROBE/isthmus_all.sh" "$src" > "$raw" 2>&1 ;;
      SPARK)     bash "$PROBE/spark_all.sh" "$src" > "$raw" 2>&1 ;;
    esac
    python3 "$PROBE/normalize.py" "$raw" "$fmt" "$name $variant" > "$OUT/$name.$variant.txt" 2>/dev/null \
      || { SKIPPED+=("$name/$variant"); rm -f "$OUT/$name.$variant.txt"; }
  done
done

# A participant is in the table only with both halves: one half alone compares nothing. Skipping is
# reported by name, because a quietly missing column reads like a participant that held.
declare -a KEPT=() KEPT_FMT=()
for i in "${!NAMES[@]}"; do
  n="${NAMES[$i]}"
  if [ -s "$OUT/$n.orig.txt" ] && [ -s "$OUT/$n.lied.txt" ]; then
    KEPT+=("$n"); KEPT_FMT+=("${FMTS[$i]}")
  else
    echo "skipped: $n (its environment did not yield a whole column on both corpora)"
  fi
done
NAMES=("${KEPT[@]}"); FMTS=("${KEPT_FMT[@]}")
[ "${#NAMES[@]}" -gt 0 ] || fail "no participant produced a column on both corpora"

python3 - "$OUT" "${NAMES[@]}" <<'PY'
import io, os, sys
out, names = sys.argv[1], sys.argv[2:]

def col(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in io.open(path, encoding="utf-8"):
        k, _, v = line.rstrip().partition(" ")
        if k and v.strip():
            d[k] = v.strip()
    return d

def refused(v):
    return v.startswith(("ERROR", "— ")) or v in ("", "—")

# The swap made by make_lied_corpus.py: decimal -> dec(20,2), i64 -> i32, i32 -> i64. "follows"
# means the answer matched that swap, not merely that it changed: without this check any reaction
# to the swap counted as copying the declaration.
def follows(before, after):
    if before == after:
        return False
    marks = (("20", "2"), )
    low = after.lower()
    if "decimal" in before.lower() or "dec(" in before.lower() or "decimal" in low:
        return any(p in low and sc in low for p, sc in marks)
    if "i64" in before.lower() or "bigint" in before.lower():
        return "i32" in low or "int32" in low or "integer" in low
    if "i32" in before.lower():
        return "i64" in low or "int64" in low or "bigint" in low
    return False

data = {n: (col("%s/%s.orig.txt" % (out, n)), col("%s/%s.lied.txt" % (out, n))) for n in names}
cases = sorted(set().union(*[set(o) for o, _ in data.values()]) if data else [])
# Only the cases the swap actually touched: the rest measure nothing.
lied_dir = os.path.join(out, "lied")
touched = {os.path.basename(f)[:-5] for f in os.listdir(lied_dir) if f.endswith(".json")}

print()
print("%-34s" % "case" + "".join("%-20s" % n for n in names))
for c in sorted(x for x in cases if x in touched):
    row = "%-34s" % c
    for n in names:
        o, l = data[n][0].get(c), data[n][1].get(c)
        if o is None or l is None:            verdict = "no answer"
        elif refused(o) and refused(l):       verdict = "both fail"
        elif refused(l) and not refused(o):   verdict = "NOTICED"
        elif o == l:                          verdict = "held"
        elif follows(o, l):                   verdict = "follows"
        else:                                 verdict = "changed"
        row += "%-20s" % verdict
    print(row)
PY
echo
echo "raw runs and columns: $OUT"
[ "$FAILED" -eq 0 ] || { echo "RESULT: FAILED - the swap matrix cannot be trusted"; exit 1; }
echo "RESULT: the swap matrix was built over ${#NAMES[@]} participants"
