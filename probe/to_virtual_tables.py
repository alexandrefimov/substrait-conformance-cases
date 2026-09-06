"""The variant of the corpus that uses virtual tables instead of named ones - for Gluten.

    python3 probe/to_virtual_tables.py <input dir> <output dir> [--row-for-empty]

--row-for-empty gives one synthetic row to the tables that canonically hold no data. It is needed
only for Gluten: Velox derives a virtual table's schema from its rows, and with zero rows it returns
ROW<>. Without the flag the corpus is honest and measures exactly that; with the flag it measures
everything else.

Gluten (SubstraitToVeloxPlan) reads only virtual_table and local_files out of a ReadRel; named_table
does not appear in its code at all. So the leaf is rewritten into a virtual table holding one row of
literals shaped by the declared schema (the fields of Nested.Struct are Expressions, hence each
literal is wrapped in {"literal": ...}). The encoding is `expressions` - the current one, the values
field having been reserved since spec 0.98 - and that is the one Gluten reads (expressions_size()).

The canonical corpus stays on named tables: Acero does not work with virtual ones at all, and a
divergence in derivation would then be indistinguishable from a lack of support.

BOUNDARY. The row is single and synthetic (i64=1, string="x", decimal=1 unscaled), so this variant
is good for comparing SCHEMAS: types, arity and column order. For the cases about ROWS (setdata_*,
avg) the data here is not the data in the engines' tables, and the results will differ.

Checked on 2026-09-03, when the corpus held 75 cases: the schemas substrait-java derived matched the
canonical corpus on all of them except virtual_table_literal_type_differs_from_schema, which is
contradictory by design and fails the same way in both. probe/vt_equivalence.sh re-runs that check.
"""
import base64, decimal, json, os, shutil, sys
from decimal import Decimal

# The data of the canonical tables - the same the engine probes create (duckdb_one.py and the
# rest). Without it the cases about rows (avg, count) would count something other than what the
# other participants measured.
DATA = {
    "t_avg": [[1, 10], [2, 20]],
    "t_dec": [[Decimal("1.00"), Decimal("3.0"),
               Decimal("9999999999999999999999999999.9999999999"),
               Decimal("9999999999999999999999999999.9999999999")]],
    "t_mix": [[10, "x", True]],
    "t_str": [["abc", "de", b"\x01", "z"]],
}

def literal(t, value=None):
    """A literal shaped by the declared type. value=None means the column has no data."""
    (kind, spec), = t.items()
    nullable = spec.get("nullability") == "NULLABILITY_NULLABLE"
    if kind == "i64":     lit = {"i64": str(value if value is not None else 1)}
    elif kind == "i32":   lit = {"i32": int(value) if value is not None else 1}
    elif kind == "bool":  lit = {"boolean": bool(value) if value is not None else True}
    elif kind == "string": lit = {"string": str(value) if value is not None else "x"}
    elif kind == "varchar":
        v = str(value) if value is not None else "x"
        lit = {"varChar": {"value": v[:spec["length"]], "length": spec["length"]}}
    elif kind == "fixedChar":
        n = spec["length"]
        v = (str(value) if value is not None else "x")
        lit = {"fixedChar": v.ljust(n)[:n]}             # exactly `length` chars, space-padded as CHAR is
    elif kind == "fixedBinary":
        n = spec["length"]
        b = value if isinstance(value, (bytes, bytearray)) else b"\x01"
        b = (bytes(b) + b"\x01" * n)[:n]                # exactly `length` bytes
        lit = {"fixedBinary": base64.b64encode(b).decode()}
    elif kind == "decimal":
        # 16 bytes, little-endian, two's complement
        if value is None:
            unscaled = 1
        else:
            # the default precision of 28 digits would round the dec(38,10) maximum to 39 digits
            with decimal.localcontext() as ctx:
                ctx.prec = 80
                unscaled = int(Decimal(str(value)).scaleb(spec["scale"]))
        lit = {"decimal": {"value": base64.b64encode(unscaled.to_bytes(16, "little", signed=True)).decode(),
                           "precision": spec["precision"], "scale": spec["scale"]}}
    else:
        raise SystemExit("no literal for type " + kind)
    lit["nullable"] = nullable
    return lit

def convert(node):
    if isinstance(node, dict):
        r = node.get("read")
        if isinstance(r, dict) and "namedTable" in r:
            types = r["baseSchema"]["struct"]["types"]
            table = r["namedTable"]["names"][-1]
            # For tables with no data the engine probes create empty tables, so there are no rows
            # here either. A synthetic row would distort the cases about counting (narrowing_count
            # returned 1 instead of 0).
            rows = DATA.get(table, [[None] * len(types)] if row_for_empty else [])
            r.pop("namedTable")
            r["virtualTable"] = {"expressions": [
                {"fields": [{"literal": literal(t, row[i] if i < len(row) else None)}
                            for i, t in enumerate(types)]} for row in rows]}
        for v in node.values(): convert(v)
    elif isinstance(node, list):
        for v in node: convert(v)

src, dst = sys.argv[1], sys.argv[2]
row_for_empty = "--row-for-empty" in sys.argv[3:]
if os.path.isdir(dst):
    shutil.rmtree(dst)          # otherwise stale files survive a regeneration
os.makedirs(dst, exist_ok=True)
n = 0
for name in sorted(os.listdir(src)):
    if not name.endswith(".json") or "manifest" in name: continue
    d = json.load(open(os.path.join(src, name)))
    convert(d)
    with open(os.path.join(dst, name), "w") as out:
        json.dump(d, out, indent=1)
        out.write("\n")   # json.dump writes none, and a file without one reads as unfinished
    n += 1
print("cases rewritten:", n)
