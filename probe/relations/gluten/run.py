#!/usr/bin/env python3
"""Observe Gluten execution from compiled bundles; do not score or publish a column."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import corpus

PREFIX = "RELATION_RESULT "
BOUNDARY = ("Native Velox schema and cell text; no nullability; leaf names are stream aliases. Rows retain execution order. "
            "Not a normalized or scored participant column.")


def request_bytes(case):
    request = type(case)()
    request.CopyFrom(case)
    request.ClearField("expect")
    return request.SerializeToString()


def response(stdout, case_id, returncode):
    if returncode != 0:
        return {"status": "CRASH", "message": "native process exit %d" % returncode}
    lines = [line[len(PREFIX):] for line in stdout.splitlines() if line.startswith(PREFIX)]
    try:
        if len(lines) != 1:
            raise ValueError("expected one result record, got %d" % len(lines))
        record = json.loads(lines[0])
        if record.get("id") != case_id:
            raise ValueError("native result identity differs")
        if record.get("status") not in ("OK", "ERROR", "HARNESS-ERROR"):
            raise ValueError("unknown native status")
        if record["status"] == "OK":
            arity, rows = record.get("arity"), record.get("rows")
            if (type(arity) is not int or arity < 0 or not isinstance(record.get("schema"), str)
                    or not isinstance(rows, list)):
                raise ValueError("native schema/rows missing")
            if any(not isinstance(row, list) or len(row) != arity
                   or any(value is not None and not isinstance(value, str) for value in row)
                   for row in rows):
                raise ValueError("native row arity/cell encoding")
        elif not isinstance(record.get("message"), str):
            raise ValueError("native failure message missing")
        return record
    except (ValueError, TypeError, AttributeError) as error:
        return {"status": "HARNESS-ERROR", "message": str(error)}


def observe(binary, bundle, timeout):
    case = corpus.read(str(bundle))
    record = {"id": case.id, "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
              "kind": corpus.KIND_NAME.get(case.kind, "UNKNOWN")}
    with tempfile.TemporaryDirectory(prefix="gluten-relation-") as directory:
        request = Path(directory) / "request.pb"
        request.write_bytes(request_bytes(case))
        write_dir = Path(directory) / "writes"
        write_dir.mkdir()
        env = os.environ.copy()
        env.update(GLUTEN_RELATION_BUNDLE=str(request), GLUTEN_RELATION_WRITE_DIR=str(write_dir))
        try:
            child = subprocess.run([str(binary), "--gtest_filter=RelationsProbeTest.bundle"],
                                   env=env, capture_output=True, text=True, timeout=timeout)
            answer = response(child.stdout, case.id, child.returncode)
        except subprocess.TimeoutExpired:
            answer = {"status": "TIMEOUT", "message": "native process exceeded %g seconds" % timeout}
        except OSError as error:
            answer = {"status": "HARNESS-ERROR", "message": str(error)}
    record.update(answer)
    # Temporary paths and native stack text stay out of the diagnostic record.
    if "message" in record:
        record["message"] = record["message"].replace(directory, "<case-temp>").split("Retriable:")[0].strip()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--gluten-revision", required=True, help="revision from the native build record")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("bundles", nargs="*", type=Path, help="default: all committed bundles")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    binary = args.binary.resolve()
    bundles = args.bundles or [Path(path) for path in corpus.bundle_paths()]
    print(json.dumps({"type": "provenance", "observed_at": datetime.now(timezone.utc).isoformat(),
                      "gluten_revision": args.gluten_revision,
                      "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                      "boundary": BOUNDARY}, sort_keys=True))
    records = []
    for path in bundles:
        record = observe(binary, path, args.timeout)
        records.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
    # Unsupported harness inputs cannot become a successful whole-corpus run.
    return int(any(record["status"] in ("HARNESS-ERROR", "CRASH", "TIMEOUT") for record in records))


if __name__ == "__main__":
    raise SystemExit(main())
