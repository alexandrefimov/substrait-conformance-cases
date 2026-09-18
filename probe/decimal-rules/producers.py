#!/usr/bin/env python3
"""Which function a producer writes for decimal arithmetic, and which type it declares for it.

A consumer that derives a type other than the formula's only matters if some producer sends it a
plan calling these functions. This reads the plans four producers wrote for the same SQL and
prints, for every scalar call in them: the function name, the extension URN that name is resolved
against, the output_type the producer declared, and the type the functions_arithmetic_decimal.yaml
formula gives for the same operands, as rules.substrait computes it.

The plans come from the producer probes, each run with SUBSTRAIT_PLANS_OUT pointing at a directory
named after the producer. All four create the same table t: a DECIMAL(10,2), b DECIMAL(5,1),
c and d DECIMAL(38,10), i BIGINT; nullability differs (Spark's parquet table is nullable).

    P=<dir>
    SUBSTRAIT_PLANS_OUT=$P/spark   bash probe/spark_run.sh ProducerSpark \\
        "SELECT a + b FROM t" "SELECT c + d FROM t" "SELECT c * d FROM t" "SELECT a / b FROM t"
    SUBSTRAIT_PLANS_OUT=$P/isthmus bash probe/isthmus_run.sh ProducerIsthmus \\
        "CREATE TABLE t (a DECIMAL(10,2) NOT NULL, b DECIMAL(5,1) NOT NULL, c DECIMAL(38,10) NOT NULL, d DECIMAL(38,10) NOT NULL, i BIGINT NOT NULL)" \\
        "SELECT a + b FROM t" "SELECT c + d FROM t" "SELECT c * d FROM t" "SELECT a / b FROM t"
    SUBSTRAIT_PLANS_OUT=$P/duckdb  <venv>/bin/python probe/duckdb_producer.py --load-only
    SUBSTRAIT_PLANS_OUT=$P/datafusion cargo run --locked -p datafusion-substrait --example corpus_producer
        (from a DataFusion checkout, as probe/README.md describes)
    <pysub>/bin/python probe/decimal-rules/producers.py $P/*

Needs the substrait protobuf bindings (the substrait-python environment has them). A plan file is
<expression>.pb (binary) or <expression>.json (DuckDB's get_substrait_json); the expression is
recovered from the file name, and the formula column is filled only for a single operation on two
columns of t. A function whose URN reference resolves to nothing is printed as "(unresolved N)".
"""

import argparse
import os
import sys

from google.protobuf import json_format
from google.protobuf.message import Message
from substrait import algebra_pb2, plan_pb2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules  # noqa: E402

COLUMNS = {"a": (10, 2), "b": (5, 1), "c": (38, 10), "d": (38, 10)}
OPS = {"add": "add", "sub": "subtract", "mul": "multiply", "div": "divide"}


def load(path):
    plan = plan_pb2.Plan()
    if path.endswith(".json"):
        with open(path) as f:
            json_format.Parse(f.read(), plan, ignore_unknown_fields=True)
    else:
        with open(path, "rb") as f:
            plan.ParseFromString(f.read())
    return plan


def type_str(t):
    kind = t.WhichOneof("kind")
    if kind is None:
        return "none"
    if kind == "decimal":
        return "dec(%d,%d)" % (t.decimal.precision, t.decimal.scale)
    return kind


def calls(message):
    """Every ScalarFunction in the plan, outermost first."""
    if isinstance(message, algebra_pb2.Expression.ScalarFunction):
        yield message
    for field, value in message.ListFields():
        if field.type != field.TYPE_MESSAGE:
            continue
        for item in (value if field.is_repeated else [value]):
            if isinstance(item, Message):
                yield from calls(item)


def formula_type(stem):
    parts = stem.split("_")
    if len(parts) == 3 and parts[0] in COLUMNS and parts[2] in COLUMNS and parts[1] in OPS:
        (p1, s1), (p2, s2) = COLUMNS[parts[0]], COLUMNS[parts[2]]
        return rules.fmt(rules.substrait(OPS[parts[1]], p1, s1, p2, s2))
    return "-"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="one directory of plans per producer, named after it")
    args = ap.parse_args()
    print("%-11s %-22s %-18s %-52s %-11s %s" % ("producer", "plan", "function", "urn", "declared", "formula"))
    for d in args.dirs:
        producer = os.path.basename(os.path.normpath(d))
        for name in sorted(os.listdir(d)):
            stem, ext = os.path.splitext(name)
            if ext not in (".pb", ".json"):
                continue
            plan = load(os.path.join(d, name))
            urns = {u.extension_urn_anchor: u.urn for u in plan.extension_urns}
            functions = {}
            for e in plan.extensions:
                if e.HasField("extension_function"):
                    f = e.extension_function
                    ref = f.extension_urn_reference
                    functions[f.function_anchor] = (f.name, urns.get(ref, "(unresolved %d)" % ref))
            found = list(calls(plan))
            if not found:
                print("%-11s %-22s (no scalar calls)" % (producer, stem))
            for i, sf in enumerate(found):
                fname, urn = functions.get(sf.function_reference, ("#%d" % sf.function_reference, "?"))
                print("%-11s %-22s %-18s %-52s %-11s %s" % (
                    producer, stem, fname, urn, type_str(sf.output_type), formula_type(stem) if i == 0 else ""))


if __name__ == "__main__":
    main()
