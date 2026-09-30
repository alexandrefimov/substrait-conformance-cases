"""DuckDB as a producer, through its substrait extension's get_substrait.

    <probe-env>/venv/bin/python producers/duckdb_producer.py <tables.sql> <queries.tsv> <out>

Writes <out>/<query>.pb, or <out>/<query>.err with the first line of the refusal, and prints the
DuckDB and extension versions last.
"""
import os
import sys

import duckdb

tables, queries, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
con = duckdb.connect()
con.execute("LOAD substrait")
for statement in open(tables).read().splitlines():
    con.execute(statement)
for line in open(queries):
    if line.startswith("#") or not line.strip():
        continue
    name, sql = line.rstrip("\n").split("\t")[:2]
    try:
        blob = con.execute("CALL get_substrait(?)", [sql]).fetchone()[0]
        open(os.path.join(out, name + ".pb"), "wb").write(blob)
    except Exception as e:
        open(os.path.join(out, name + ".err"), "w").write(str(e).splitlines()[0] + "\n")
print("duckdb", duckdb.__version__,
      con.execute("SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'").fetchone()[0])
