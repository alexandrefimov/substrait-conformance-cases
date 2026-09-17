#!/usr/bin/env python3
"""Run the decimal arithmetic cases of substrait-io/substrait#1213 on Spark and
Hive in Docker and print, per case, the type the Substrait formula derives, the
type the engine derived and the value it produced.

The cases are the ones the pull request asserts, plus a rounding group it does
not cover: its scale-reduction operands lose only zeros, so they pin the derived
type and say nothing about what happens to a digit that is dropped.

    python3 probe/decimal-rules/engines.py spark
    python3 probe/decimal-rules/engines.py hive
    python3 probe/decimal-rules/engines.py hive --stop
    SPARK_IMAGE=apache/spark:4.0.4 python3 probe/decimal-rules/engines.py spark

The expected column comes from rules.py, so a disagreement between the formula
and an engine is in the output rather than left to the reader; `differ` at the
end of a line marks one. Every case must produce a row: a run that lost one
fails rather than print a short table that reads like a complete one.

Spark runs one container per invocation and answers with the analyzed schema of
the expression. Hive needs a HiveServer2, which the script starts, reuses while
it is up and leaves running; `--stop` removes it. Hive prints no type for an
expression, so each case becomes a view and is read back with `describe`.

Overflow is where the two engines differ by configuration rather than by
formula, so Spark is asked twice: `spark.sql.ansi.enabled` at its default and
off. Raising and returning NULL are the ERROR and SILENT values of the
`overflow` option of the Substrait function.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules                                                    # noqa: E402

def pinned(name):
    """probe/versions.env is where this repository keeps participant versions,
    so the images live there and not in a second copy here."""
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "versions.env")
    for line in open(env):
        line = line.split("#", 1)[0].strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("%s is not pinned in probe/versions.env" % name)


SPARK_IMAGE = os.environ.get("SPARK_IMAGE") or pinned("DECIMAL_SPARK_IMAGE")
HIVE_IMAGE = os.environ.get("HIVE_IMAGE") or pinned("DECIMAL_HIVE_IMAGE")
TRINO_IMAGE = os.environ.get("TRINO_IMAGE") or pinned("DECIMAL_TRINO_IMAGE")
MYSQL_IMAGE = os.environ.get("MYSQL_IMAGE") or pinned("DECIMAL_MYSQL_IMAGE")
CLICKHOUSE_IMAGE = os.environ.get("CLICKHOUSE_IMAGE") or pinned("DECIMAL_CLICKHOUSE_IMAGE")
HIVE_CONTAINER = os.environ.get("HIVE_CONTAINER", "substrait-decimal-hive")
STARTUP_SECONDS = int(os.environ.get("DECIMAL_STARTUP_SECONDS", "300"))

D38 = "DECIMAL(38,10)"
BIG = "99999999999999999999999999999999999999"
NEAR = "9999999999999999999999999999.9999999999"

# name, SQL expression, and the operands as the formula sees them, so that
# rules.substrait can derive what the case should return.
CASES = [
    ("basic/add", "CAST('1.00' AS DECIMAL(10,2)) + CAST('2.0' AS DECIMAL(5,1))",
     ("add", 10, 2, 5, 1)),
    ("basic/subtract", "CAST('1.00' AS DECIMAL(10,2)) - CAST('2.0' AS DECIMAL(5,1))",
     ("subtract", 10, 2, 5, 1)),
    ("basic/multiply", "CAST('1.00' AS DECIMAL(10,2)) * CAST('2.0' AS DECIMAL(5,1))",
     ("multiply", 10, 2, 5, 1)),
    ("basic/divide", "CAST('1.00' AS DECIMAL(10,2)) / CAST('2.0' AS DECIMAL(5,1))",
     ("divide", 10, 2, 5, 1)),
    ("scale_reduction/add", "CAST('1.0000000000' AS %s) + CAST('2.0000000000' AS %s)" % (D38, D38),
     ("add", 38, 10, 38, 10)),
    ("scale_reduction/subtract", "CAST('3.0000000000' AS %s) - CAST('1.0000000000' AS %s)" % (D38, D38),
     ("subtract", 38, 10, 38, 10)),
    ("scale_reduction/multiply", "CAST('1.0000000000' AS %s) * CAST('2.0000000000' AS %s)" % (D38, D38),
     ("multiply", 38, 10, 38, 10)),
    ("scale_reduction/divide", "CAST('6.0000000000' AS %s) / CAST('2.0000000000' AS %s)" % (D38, D38),
     ("divide", 38, 10, 38, 10)),
    # Not in the pull request either: the basic divide case separates P2 from
    # S2 by four digits, this one by nine, and neither operand reaches the cap,
    # so an engine's answer says which form it uses rather than what it clamps.
    ("divide_rule/wide_divisor", "CAST('1.00' AS DECIMAL(10,2)) / CAST('123456789' AS DECIMAL(9,0))",
     ("divide", 10, 2, 9, 0)),
    ("null_values/add", "CAST(NULL AS DECIMAL(10,2)) + CAST('2.0' AS DECIMAL(5,1))",
     ("add", 10, 2, 5, 1)),
    ("null_values/divide", "CAST(NULL AS DECIMAL(10,2)) / CAST('2.0' AS DECIMAL(5,1))",
     ("divide", 10, 2, 5, 1)),
    ("overflow/add", "CAST('%s' AS DECIMAL(38,0)) + CAST('1.0000000000' AS %s)" % (BIG, D38),
     ("add", 38, 0, 38, 10)),
    ("overflow/subtract", "CAST('-%s' AS DECIMAL(38,0)) - CAST('1.0000000000' AS %s)" % (BIG, D38),
     ("subtract", 38, 0, 38, 10)),
    ("overflow/multiply", "CAST('%s' AS %s) * CAST('%s' AS %s)" % (NEAR, D38, NEAR, D38),
     ("multiply", 38, 10, 38, 10)),
    ("overflow/divide", "CAST('%s' AS DECIMAL(38,0)) / CAST('0.0000000001' AS %s)" % (BIG, D38),
     ("divide", 38, 0, 38, 10)),
    # Not in the pull request: a dropped digit that is not a zero, and the two
    # ties that separate rounding away from zero from rounding to even.
    ("rounding/add_up", "CAST('1.2345678906' AS %s) + CAST('0.0000000000' AS %s)" % (D38, D38),
     ("add", 38, 10, 38, 10)),
    ("rounding/add_tie", "CAST('1.2345678905' AS %s) + CAST('0.0000000000' AS %s)" % (D38, D38),
     ("add", 38, 10, 38, 10)),
    ("rounding/add_tie_even", "CAST('1.2345678915' AS %s) + CAST('0.0000000000' AS %s)" % (D38, D38),
     ("add", 38, 10, 38, 10)),
    ("rounding/add_tie_negative", "CAST('-1.2345678905' AS %s) + CAST('0.0000000000' AS %s)" % (D38, D38),
     ("add", 38, 10, 38, 10)),
    ("rounding/multiply", "CAST('1.2345678901' AS %s) * CAST('1.0000000000' AS %s)" % (D38, D38),
     ("multiply", 38, 10, 38, 10)),
    # multiply reduces to scale 6 in every engine whose type is bounded at 38,
    # so these two are the ties Trino also reaches; its add never reduces. The
    # digit before the tie is even, which is what separates rounding away from
    # zero from rounding to even: 1.234568|5 goes to 1.234569 or stays.
    ("rounding/multiply_tie", "CAST('1.2345685000' AS %s) * CAST('1.0000000000' AS %s)" % (D38, D38),
     ("multiply", 38, 10, 38, 10)),
    ("rounding/multiply_tie_negative", "CAST('-1.2345685000' AS %s) * CAST('1.0000000000' AS %s)" % (D38, D38),
     ("multiply", 38, 10, 38, 10)),
    ("rounding/divide", "CAST('2.0000000000' AS %s) / CAST('3.0000000000' AS %s)" % (D38, D38),
     ("divide", 38, 10, 38, 10)),
]

OVERFLOW = [name for name, _, _ in CASES if name.startswith("overflow/")]
ACTIVE = CASES          # the decimal family unless --overflow says otherwise
FAMILY = "decimal"


# The `overflow` option is declared on integer arithmetic as well, in
# functions_arithmetic.yaml and unsigned_integers.yaml, and saturation is far
# more plausible there than on decimals. Its three values name behaviours the
# specification never defines, so the question here is which of them an engine
# actually performs at a type boundary. The expressions differ per engine
# because fixed-width integer arithmetic is not written the same way twice.
OVERFLOW_CASES = [
    ("i8/add_max", {
        "spark": "CAST(127 AS TINYINT) + CAST(1 AS TINYINT)",
        "hive": "CAST(127 AS TINYINT) + CAST(1 AS TINYINT)",
        "trino": "CAST(127 AS TINYINT) + CAST(1 AS TINYINT)",
        "mysql": "CAST(127 AS SIGNED) + CAST(1 AS SIGNED)",
        "clickhouse": "toInt8(127) + toInt8(1)"}),
    ("i32/add_max", {
        "spark": "CAST(2147483647 AS INT) + CAST(1 AS INT)",
        "hive": "CAST(2147483647 AS INT) + CAST(1 AS INT)",
        "trino": "CAST(2147483647 AS INTEGER) + CAST(1 AS INTEGER)",
        "mysql": "CAST(2147483647 AS SIGNED) + CAST(1 AS SIGNED)",
        "clickhouse": "toInt32(2147483647) + toInt32(1)"}),
    ("i32/multiply_max", {
        "spark": "CAST(2147483647 AS INT) * CAST(2 AS INT)",
        "hive": "CAST(2147483647 AS INT) * CAST(2 AS INT)",
        "trino": "CAST(2147483647 AS INTEGER) * CAST(2 AS INTEGER)",
        "mysql": "CAST(2147483647 AS SIGNED) * CAST(2 AS SIGNED)",
        "clickhouse": "toInt32(2147483647) * toInt32(2)"}),
    ("i64/add_max", {
        "spark": "CAST(9223372036854775807 AS BIGINT) + CAST(1 AS BIGINT)",
        "hive": "CAST(9223372036854775807 AS BIGINT) + CAST(1 AS BIGINT)",
        "trino": "CAST(9223372036854775807 AS BIGINT) + CAST(1 AS BIGINT)",
        "mysql": "CAST(9223372036854775807 AS SIGNED) + CAST(1 AS SIGNED)",
        "clickhouse": "toInt64(9223372036854775807) + toInt64(1)"}),
    ("i64/subtract_min", {
        "spark": "CAST(-9223372036854775808 AS BIGINT) - CAST(1 AS BIGINT)",
        "hive": "CAST(-9223372036854775808 AS BIGINT) - CAST(1 AS BIGINT)",
        "trino": "CAST(-9223372036854775808 AS BIGINT) - CAST(1 AS BIGINT)",
        "mysql": "CAST(-9223372036854775808 AS SIGNED) - CAST(1 AS SIGNED)",
        "clickhouse": "toInt64(-9223372036854775808) - toInt64(1)"}),
    # Only MySQL and ClickHouse have an unsigned integer type at all, and
    # unsigned_integers.yaml declares the same option, so the boundary that
    # tests it is theirs. None means the engine has no such type.
    ("u64/add_max", {
        "spark": None, "hive": None, "trino": None,
        "mysql": "CAST(18446744073709551615 AS UNSIGNED) + CAST(1 AS UNSIGNED)",
        "clickhouse": "toUInt64(18446744073709551615) + toUInt64(1)"}),
]


def saturating_answer(name, value):
    """SATURATE would clamp to the boundary; say so where it happens."""
    limits = {"i8/add_max": "127", "i32/add_max": "2147483647",
              "i32/multiply_max": "2147483647", "i64/add_max": "9223372036854775807",
              "i64/subtract_min": "-9223372036854775808",
              "u64/add_max": "18446744073709551615"}
    return " SATURATE" if value.strip() == limits.get(name) else ""


def expected(name):
    """What the Substrait formula derives. The overflow family asks what an
    engine does at a type boundary, which no formula predicts, so it has none."""
    for case, _, operands in ACTIVE:
        if case == name:
            return "-" if operands is None else "decimal(%d,%d)" % rules.substrait(*operands)
    raise KeyError(name)


def norm(t):
    """decimal(11,2), DECIMAL(11, 2) and Decimal(11, 2) are the same answer
    spelled three ways; the comparison is about the numbers."""
    return re.sub(r"\s+", "", t).lower()


def run(cmd, **kwargs):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, **kwargs)


def emit(rows, label):
    """Refuse a run that lost a case, then print the table. Checking first
    keeps a short table out of a file someone is redirecting this into."""
    missing = [name for name, _, _ in ACTIVE if name not in {r[0] for r in rows}]
    if missing:
        raise SystemExit("%s answered %d of %d cases, missing: %s"
                         % (label, len(rows), len(ACTIVE), ", ".join(missing)))
    for name, engine_type, value in rows:
        want = expected(name)
        if FAMILY == "overflow":
            print("%-26s %-16s %s%s" % (name, engine_type, value, saturating_answer(name, value)))
            continue
        mark = "" if norm(engine_type) == norm(want) else "   differ"
        print("%-26s %-14s %-16s %s%s" % (name, want, engine_type, value, mark))


def spark():
    """One spark-submit, so that a case that raises does not end the run, and
    two passes over the overflow cases for the two values of the ANSI flag."""
    script = [
        "from pyspark.sql import SparkSession",
        "spark = (SparkSession.builder.appName('substrait-decimal')",
        "         .config('spark.sql.catalogImplementation', 'in-memory')",
        "         .config('spark.ui.enabled', 'false').getOrCreate())",
        "spark.sparkContext.setLogLevel('ERROR')",
        "print('# spark.sql.decimalOperations.allowPrecisionLoss = %s'",
        "      % spark.conf.get('spark.sql.decimalOperations.allowPrecisionLoss'))",
        "CASES = [",
    ]
    for name, expr, _ in ACTIVE:
        script.append("    (%r, %r)," % (name, expr))
    script += [
        "]",
        "OVERFLOW = %r" % (OVERFLOW if FAMILY == "decimal" else [n for n, _, _ in ACTIVE]),
        "def one(name, expr, prefix):",
        "    df = spark.sql('SELECT ' + expr + ' AS v')",
        "    t = df.schema[0].dataType.simpleString()",
        "    try:",
        "        v = df.collect()[0][0]",
        "        v = 'NULL' if v is None else str(v)",
        "    except Exception as e:",
        "        v = 'ERROR ' + str(e).strip().splitlines()[0].split(']')[0].lstrip('[')",
        "    print('%s%s\\t%s\\t%s' % (prefix, name, t, v))",
        "for ansi in ('true', 'false'):",
        "    spark.conf.set('spark.sql.ansi.enabled', ansi)",
        "    if ansi == 'true':",
        "        print('# spark.sql.ansi.enabled = true (its default)')",
        "        for name, expr in CASES:",
        "            one(name, expr, 'ROW\\t')",
        "    else:",
        "        pass",
        "        for name, expr in CASES:",
        "            if name in OVERFLOW:",
        "                one(name, expr, 'ANSIOFF\\t')",
        "spark.stop()",
    ]
    work = tempfile.mkdtemp()
    os.chmod(work, 0o755)          # the image runs as UID 185, mkdtemp is 0700
    path = os.path.join(work, "cases.py")
    with open(path, "w") as f:
        f.write("\n".join(script) + "\n")
    os.chmod(path, 0o644)
    out = run(["docker", "run", "--rm", "-v", work + ":/w", SPARK_IMAGE,
               "/opt/spark/bin/spark-submit", "--conf", "spark.ui.enabled=false", "/w/cases.py"])
    print("# %s" % SPARK_IMAGE)
    rows, tail = [], []
    for line in out.stdout.splitlines():
        if line.startswith("#"):
            print(line)
        elif line.startswith("ROW\t"):
            rows.append(tuple(line.split("\t")[1:4]))
        elif line.startswith("ANSIOFF\t"):
            tail.append(tuple(line.split("\t")[1:4]))
    if not rows:
        sys.stderr.write(out.stderr[-4000:])
        raise SystemExit("spark produced no rows")
    emit(rows, "spark")
    want_tail = OVERFLOW if FAMILY == "decimal" else [n for n, _, _ in ACTIVE]
    if len(tail) != len(want_tail):
        raise SystemExit("spark answered %d of %d overflow cases with ANSI off"
                         % (len(tail), len(want_tail)))
    print("# spark.sql.ansi.enabled = false")
    for name, engine_type, value in tail:
        if FAMILY == "overflow":
            print("%-26s %-16s %s%s" % (name, engine_type, value, saturating_answer(name, value)))
        else:
            print("%-26s %-14s %-14s %s" % (name, expected(name), engine_type, value))


def server_up(container, image, extra=()):
    """Start the engine unless it is already up on this image. Reusing a
    container that runs another one would answer from one version while the
    run claims another."""
    state = run(["docker", "inspect", "-f", "{{.State.Running}} {{.Config.Image}}",
                 container]).stdout.split()
    if state[:1] == ["true"] and state[1:2] == [image]:
        return
    run(["docker", "rm", "-f", container])
    started = run(["docker", "run", "-d", "--name", container] + list(extra) + [image])
    if started.returncode:
        raise SystemExit(started.stderr.strip())


def await_ready(container, probe_cmd):
    deadline = time.time() + STARTUP_SECONDS
    while time.time() < deadline:
        out = run(["docker", "exec", container] + probe_cmd)
        if out.returncode == 0 and "1" in out.stdout.split():
            return
        time.sleep(2)
    raise SystemExit("%s did not answer within %d seconds" % (container, STARTUP_SECONDS))


def refusal(out):
    """An engine that will not answer a case has answered it: keep the reason
    on the row rather than end the run."""
    for line in (out.stdout + "\n" + out.stderr).splitlines():
        line = line.strip()
        if line and re.search(r"error|failed|exception|out of range", line, re.I):
            return line[:90]
    return "no answer"


def per_query(container, build, parse):
    """Trino, MySQL and ClickHouse are asked one case at a time, so that a case
    the engine rejects leaves a row instead of taking the run with it."""
    rows = []
    for i, (name, expr, _) in enumerate(ACTIVE):
        out = run(["docker", "exec", container] + build(i, expr))
        got = None if out.returncode else parse(out.stdout)
        rows.append((name, "-", refusal(out)) if got is None else (name,) + got)
    return rows


def trino():
    container = "substrait-decimal-trino"
    server_up(container, TRINO_IMAGE)
    await_ready(container, ["trino", "--output-format=TSV", "--execute", "select 1"])

    def build(_i, expr):
        return ["trino", "--output-format=TSV", "--execute",
                "SELECT typeof(%s), CAST(%s AS varchar)" % (expr, expr)]

    def parse(text):
        line = text.strip().splitlines()
        if not line:
            return None
        parts = (line[0].split("\t") + [""])[:2]
        return (parts[0], parts[1] or "NULL")

    print("# %s" % TRINO_IMAGE)
    emit(per_query(container, build, parse), "trino")


def clickhouse():
    container = "substrait-decimal-clickhouse"
    server_up(container, CLICKHOUSE_IMAGE)
    await_ready(container, ["clickhouse-client", "-q", "select 1"])

    def build(_i, expr):
        # ClickHouse refuses to cast NULL to a non-nullable type, so the two
        # null cases say so; everything else is the same expression.
        expr = expr.replace("CAST(NULL AS DECIMAL(10,2))",
                            "CAST(NULL AS Nullable(DECIMAL(10,2)))")
        return ["clickhouse-client", "-q",
                "SELECT toTypeName(%s), toString(%s)" % (expr, expr)]

    def parse(text):
        line = text.strip().splitlines()
        if not line:
            return None
        parts = (line[0].split("\t") + [""])[:2]
        return (parts[0], parts[1] or "NULL")

    print("# %s" % CLICKHOUSE_IMAGE)
    emit(per_query(container, build, parse), "clickhouse")


def mysql():
    container = "substrait-decimal-mysql"
    server_up(container, MYSQL_IMAGE, ["-e", "MYSQL_ALLOW_EMPTY_PASSWORD=1"])
    await_ready(container, ["mysql", "-uroot", "-N", "-e", "select 1"])

    def build(i, expr):
        # MySQL prints no type for an expression either, and has no temporary
        # view, so each case becomes a table and is read back from the catalog.
        sql = ("CREATE DATABASE IF NOT EXISTS substrait_decimal;"
               "DROP TABLE IF EXISTS substrait_decimal.c%d;"
               "CREATE TABLE substrait_decimal.c%d AS SELECT %s AS v;"
               "SELECT column_type FROM information_schema.columns"
               " WHERE table_schema='substrait_decimal' AND table_name='c%d';"
               "SELECT IFNULL(CAST(v AS CHAR), 'NULL') FROM substrait_decimal.c%d;"
               % (i, i, expr, i, i))
        return ["mysql", "-uroot", "-N", "-e", sql]

    def parse(text):
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            return None
        return (lines[0], lines[1])

    print("# %s" % MYSQL_IMAGE)
    emit(per_query(container, build, parse), "mysql")


def beeline(sql, check=True):
    work = tempfile.mkdtemp()
    path = os.path.join(work, "q.sql")
    with open(path, "w") as f:
        f.write(sql)
    copied = run(["docker", "cp", path, HIVE_CONTAINER + ":/tmp/q.sql"])
    if copied.returncode and check:
        raise SystemExit(copied.stderr.strip())
    out = run(["docker", "exec", HIVE_CONTAINER, "beeline",
               "-u", "jdbc:hive2://localhost:10000/", "--outputformat=tsv2",
               "--silent=true", "-f", "/tmp/q.sql"])
    if check and (out.returncode or "Error" in out.stdout or "Error" in out.stderr):
        raise SystemExit("hive rejected a statement:\n" + (out.stdout + out.stderr)[-2000:])
    return out.stdout


def hive_up():
    running = run(["docker", "inspect", "-f", "{{.State.Running}} {{.Config.Image}}",
                   HIVE_CONTAINER]).stdout.split()
    if running[:1] == ["true"]:
        if running[1:2] == [HIVE_IMAGE]:
            return
        # Reusing it would answer from one version while the run claims another.
        run(["docker", "rm", "-f", HIVE_CONTAINER])
    else:
        run(["docker", "rm", "-f", HIVE_CONTAINER])
    # No published port: beeline is reached through docker exec, and publishing
    # 10000 makes the run fail when anything else on the host holds it.
    started = run(["docker", "run", "-d", "--name", HIVE_CONTAINER,
                   "--env", "SERVICE_NAME=hiveserver2", HIVE_IMAGE])
    if started.returncode:
        raise SystemExit(started.stderr.strip())
    deadline = time.time() + STARTUP_SECONDS
    while time.time() < deadline:
        if "1" in beeline("select 1 as one;", check=False).split():
            return
        time.sleep(2)
    raise SystemExit("HiveServer2 did not answer within %d seconds" % STARTUP_SECONDS)


def hive():
    hive_up()
    ddl = []
    for i, (_, expr, _) in enumerate(ACTIVE):
        ddl.append("drop view if exists dec_%d;" % i)
        ddl.append("create view dec_%d as select %s as v;" % (i, expr))
    beeline("\n".join(ddl))
    query = []
    for i, (name, _, _) in enumerate(ACTIVE):
        query.append("select '%s' as c, cast(v as string) as value from dec_%d;" % (name, i))
        query.append("describe dec_%d;" % i)
    text = beeline("\n".join(query))
    names = {name for name, _, _ in ACTIVE}
    rows, pending = [], None
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] in names:
            pending = (parts[0], parts[1] or "NULL")
        elif pending and len(parts) >= 2 and parts[0] == "v":
            rows.append((pending[0], parts[1], pending[1]))
            pending = None
    if not rows:
        raise SystemExit("hive produced no rows:\n" + text[-2000:])
    print("# %s" % HIVE_IMAGE)
    emit(rows, "hive")


ENGINES = {"spark": lambda: spark(), "hive": lambda: hive(), "trino": lambda: trino(),
           "mysql": lambda: mysql(), "clickhouse": lambda: clickhouse()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("engine", choices=sorted(ENGINES))
    ap.add_argument("--overflow", action="store_true",
                    help="run the integer overflow cases instead of the decimal ones")
    ap.add_argument("--stop", action="store_true",
                    help="remove the containers this probe leaves running and exit")
    args = ap.parse_args()
    if args.overflow:
        global ACTIVE, FAMILY
        ACTIVE = [(name, exprs[args.engine], None) for name, exprs in OVERFLOW_CASES
                  if exprs[args.engine] is not None]
        FAMILY = "overflow"
    if args.stop:
        for container in (HIVE_CONTAINER, "substrait-decimal-trino",
                          "substrait-decimal-mysql", "substrait-decimal-clickhouse"):
            run(["docker", "rm", "-f", container])
        return
    ENGINES[args.engine]()


if __name__ == "__main__":
    main()
