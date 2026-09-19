"""DataFusion (the pip package) as a producer, from the optimized logical plan - what
datafusion-substrait's own serializer::serialize_bytes hands to its producer.

    <venv with datafusion>/bin/python datafusion_shapes.py queries.tsv <out>
"""
import os, sys
import datafusion
from datafusion import SessionContext
from datafusion import substrait as ss

DDL = ["CREATE TABLE t_rn (c0 BIGINT NOT NULL, c1 BIGINT)",
       "CREATE TABLE t_nr (c0 BIGINT, c1 BIGINT NOT NULL)",
       "CREATE TABLE t_mix (c0 BIGINT NOT NULL, c1 VARCHAR NOT NULL, c2 BOOLEAN NOT NULL)",
       "CREATE TABLE t_ts (ts TIMESTAMP NOT NULL)",
       "CREATE TABLE t_dec (a DECIMAL(10,2) NOT NULL, b DECIMAL(5,1) NOT NULL)"]

queries, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
ctx = SessionContext()
for d in DDL:
    ctx.sql(d).collect()
for line in open(queries):
    name, sql = line.rstrip("\n").split("\t", 1)
    try:
        lp = ctx.sql(sql).optimized_logical_plan()
        plan = ss.Producer.to_substrait_plan(lp, ctx)
        open(os.path.join(out, name + ".pb"), "wb").write(plan.encode())
    except Exception as e:
        open(os.path.join(out, name + ".err"), "w").write(str(e).splitlines()[0] + "\n")
print("datafusion", datafusion.__version__)
