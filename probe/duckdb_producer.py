"""What DuckDB DECLARES as a producer, and whether it agrees with itself.

    <venv>/bin/python probe/duckdb_producer.py

Prints two things: the output_type a function call is declared with in the plan get_substrait_json
returns, and the result type taken directly against the result type after the round trip
get_substrait_json -> from_substrait_json. On addition, the round trip differs by exactly one digit
of precision.
"""
import argparse
import json
import duckdb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--load-only", action="store_true", help="use the installed extension")
parser.add_argument("--decimal-roundtrip", action="store_true", help="compare three additions and a read control")
parser.add_argument("--check", action="store_true", help="fail if the focused round-trip comparison differs")
args = parser.parse_args()
if args.check and not args.decimal_roundtrip:
    parser.error("--check requires --decimal-roundtrip")

con = duckdb.connect()
if args.load_only:
    con.execute("LOAD substrait")
else:
    try:
        con.execute("INSTALL substrait"); con.execute("LOAD substrait")
    except Exception:
        con.execute("INSTALL substrait FROM community"); con.execute("LOAD substrait")
con.execute("CREATE TABLE t (a DECIMAL(10,2) NOT NULL, b DECIMAL(5,1) NOT NULL, "
            "c DECIMAL(38,10) NOT NULL, d DECIMAL(38,10) NOT NULL, i BIGINT NOT NULL)")
con.execute("INSERT INTO t VALUES (1.00, 3.0, 1.0000000000, 2.0000000000, 7)")

def declared(plan):
    names = {str(e["extensionFunction"].get("functionAnchor", 0)): e["extensionFunction"]["name"]
             for e in plan.get("extensions", []) if "extensionFunction" in e}
    out = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("scalarFunction", "aggregateFunction") and isinstance(v, dict):
                    t = v.get("outputType", {}); kind = next(iter(t)) if t else "?"
                    spec = t.get(kind, {})
                    s = "dec(%s,%s)" % (spec.get("precision"), spec.get("scale")) if kind == "decimal" else kind
                    out.append("%s -> %s" % (names.get(str(v.get("functionReference", 0)), "?"), s))
                walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(plan)
    return out

if args.decimal_roundtrip:
    print(json.dumps({"duckdb": duckdb.__version__, "extension": con.execute(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'"
    ).fetchone()[0]}))
    mismatches = 0
    for expression in ["a", "a + b", "(a + b) + b", "((a + b) + b) + b"]:
        sql = "SELECT " + expression + " AS r FROM t"
        direct = con.execute("DESCRIBE " + sql).fetchone()[1]
        js = con.execute("CALL get_substrait_json(?)", [sql]).fetchone()[0]
        actual = con.execute("DESCRIBE SELECT * FROM from_substrait_json(?)", [js]).fetchone()[1]
        matches = direct == actual
        mismatches += not matches
        print(json.dumps({"expression": expression, "direct": direct, "roundtrip": actual,
                          "matches": matches, "declared": declared(json.loads(js))}))
    print(json.dumps({"cases": 4, "mismatches": mismatches}))
    raise SystemExit(1 if args.check and mismatches else 0)

print("%-24s %-18s %-18s %s" % ("expression", "direct", "round trip", "declared in the plan"))
for sql in ["SELECT a + b FROM t", "SELECT c + d FROM t", "SELECT c * d FROM t",
            "SELECT a / b FROM t", "SELECT avg(i) FROM t",
            "SELECT (a + b) + b FROM t", "SELECT ((a + b) + b) + b FROM t"]:
    direct = str(con.execute(sql).description[0][1])
    js = con.execute("CALL get_substrait_json(?)", [sql]).fetchone()[0]
    rt = str(con.execute("CALL from_substrait_json(?)", [js]).description[0][1])
    mark = "" if direct == rt else "  <-- disagrees with itself"
    print("%-24s %-18s %-18s %s%s" % (sql.replace("SELECT ", "").replace(" FROM t", ""),
                                      direct, rt, "; ".join(declared(json.loads(js))) or "(no calls)", mark))
