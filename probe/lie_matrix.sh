#!/bin/bash
# Who notices when the declared type is swapped for a false one.
#
#   bash probe/lie_matrix.sh [output directory]
#
# Builds the swapped corpus (make_lied_corpus.py), runs the original and the swapped corpus
# through the participants, and prints one of these words per case:
#
#   follows      the answer matched the swapped type - the declaration was copied, nothing derived
#   changed      the answer changed, but not into the swapped type - it derives, but looks at the
#                declaration on the way
#   held         the answer did not change - the type was derived independently of the declaration
#   NOTICED      the swapped plan errors where the original does not - the only honest outcome
#   both fail    the case is unsupported either way
#
# The participants here are the ones whose probes run locally from a single command: substrait-java,
# substrait-python, the validator and DuckDB. The saved LIE.txt was taken over a different set
# (Spark and Gluten in place of DuckDB), so it does not line up with this run row for row; the rows
# they share agree.
# On ctas_keeps_declared_schema the validator derives no type in either run. The hand-written column
# called that "held" rather than "no type derived"; the second wording is the true one, because there
# is nothing there to compare.
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

declare -a NAMES=() FMTS=()
add() { NAMES+=("$1"); FMTS+=("$2"); }

for spec in "JAVA:line" "PYTHON:line" "VALIDATOR:block" "DUCKDB:block"; do
  add "${spec%%:*}" "${spec##*:}"
done

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"; fmt="${FMTS[$i]}"
  for variant in orig lied; do
    src=$CASES; [ "$variant" = lied ] && src=$LIED
    raw="$OUT/$name.$variant.raw"
    case "$name" in
      JAVA)      java -cp "$ROOT/gen/out:$(cat "$ROOT/gen/classpath.txt")" \
                   SchemaOf $(ls "$src"/*.json | grep -v manifest) > "$raw" 2>/dev/null ;;
      PYTHON)    bash "$PROBE/python_all.sh" "$src" > "$raw" 2>&1 ;;
      VALIDATOR) bash "$PROBE/validator_all.sh" "$src" > "$raw" 2>&1 ;;
      DUCKDB)    bash "$PROBE/duckdb_all.sh" "$src" > "$raw" 2>&1 ;;
    esac
    python3 "$PROBE/normalize.py" "$raw" "$fmt" "$name $variant" > "$OUT/$name.$variant.txt" 2>/dev/null \
      || fail "$name/$variant: normalization did not yield a whole column"
  done
done

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
