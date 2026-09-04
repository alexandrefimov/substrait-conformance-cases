#!/bin/bash
# Checks that the virtual-table variant of the corpus derives the same schemas as the canonical one.
set -e
D="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
CACHE="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}"; OUT="$CACHE/javaprobe"; mkdir -p "$OUT"
CP="$(bash "$D/cp.sh" core)"
python3 "$D/to_virtual_tables.py" "$ROOT/derived-schema" "$CACHE/vt-check" | tail -1
javac -nowarn -cp "$CP" -d "$OUT" "$D/SchemaOf.java"
run() { java -cp "$OUT:$CP" SchemaOf $(ls "$1"/*.json | grep -v manifest) 2>/dev/null | grep -v WARNING; }
run "$ROOT/derived-schema" > "$CACHE/eq_named.txt"
run "$CACHE/vt-check"      > "$CACHE/eq_vt.txt"
python3 - "$CACHE/eq_named.txt" "$CACHE/eq_vt.txt" <<'PY'
import io, sys
def load(p):
    d = {}
    for line in io.open(p, encoding="utf-8"):
        k, _, v = line.rstrip().partition(" ")
        if k: d[k] = v.strip()
    return d
a, b = load(sys.argv[1]), load(sys.argv[2])
diff = [k for k in sorted(b) if k in a and a[k] != b[k]]
print("cases compared:", len(set(a) & set(b)), "| schemas differing:", len(diff))
for k in diff[:5]: print("  ", k)
raise SystemExit(1 if diff else 0)
PY
