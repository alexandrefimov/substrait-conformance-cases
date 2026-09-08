"""Compare Isthmus's default type factory with Impala's on the same classpath.

Requires already built Java artifacts; it does not build or start Impala. See --help.
Outputs are a diagnostic pair, outside the saved consumer matrix.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


PROBE = Path(__file__).resolve().parent
ROOT = PROBE.parent
FACTORY = "org.apache.impala.calcite.type.ImpalaTypeFactoryImpl"


def fingerprint(path):
    if not path.exists():
        return None  # Gradle can include an optional resources directory that was never created.
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(child.relative_to(path).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(child.read_bytes()).digest())
    return digest.hexdigest()


def check_column(path, names):
    """Validate every submitted case, including the five unscored cases."""
    rows = path.read_text().split("\n\n", 1)[1].splitlines()
    seen = []
    answered = 0
    for row in rows:
        name, answer = row.split(maxsplit=1)
        seen.append(name)
        answered += not answer.startswith("ERROR:")
    if len(seen) != len(names) or set(seen) != names:
        raise RuntimeError("incomplete or duplicate cases in " + path.name)
    if not answered:
        raise RuntimeError("every case refused in " + path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isthmus-classpath", required=True, type=Path,
                        help="classpath file produced by probe/cp.sh isthmus")
    parser.add_argument("--impala-classpath", required=True, type=Path,
                        help="classpath file containing built Impala planner/frontend and dependencies")
    parser.add_argument("--substrait-java-revision", required=True,
                        help="source revision from the Isthmus build record")
    parser.add_argument("--impala-revision", required=True,
                        help="source revision from the Impala build record")
    parser.add_argument("--out", required=True, type=Path, help="new directory for local run artifacts")
    args = parser.parse_args()
    entries = []
    for cp_file in (args.isthmus_classpath, args.impala_classpath):
        parts = cp_file.read_text().strip().split(os.pathsep)
        if not all(parts):
            parser.error("empty classpath entry in " + str(cp_file))
        for part in parts:
            path = Path(part)
            if not path.is_absolute() or "*" in part:
                parser.error("classpath entries must be explicit absolute paths: " + part)
            if path.suffix == ".jar" and not path.is_file():
                parser.error("missing classpath jar: " + part)
            if path not in entries:
                entries.append(path)
    # Put the complete Isthmus classpath first on BOTH runs: adding Impala must not silently
    # replace Calcite or protobuf only for the experimental side.
    cp = os.pathsep.join(map(str, entries))
    cases = sorted(p for p in (ROOT / "derived-schema").glob("*.json") if p.name != "manifest.json")
    if not cases:
        parser.error("empty corpus")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    classes = out / "classes"
    classes.mkdir()
    inputs = {str(p): fingerprint(p) for p in entries}
    record = {
        "taken": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Isthmus relation schemas with default and Impala type factories; no Impala execution",
        "build_revision_labels": {"substrait_java": args.substrait_java_revision,
                                  "impala": args.impala_revision},
        "classpath_sha256": inputs,
        "corpus_sha256": {p.name: fingerprint(p) for p in cases},
        "probe_sha256": {n: fingerprint(PROBE / n) for n in
                         ("TypeFactorySchemaOf.java", "CalciteSchemaOf.java", "impala_types.py")},
    }
    (out / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    with (out / "compile.log").open("w") as log:
        subprocess.run(["javac", "-nowarn", "-cp", cp, "-d", str(classes),
                        str(PROBE / "CalciteSchemaOf.java"), str(PROBE / "TypeFactorySchemaOf.java")],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    columns = []
    for label, factory in (("ISTHMUS-DEFAULT", "default"), ("ISTHMUS-IMPALA-TYPES", FACTORY)):
        raw = out / (label + ".raw")
        column = out / (label + ".txt")
        with raw.open("w") as stdout, (out / (label + ".log")).open("w") as stderr:
            subprocess.run(["java", "-cp", str(classes) + os.pathsep + cp, "TypeFactorySchemaOf",
                            factory, *map(str, cases)], stdout=stdout, stderr=stderr, check=True)
        with column.open("w") as stdout:
            subprocess.run([sys.executable, str(PROBE / "normalize.py"), str(raw), "line",
                            label + ": " + record["taken"]], stdout=stdout, check=True)
        check_column(column, {p.stem for p in cases})
        scored = subprocess.run([sys.executable, str(PROBE / "check_expected.py"), str(column),
                                 "calcite"], capture_output=True, text=True)
        (out / (label + "-expected.txt")).write_text(scored.stdout + scored.stderr)
        # A schema divergence is the measurement. An unparsed answer, incomplete output or
        # failed checker is a harness error, even if the other side ran successfully.
        summary = [line for line in scored.stdout.splitlines() if line.startswith("matched:")]
        if (scored.returncode not in (0, 1) or len(summary) != 1
                or "unparsed by the check: 0," not in summary[0]
                or "INCOMPLETE:" in scored.stdout):
            raise RuntimeError("invalid checker result for " + label)
        print(label + ": " + summary[0], flush=True)
        columns.append(column)
    delta = subprocess.run([sys.executable, str(PROBE / "column_diff.py"), *map(str, columns),
                            "Impala type factory"], capture_output=True, text=True)
    (out / "comparison.txt").write_text(delta.stdout + delta.stderr)
    if delta.returncode not in (0, 1):
        raise RuntimeError("column comparison failed")
    if inputs != {str(p): fingerprint(p) for p in entries}:
        raise RuntimeError("classpath contents changed during the comparison")
    print(delta.stdout, end="")
    (out / "COMPLETE").write_text("Both columns are complete and readable; differences are measurements.\n")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit("HARNESS FAILED: " + str(error))
