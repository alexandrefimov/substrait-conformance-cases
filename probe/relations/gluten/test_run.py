# SPDX-License-Identifier: Apache-2.0
"""Driver trust-boundary checks. Needs bootstrap bindings and protobuf."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import run


class DriverTests(unittest.TestCase):
    def test_every_request_keeps_program_and_fixtures_but_not_expectation(self):
        for path in run.corpus.bundle_paths():
            with self.subTest(bundle=Path(path).name):
                case = run.corpus.read(path)
                original = case.SerializeToString()
                request = type(case)()
                request.ParseFromString(run.request_bytes(case))
                self.assertFalse(request.HasField("expect"))
                self.assertEqual(request.plan, case.plan)
                self.assertEqual(list(request.tables), list(case.tables))
                self.assertEqual(request.id, case.id)
                self.assertEqual(case.SerializeToString(), original)
                case.ClearField("expect")
                self.assertEqual(run.request_bytes(case), run.request_bytes(request))

    def test_failure_records_cannot_be_success(self):
        valid = {"id": "case", "status": "OK", "arity": 1,
                 "schema": "ROW<a:BIGINT>", "rows": [["1"], [None]]}
        line = run.PREFIX + json.dumps(valid)
        self.assertEqual(run.response(line, "case", 0), valid)
        self.assertEqual(run.response(line, "case", 139)["status"], "CRASH")
        for stdout in ("", "[ PASSED ] 0 tests", line + "\n" + line,
                       run.PREFIX + "not-json", run.PREFIX + "[]"):
            self.assertEqual(run.response(stdout, "case", 0)["status"], "HARNESS-ERROR")
        self.assertEqual(run.response(line, "other-case", 0)["status"], "HARNESS-ERROR")
        for replacement in ({"rows": [[1]]}, {"rows": [[]]}, {"rows": None},
                            {"arity": True}, {"status": "MATCHED"}, {"schema": None}):
            malformed = dict(valid, **replacement)
            self.assertEqual(run.response(run.PREFIX + json.dumps(malformed), "case", 0)["status"],
                             "HARNESS-ERROR")

    def test_subprocess_gets_only_the_request_and_private_write_directory(self):
        bundle = Path(run.corpus.bundle_paths()[0])
        case = run.corpus.read(str(bundle))
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "consumer"
            binary.write_text("#!" + sys.executable + "\n" + """
import json, os, pathlib, sys
sys.path.insert(0, %r)
from substrait.test import relation_test_pb2 as rt
case = rt.RelationTestCase()
request = pathlib.Path(os.environ["GLUTEN_RELATION_BUNDLE"])
case.ParseFromString(request.read_bytes())
assert not case.HasField("expect")
assert request.parent == pathlib.Path(os.environ["GLUTEN_RELATION_WRITE_DIR"]).parent
print("RELATION_RESULT " + json.dumps({
    "id": case.id, "status": "OK", "arity": 1,
    "schema": "ROW<x:BIGINT>", "rows": [["7"], [None]]}))
""" % run.corpus._BINDINGS)
            binary.chmod(0o700)
            record = run.observe(binary, bundle, 5)
            self.assertEqual(record["id"], case.id)
            self.assertEqual(record["status"], "OK")
            self.assertEqual(record["rows"], [["7"], [None]])
            binary.write_text("#!" + sys.executable + "\nimport time; time.sleep(2)\n")
            self.assertEqual(run.observe(binary, bundle, 0.1)["status"], "TIMEOUT")
            binary.write_text("#!" + sys.executable + "\nraise SystemExit(42)\n")
            self.assertEqual(run.observe(binary, bundle, 5)["status"], "CRASH")
            binary.write_text("#!" + sys.executable + "\nprint('[ PASSED ] 0 tests')\n")
            self.assertEqual(run.observe(binary, bundle, 5)["status"], "HARNESS-ERROR")


if __name__ == "__main__":
    unittest.main()
