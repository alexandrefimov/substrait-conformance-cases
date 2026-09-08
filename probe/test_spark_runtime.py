"""Failure controls for the separate Spark runtime runner; no engine installation needed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from spark_runtime import column_answers, diagnostics, verify_identity


class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "output.txt"

    def test_column_completeness(self):
        self.output.write_text("SPARK: test\n\na [r:i32]\nb ERROR: unsupported\n")
        self.assertEqual(len(column_answers(self.output, {"a", "b"})), 2)
        for body in ("a [r:i32]\n", "a [r:i32]\na [r:i32]\n",
                     "a [r:i32]\nc ERROR: unsupported\n"):
            with self.subTest(body=body):
                self.output.write_text("SPARK: test\n\n" + body)
                with self.assertRaises(ValueError):
                    column_answers(self.output, {"a", "b"})

    def write_diagnostics(self, rows):
        self.output.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    def test_diagnostic_verdicts(self):
        rows = [{"case": "safe", "control": True, "matches": True},
                {"case": "overflow", "control": False, "matches": False},
                {"cases": 2, "differences": 1, "failed_controls": 0}]
        expected = {"safe": True, "overflow": False}
        self.write_diagnostics(rows)
        self.assertEqual(diagnostics(self.output, expected)["differences"], 1)
        mutations = []
        failed = copy.deepcopy(rows)
        failed[0]["matches"] = False
        failed[-1].update(differences=2, failed_controls=1)
        mutations.append(failed)
        mutations.append(rows[1:])
        mutations.append([rows[0], rows[0], rows[-1]])
        for key, value in (("control", False), ("matches", "true"), ("case", "unexpected")):
            changed = copy.deepcopy(rows)
            changed[0][key] = value
            mutations.append(changed)
        summary = copy.deepcopy(rows)
        summary[-1]["differences"] = 0
        mutations.append(summary)
        for mutation in mutations:
            with self.subTest(rows=mutation):
                self.write_diagnostics(mutation)
                with self.assertRaises(ValueError):
                    diagnostics(self.output, expected)

    def test_runtime_identity(self):
        identity = {"spark": "4.2.0", "scala": "2.13.18", "java": "17.0.20.1",
                    "ansi_default": True, "substrait_spec": "0.102.0",
                    "consumer_loaded_from": (self.root / "consumer-build/classes/scala/main").as_uri(),
                    "spark_loaded_from": (self.root / "spark-catalyst_2.13-4.2.0.jar").as_uri()}
        dependencies = [{"group": "org.apache.spark", "name": name, "version": "4.2.0"}
                        for name in ("spark-core_2.13", "spark-catalyst_2.13")]
        verify_identity(identity, dependencies, "4.2.0", "spark-4.0_2.13", self.root)
        for key, value in (("spark", "4.0.2"), ("scala", "2.12.21"), ("java", "21.0.1"),
                           ("ansi_default", "true"), ("substrait_spec", ""),
                           ("consumer_loaded_from", (self.root / "old-build").as_uri()),
                           ("spark_loaded_from", (self.root / "spark-catalyst_2.13-4.0.2.jar").as_uri())):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    verify_identity({**identity, key: value}, dependencies,
                                    "4.2.0", "spark-4.0_2.13", self.root)
        for bad in ([], [dependencies[0], {**dependencies[1], "version": "4.0.2"}]):
            with self.subTest(dependencies=bad):
                with self.assertRaises(ValueError):
                    verify_identity(identity, bad, "4.2.0", "spark-4.0_2.13", self.root)


if __name__ == "__main__":
    unittest.main()
