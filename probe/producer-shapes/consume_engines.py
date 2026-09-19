"""Runs plans through DuckDB (from_substrait) or DataFusion (pip, from_substrait_plan) over tables
holding rows, and prints the schema and rows each returns.

    <venv>/bin/python consume_engines.py duckdb|datafusion <plan.pb> ...
"""
import sys
ROWS = {"t_rn": ["(1, 10)", "(2, NULL)", "(3, 30)"], "t_nr": ["(NULL, 1)", "(2, 2)", "(3, 30)"],
        "t_mix": ["(10, 'x', true)", "(20, 'y', false)"]}
DDL = {"t_rn": "c0 BIGINT NOT NULL, c1 BIGINT", "t_nr": "c0 BIGINT, c1 BIGINT NOT NULL",
       "t_mix": "c0 BIGINT NOT NULL, c1 VARCHAR NOT NULL, c2 BOOLEAN NOT NULL"}
eng = sys.argv[1]
if eng == "duckdb":
    import duckdb
    con = duckdb.connect(); con.execute("LOAD substrait")
    con.execute("CREATE TABLE t_ts (ts TIMESTAMP_NS NOT NULL)")
    con.execute("INSERT INTO t_ts VALUES (TIMESTAMP_NS '2020-01-01 00:00:00.123456789'), (TIMESTAMP_NS '2020-01-01 00:00:00.123456790')")
    for t, d in DDL.items():
        con.execute("CREATE TABLE %s (%s)" % (t, d)); con.execute("INSERT INTO %s VALUES %s" % (t, ",".join(ROWS[t])))
    def run(blob):
        cur = con.execute("SELECT * FROM from_substrait(?)", [blob])
        return [(d[0], str(d[1])) for d in cur.description], sorted(cur.fetchall(), key=repr)
else:
    from datafusion import SessionContext
    from datafusion import substrait as ss
    ctx = SessionContext()
    ctx.sql("CREATE TABLE t_ts (ts TIMESTAMP NOT NULL)").collect()
    ctx.sql("INSERT INTO t_ts VALUES (TIMESTAMP '2020-01-01 00:00:00.123456789'), (TIMESTAMP '2020-01-01 00:00:00.123456790')").collect()
    for t, d in DDL.items():
        ctx.sql("CREATE TABLE %s (%s)" % (t, d)).collect(); ctx.sql("INSERT INTO %s VALUES %s" % (t, ",".join(ROWS[t]))).collect()
        # Isthmus writes Calcite's upper-cased identifiers; DataFusion resolves names case-sensitively.
        up = ", ".join('"%s" %s' % (c.split()[0].upper(), " ".join(c.split()[1:])) for c in d.split(", "))
        ctx.sql('CREATE TABLE "%s" (%s)' % (t.upper(), up)).collect()
        ctx.sql('INSERT INTO "%s" VALUES %s' % (t.upper(), ",".join(ROWS[t]))).collect()
    def run(blob):
        plan = ss.Serde.deserialize_bytes(blob)
        lp = ss.Consumer.from_substrait_plan(ctx, plan)
        df = ctx.create_dataframe_from_logical_plan(lp)
        tbl = df.to_arrow_table()
        return ["%s:%s%s" % (f.name, f.type, "" if f.nullable else "!") for f in tbl.schema], sorted([{k: str(v) for k, v in r.items()} for r in tbl.to_pylist()], key=repr)
for path in sys.argv[2:]:
    try:
        cols, rows = run(open(path, "rb").read())
        print("%-32s %s rows=%s" % ("/".join(path.split("/")[-2:]), cols, rows))
    except Exception as e:
        print("%-32s REJECTED %s" % ("/".join(path.split("/")[-2:]), " ".join(str(e).split())[:160]))
