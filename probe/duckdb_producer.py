"""What DuckDB DECLARES as a producer, and whether it agrees with itself.

    <venv>/bin/python probe/duckdb_producer.py

Prints two things: the output_type a function call is declared with in the plan get_substrait_json
returns, and the result type taken directly against the result type after the round trip
get_substrait_json -> from_substrait_json. On addition, the round trip differs by exactly one digit
of precision.
"""
import json
import duckdb

con = duckdb.connect()
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
