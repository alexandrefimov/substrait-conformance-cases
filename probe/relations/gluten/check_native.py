#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check fixture binding against a built native probe, without corpus expectations."""
import argparse
from collections import Counter
from pathlib import Path
import tempfile
import unittest

import run

BINARY = None


def fixture_case():
    case = run.corpus.rt.RelationTestCase(id="harness/fixture",
                                         kind=run.corpus.rt.RelationTestCase.KIND_UNRESOLVED)
    table = case.tables.add()
    table.name.append("fixture")
    table.schema.names.extend(["n", "s", "b"])
    for kind in ("i64", "string", "bool"):
        typ = table.schema.struct.types.add()
        getattr(typ, kind).nullability = run.corpus.Type.NULLABILITY_NULLABLE
    for values in ((7, "x", True), (-3, "y", False), (7, "x", True), (None, None, None)):
        row = table.rows.add()
        for typ, value in zip(table.schema.struct.types, values):
            literal = row.fields.add()
            if value is None:
                literal.null.CopyFrom(typ)
            else:
                kind = typ.WhichOneof("kind")
                setattr(literal, "boolean" if kind == "bool" else kind, value)
    read = case.plan.relations.add().root.input.read
    read.common.direct.SetInParent()
    read.named_table.names.extend(table.name)
    read.base_schema.CopyFrom(table.schema)
    return case


class NativeTests(unittest.TestCase):
    def observe(self, case):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "case.pb"
            bundle.write_bytes(case.SerializeToString())
            return run.observe(BINARY, bundle, 20)

    def test_primitives_nulls_duplicates_and_order(self):
        record = self.observe(fixture_case())
        self.assertEqual(record["status"], "OK", record)
        self.assertEqual(record["arity"], 3)
        self.assertEqual(record["rows"],
                         [["7", "x", "true"], ["-3", "y", "false"],
                          ["7", "x", "true"], [None, None, None]])

    def test_empty_fixture_keeps_its_schema(self):
        case = fixture_case()
        del case.tables[0].rows[:]
        record = self.observe(case)
        self.assertEqual(record["status"], "OK", record)
        self.assertEqual(record["arity"], 3)
        self.assertEqual(record["rows"], [])

    def test_each_read_gets_its_own_stream(self):
        case = fixture_case()
        read = type(case.plan.relations[0].root.input)()
        read.CopyFrom(case.plan.relations[0].root.input)
        root = case.plan.relations[0].root
        root.ClearField("input")
        join = root.input.nested_loop_join
        join.type = 1  # JOIN_TYPE_INNER; no function extension needed.
        join.expression.literal.boolean = True
        join.left.CopyFrom(read)
        join.right.CopyFrom(read)
        record = self.observe(case)
        self.assertEqual(record["status"], "OK", record)
        self.assertEqual(record["input_streams"], 2)
        rows = [("7", "x", "true"), ("-3", "y", "false"),
                ("7", "x", "true"), (None, None, None)]
        self.assertEqual(Counter(map(tuple, record["rows"])),
                         Counter(left + right for left in rows for right in rows))

    def test_binding_failures_are_harness_errors(self):
        mutations = ("missing", "duplicate", "schema", "row-arity", "null-type", "filter")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                case = fixture_case()
                read = case.plan.relations[0].root.input.read
                if mutation == "missing":
                    del case.tables[:]
                elif mutation == "duplicate":
                    case.tables.add().CopyFrom(case.tables[0])
                elif mutation == "schema":
                    read.base_schema.names[0] = "wrong"
                elif mutation == "row-arity":
                    del case.tables[0].rows[0].fields[-1]
                elif mutation == "null-type":
                    case.tables[0].rows[-1].fields[0].null.i64.nullability = (
                        run.corpus.Type.NULLABILITY_REQUIRED)
                elif mutation == "filter":
                    read.filter.literal.boolean = True
                record = self.observe(case)
                self.assertEqual(record["status"], "HARNESS-ERROR", record)

    def test_unsupported_fixture_is_not_a_consumer_refusal(self):
        case = fixture_case()
        typ = case.tables[0].schema.struct.types[0]
        typ.ClearField("i64")
        typ.decimal.precision, typ.decimal.scale = 10, 2
        case.plan.relations[0].root.input.read.base_schema.CopyFrom(case.tables[0].schema)
        record = self.observe(case)
        self.assertEqual(record["status"], "HARNESS-ERROR", record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    BINARY = args.binary.resolve()
    unittest.main(argv=[__file__])
