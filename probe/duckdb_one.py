"""One case through DuckDB. A separate process per case: the extension can die on a signal."""
import argparse, pathlib
import duckdb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("plan", type=pathlib.Path)
parser.add_argument("--load-only", action="store_true", help="load the installed extension without installing")
parser.add_argument("--describe", action="store_true", help="report versions and bound column types without executing the plan")
args = parser.parse_args()

con = duckdb.connect()
if args.load_only:
    con.execute("LOAD substrait")
else:
    try:
        con.execute("INSTALL substrait"); con.execute("LOAD substrait")
    except Exception:
        con.execute("INSTALL substrait FROM community"); con.execute("LOAD substrait")
if args.describe:
    print("DUCKDB VERSION", con.execute("SELECT version()").fetchone()[0])
    print("SUBSTRAIT EXTENSION", con.execute(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'"
    ).fetchone()[0])
con.execute("CREATE TABLE foo (a BIGINT NOT NULL, b BIGINT NOT NULL, c VARCHAR NOT NULL)")
con.execute("CREATE TABLE SRC1 (INTCOL INTEGER, CHARCOL VARCHAR)")
con.execute("CREATE TABLE t_mix (c0 BIGINT NOT NULL, c1 VARCHAR NOT NULL, c2 BOOLEAN NOT NULL)")
con.execute("INSERT INTO t_mix VALUES (10, 'x', true)")
con.execute("CREATE TABLE t_dec (c0 DECIMAL(10,2) NOT NULL, c1 DECIMAL(5,1) NOT NULL, c2 DECIMAL(38,10) NOT NULL, c3 DECIMAL(38,10) NOT NULL)")
con.execute("INSERT INTO t_dec VALUES (1.00, 3.0, 9999999999999999999999999999.9999999999, 9999999999999999999999999999.9999999999)")
con.execute("CREATE TABLE t_str (c0 VARCHAR NOT NULL, c1 VARCHAR NOT NULL, c2 BLOB NOT NULL, c3 VARCHAR NOT NULL)")
con.execute("INSERT INTO t_str VALUES ('abc', 'de', '\\x01'::BLOB, 'z')")
con.execute("CREATE TABLE t_avg (c0 BIGINT NOT NULL, c1 BIGINT NOT NULL)")
con.execute("INSERT INTO t_avg VALUES (1, 10), (2, 20)")
con.execute("CREATE TABLE t_rn (c0 BIGINT NOT NULL, c1 BIGINT)")
con.execute("CREATE TABLE t_nr (c0 BIGINT, c1 BIGINT NOT NULL)")
con.execute("CREATE TABLE s1 (c0 BIGINT NOT NULL, c1 BIGINT NOT NULL, c2 BIGINT NOT NULL, c3 BIGINT NOT NULL, c4 BIGINT, c5 BIGINT, c6 BIGINT, c7 BIGINT)")
con.execute("CREATE TABLE s2 (c0 BIGINT NOT NULL, c1 BIGINT NOT NULL, c2 BIGINT, c3 BIGINT, c4 BIGINT NOT NULL, c5 BIGINT NOT NULL, c6 BIGINT, c7 BIGINT)")
con.execute("CREATE TABLE s3 (c0 BIGINT NOT NULL, c1 BIGINT, c2 BIGINT NOT NULL, c3 BIGINT, c4 BIGINT NOT NULL, c5 BIGINT, c6 BIGINT NOT NULL, c7 BIGINT)")
con.execute("CREATE TABLE t_xnull (c0 BIGINT)")

try:
    text = args.plan.read_text()
    if args.describe:
        description = con.execute(
            "DESCRIBE SELECT * FROM from_substrait_json(?)", [text]
        ).fetchall()
        print("DUCKDB BOUND     [%s]" % ", ".join("%s:%s" % (d[0], d[1]) for d in description))
    else:
        cur = con.execute("SELECT * FROM from_substrait_json(?)", [text])
        cols = [(d[0], str(d[1])) for d in cur.description]
        rows = cur.fetchall()
        print("DUCKDB ACCEPTED  [%s]" % ", ".join("%s:%s" % c for c in cols))
        if rows:
            print("DUCKDB ROW       %r" % (rows[0],))
        if rows and len(cols) == 1:
            vals = sorted(r[0] for r in rows)
            print("DUCKDB ROWS      %s" % (vals if len(vals) <= 30 else vals[:30] + ["..."],))
except Exception as e:
    print("DUCKDB REJECTED  %s: %s" % (type(e).__name__, str(e).replace("\n", " ")[:150]))
