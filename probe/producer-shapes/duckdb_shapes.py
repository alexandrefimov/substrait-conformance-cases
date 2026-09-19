"""DuckDB as a producer: writes <out>/<name>.pb for every query in queries.tsv, or <name>.err.

    <probe-env>/venv/bin/python duckdb_shapes.py queries.tsv <out>
"""
import os, sys
import duckdb

DDL = ["CREATE TABLE t_rn (c0 BIGINT NOT NULL, c1 BIGINT)",
       "CREATE TABLE t_nr (c0 BIGINT, c1 BIGINT NOT NULL)",
       "CREATE TABLE t_mix (c0 BIGINT NOT NULL, c1 VARCHAR NOT NULL, c2 BOOLEAN NOT NULL)",
       "CREATE TABLE t_ts (ts TIMESTAMP_NS NOT NULL)",
       "CREATE TABLE t_dec (a DECIMAL(10,2) NOT NULL, b DECIMAL(5,1) NOT NULL)"]

queries, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
con = duckdb.connect()
con.execute("LOAD substrait")
for d in DDL:
    con.execute(d)
# DuckDB optimizes with the statistics of the tables it holds, so a plan is only valid for data
# those statistics cover: over empty tables it proves a filter empty and writes an empty virtual
# table, and with rows that never join it replaces the join's input the same way. These are the
# rows consume_engines.py runs the plans against.
for t, row in [("t_rn", "(1, 10), (2, NULL), (3, 30)"), ("t_nr", "(NULL, 1), (2, 2), (3, 30)"),
               ("t_mix", "(10, 'x', true), (20, 'y', false)"),
               ("t_ts", "(TIMESTAMP_NS '2021-01-01 00:00:00.123456789')"), ("t_dec", "(1.00, 2.0)")]:
    con.execute("INSERT INTO %s VALUES %s" % (t, row))
for line in open(queries):
    name, sql = line.rstrip("\n").split("\t", 1)
    try:
        blob = con.execute("CALL get_substrait(?)", [sql]).fetchone()[0]
        open(os.path.join(out, name + ".pb"), "wb").write(blob)
    except Exception as e:
        open(os.path.join(out, name + ".err"), "w").write(str(e).splitlines()[0] + "\n")
print("duckdb", duckdb.__version__,
      con.execute("SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'").fetchone()[0])
