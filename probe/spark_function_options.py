"""Check decimal overflow options through the Spark expression importer.

Uses spark_run.sh and the same JDK 17 / substrait-java setup as SparkSchemaOf.
Safe-value controls must pass. --check also fails on ignored overflow options.
These evaluated expressions are separate from the saved schema matrix.
"""
import argparse
import json
from pathlib import Path
import subprocess

PROBE = Path(__file__).resolve().parent


def check_results(output):
    expected = {(function, ansi, kind) for function in ("add", "multiply")
                for ansi in (False, True) for kind in ("safe", "overflow")}
    seen = set()
    results = []
    for line in output.splitlines():
        observed = json.loads(line)
        key = (observed["function"], observed["ansi"], observed["input"])
        if type(observed["ansi"]) is not bool or key not in expected or key in seen:
            raise ValueError("unexpected or duplicate Spark function case")
        seen.add(key)
        function, ansi, kind = key
        control = kind == "safe"
        options = [] if control else [{"name": "overflow", "values": ["ERROR"]}]
        if observed["options"] != options:
            raise ValueError("the function passed to Spark has unexpected options")
        status = observed["status"]
        if status not in ("value", "overflow_error", "rejected"):
            raise ValueError("unrecognized Spark evaluation status")
        if status != "rejected":
            if not isinstance(observed.get("type"), str) or not observed["type"]:
                raise ValueError("missing Spark output type")
            if type(observed.get("nullable")) is not bool:
                raise ValueError("missing Spark output nullability")
        if status == "value":
            value = observed["value"]
            if value is not None and not isinstance(value, str):
                raise ValueError("unexpected Spark value encoding")
        elif not isinstance(observed.get("error"), str) or not observed["error"]:
            raise ValueError("missing Spark error class")
        if control:
            dtype, value = (("decimal(11,2)", "4.00") if function == "add"
                            else ("decimal(16,3)", "3.000"))
            matches = (status == "value" and observed["type"] == dtype
                       and observed["value"] == value)
        else:
            # Explicit ERROR may be honored at evaluation or rejected during conversion.
            matches = status in ("overflow_error", "rejected")
        results.append({"case": f"{function}_{kind}_ansi_{str(ansi).lower()}",
                        "control": control, "matches": matches, "observed": observed})
    if seen != expected:
        raise ValueError("Spark did not report all eight function cases")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any case differs")
    args = parser.parse_args()
    run = subprocess.run(["bash", str(PROBE / "spark_run.sh"), "SparkFunctionOptions"],
                         capture_output=True, text=True, timeout=120)
    if run.returncode:
        raise RuntimeError(f"Spark function probe failed: {run.stderr.strip()}")
    results = check_results(run.stdout)
    for result in results:
        print(json.dumps(result))
    differences = sum(not result["matches"] for result in results)
    failed_controls = sum(result["control"] and not result["matches"] for result in results)
    print(json.dumps({"cases": len(results), "differences": differences,
                      "failed_controls": failed_controls}))
    if failed_controls or (args.check and differences):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
