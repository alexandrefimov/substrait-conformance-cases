"""Run minimal consumer and text round-trip cases, separately from the saved matrix.

Set SUBSTRAIT_PROBE_ENV to the environment built by probe/setup.sh.
Differences are reported as JSON Lines; --check makes them fail the command.
Missing tools, malformed output and failing controls always fail the command.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

PROBE = Path(__file__).resolve().parent
CASES = PROBE / "structural-cases"


def load_cases():
    groups = json.loads((CASES / "expected.json").read_text())
    if set(groups) != {"duckdb", "go", "validator", "explain", "spark", "acero"}:
        raise ValueError("expected the duckdb, go, validator, explain, spark and acero case groups")
    for engine, cases in groups.items():
        files = {p.stem for p in (CASES / engine).glob("*.json")}
        if not cases or set(cases) != files or not any(c["control"] for c in cases.values()):
            raise ValueError(f"{engine}: incomplete fixtures or missing controls")
        for name in cases:
            plan = json.loads((CASES / engine / (name + ".json")).read_text())
            if len(plan.get("relations", [])) != 1 or "root" not in plan["relations"][0]:
                raise ValueError(f"{engine}/{name}: expected one rooted plan")
            if engine in ("go", "acero") and not (CASES / engine / (name + ".bin")).is_file():
                raise ValueError(f"{engine}/{name}: missing binary plan")
    return groups


def duck_worker(path):
    import duckdb

    con = duckdb.connect()
    con.execute("LOAD substrait")
    version = con.execute(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'"
    ).fetchone()[0]
    con.execute("CREATE TABLE t (x INTEGER NOT NULL)")
    con.execute("INSERT INTO t VALUES (1), (2)")
    try:
        cur = con.execute("SELECT * FROM from_substrait_json(?)", [path.read_text()])
        result = {"status": "accepted", "columns": [[d[0], str(d[1])] for d in cur.description],
                  "rows": sorted([list(row) for row in cur.fetchall()])}
    except duckdb.NotImplementedException as exc:
        result = {"status": "unsupported", "error": str(exc)}
    except duckdb.Error as exc:
        result = {"status": "error", "error": str(exc)}
    print(json.dumps({**result, "duckdb": duckdb.__version__, "extension": version}))


def acero_worker(path):
    import pyarrow as pa
    import pyarrow.acero as ac
    import pyarrow.compute as pc
    import pyarrow.substrait as ps

    schema = pa.schema([pa.field("r", pa.int64(), nullable=False),
                        pa.field("n", pa.int64(), nullable=True)])
    table = pa.Table.from_arrays([pa.array([1, 2], type=pa.int64()),
                                 pa.array([None, 3], type=pa.int64())], schema=schema)
    read = json.loads(path.read_text())["relations"][0]["root"]["input"]["read"]
    mapping = read.get("common", {}).get("emit", {}).get("outputMapping")
    indices = list(range(len(schema))) if mapping is None else mapping
    def provider(names, requested):
        if names != ["t"] or not requested.equals(schema):
            raise ValueError("Acero requested a different table or input schema")
        return table

    def describe(value):
        return {"schema": [[f.name, str(f.type), f.nullable] for f in value.schema],
                "rows": [list(row.values()) for row in value.to_pylist()]}

    reader = ps.run_query(path.with_suffix(".bin").read_bytes(),
                          table_provider=provider, use_threads=False)
    reader_schema = reader.schema
    result = reader.read_all()
    if not reader_schema.equals(result.schema):
        raise ValueError("Acero reader and materialized table have different schemas")

    native = ac.Declaration("table_source", ac.TableSourceNodeOptions(table))
    if mapping is not None:
        names = [schema[i].name for i in indices]
        native = ac.Declaration("project", ac.ProjectNodeOptions(
            [pc.field(i) for i in indices], names), inputs=[native])
    print(json.dumps({"status": "accepted", "pyarrow": pa.__version__,
                      "substrait": describe(result),
                      "native": describe(native.to_table(use_threads=False)),
                      "table_select": describe(table.select(indices))}))


def explain_roundtrip(path, expected):
    command = [os.environ.get("SUBSTRAIT_EXPLAIN", "substrait-explain"), "convert"]
    formatted = subprocess.run(command + ["-i", str(path), "-f", "json", "-t", "text"],
                               capture_output=True, text=True, timeout=30)
    if formatted.returncode:
        raise RuntimeError(f"{path.stem}: formatter failed: {formatted.stderr.strip()}")
    parsed = subprocess.run(command + ["-f", "text", "-t", "json"], input=formatted.stdout,
                            capture_output=True, text=True, timeout=30)
    if parsed.returncode:
        if "panicked at" in parsed.stderr:
            return {"status": "crash", "stage": "parse", "returncode": parsed.returncode}, False
        raise RuntimeError(f"{path.stem}: parser failed: {parsed.stderr.strip()}")
    root = json.loads(parsed.stdout)["relations"][0]["root"]
    schema = root["input"]["read"]["baseSchema"]
    observed = {"status": "accepted", "schema": schema, "names": root["names"]}
    return observed, schema == expected["schema"] and root["names"] == expected["names"]


def run_case(engine, name, expected, env):
    path = CASES / engine / (name + ".json")
    if engine == "explain":
        observed, matches = explain_roundtrip(path, expected)
        return {"case": name, "matches": matches, "control": expected["control"],
                "observed": observed}
    elif engine == "spark":
        command = ["bash", str(PROBE / "spark_run.sh"), "SparkSchemaOf", str(path)]
    elif engine == "duckdb":
        command = [str(env / "venv/bin/python"), str(PROBE / "structural_cases.py"),
                   "--duck-worker", str(path)]
    elif engine == "acero":
        command = [str(env / "venv/bin/python"), str(PROBE / "structural_cases.py"),
                   "--acero-worker", str(path)]
    elif engine == "go":
        command = [str(env / "gosub9/probe_go9"), str(path.with_suffix(".bin"))]
    else:
        val = Path(os.environ.get("SUBSTRAIT_VALIDATOR_ENV", str(env / "val")))
        command = [str(val / "bin/python"), str(PROBE / "validator_one.py"), str(path)]
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=90 if engine == "spark" else 30)
    if result.returncode:
        # Go uses exit 2 for an unrecovered panic. C++ crashes terminate on a signal.
        if result.returncode < 0 or (engine == "go" and result.stderr.startswith("panic:")):
            observed = {"status": "crash", "returncode": result.returncode}
        else:
            raise RuntimeError(f"{name}: probe failed: {result.stderr.strip()}")
        matches = False
    elif engine == "spark":
        lines = [line[len(name):].strip() for line in result.stdout.splitlines()
                 if line.startswith(name + " ")]
        if len(lines) != 1 or not lines[0].startswith("[") or not lines[0].endswith("]"):
            raise RuntimeError(f"{name}: Spark did not produce one schema: {result.stdout}")
        observed = {"status": "accepted", "schema": lines[0]}
        matches = observed["schema"] == expected["schema"]
    elif engine == "duckdb":
        observed = json.loads(result.stdout)
        matches = (observed["status"] == "unsupported" and expected["allow_unsupported"])
        if observed["status"] == "accepted":
            matches = (observed["columns"] == expected["columns"]
                       and observed["rows"] == expected["rows"])
    elif engine == "acero":
        observed = json.loads(result.stdout)
        want = {"schema": expected["schema"], "rows": expected["rows"]}
        # Table.select is an independent control for the same input and mapping.
        # Values must agree even when the output schema loses requiredness.
        if observed["table_select"] != want or any(
                observed[key]["rows"] != expected["rows"] for key in ("substrait", "native")):
            raise RuntimeError(f"{name}: input/mapping control or row comparison failed")
        matches = observed["substrait"] == want and observed["native"] == want
    elif engine == "go":
        accepted = "SUBSTRAITGO ACCEPTED  "
        if result.stdout.startswith(accepted):
            observed = {"status": "accepted", "schema": result.stdout[len(accepted):].strip()}
            matches = observed["schema"] == expected["schema"]
        elif result.stdout.startswith("SUBSTRAITGO REJECTED"):
            observed = {"status": "rejected", "error": result.stdout.strip()}
            matches = False
        else:
            raise RuntimeError(f"{name}: unrecognized Go output")
    else:
        lines = result.stdout.splitlines()
        schemas = [line.removeprefix("VALIDATOR SCHEMA    ") for line in lines
                   if line.startswith("VALIDATOR SCHEMA    ")]
        if len(schemas) != 1:
            raise RuntimeError(f"{name}: validator did not produce one schema: {result.stdout}")
        errors = [line for line in lines if line.startswith("VALIDATOR ERROR")]
        observed = {"status": "rejected" if errors else "accepted", "schema": schemas[0]}
        if errors:
            observed["error"] = errors[0]
        matches = not errors and schemas[0] == expected["schema"]
    return {"case": name, "matches": matches, "control": expected["control"],
            "observed": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=["duckdb", "go", "validator", "explain", "spark", "acero"], nargs="?")
    parser.add_argument("--check", action="store_true", help="fail if any case differs")
    parser.add_argument("--verify-fixtures", action="store_true", help="check fixture inventory without running engines")
    parser.add_argument("--duck-worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--acero-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.duck_worker:
        duck_worker(args.duck_worker)
        return
    if args.acero_worker:
        acero_worker(args.acero_worker)
        return
    groups = load_cases()
    if args.verify_fixtures:
        print(json.dumps({"fixture_cases": sum(len(cases) for cases in groups.values())}))
        return
    if not args.engine:
        parser.error("engine is required")
    env = Path(os.environ.get("SUBSTRAIT_PROBE_ENV", str(PROBE.parent / ".probe-env")))
    cases = groups[args.engine]
    results = []
    for name, expected in cases.items():
        result = run_case(args.engine, name, expected, env)
        results.append(result)
        print(json.dumps(result), flush=True)
    differences = sum(not r["matches"] for r in results)
    failed_controls = sum(r["control"] and not r["matches"] for r in results)
    print(json.dumps({"engine": args.engine, "cases": len(results), "differences": differences,
                      "failed_controls": failed_controls}))
    if failed_controls or (args.check and differences):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
