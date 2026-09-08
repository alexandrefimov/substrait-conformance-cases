"""Run an explicit Spark runtime profile separately from the saved nine-column matrix.

Requires JDK 17 in JAVA_HOME (or JAVA17_HOME). Builds a fresh classpath and consumer
output directory. Differences are observations; broken controls, missing answers,
build failures and incorrect runtime identity fail the run. See probe/README.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse

PROBE = Path(__file__).resolve().parent
ROOT = PROBE.parent


def profiles():
    data = json.loads((PROBE / "spark-runtimes.json").read_text())
    if not data or any(not re.fullmatch(r"[34]\.\d+\.\d+", version)
                       or module != ("spark-3.5_2.12" if version.startswith("3.")
                                     else "spark-4.0_2.13")
                       for version, module in data.items()):
        raise ValueError("invalid Spark runtime profiles")
    return data


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def run(command, out, name, env, cwd=ROOT, allowed=(0,), timeout=1800):
    """Keep output even when the command fails or times out."""
    stdout = out / (name + ".txt")
    with stdout.open("w") as output, (out / (name + ".log")).open("w") as errors:
        result = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env,
                                stdout=output, stderr=errors, timeout=timeout)
    if result.returncode not in allowed:
        raise RuntimeError(f"{name} failed ({result.returncode}); see {name}.txt and {name}.log")
    return stdout


def input_hashes():
    paths = [ROOT / "expected.json", ROOT / "results/SPARK.txt"]
    paths += list((ROOT / "derived-schema").glob("*.json"))
    paths += [p for p in PROBE.iterdir() if p.suffix in (".py", ".sh", ".java", ".gradle", ".env")]
    paths += [PROBE / "spark-runtimes.json", PROBE / "structural-cases/expected.json"]
    paths += list((PROBE / "structural-cases/spark").glob("*.json"))
    paths += [ROOT / "gen/make_classpath.sh", ROOT / "gen/cp.init.gradle"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def column_answers(path, names):
    body = path.read_text().split("\n\n", 1)[1]
    answers = {}
    for line in body.splitlines():
        name, answer = line.split(None, 1)
        if name in answers:
            raise ValueError(f"{path.name}: duplicate answer for {name}")
        answers[name] = answer
    if set(answers) != set(names):
        raise ValueError(f"{path.name}: missing or unexpected corpus cases")
    return answers


def diagnostics(path, expected):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    results, summary = rows[:-1], rows[-1]
    if len(results) != len(expected) or {r["case"] for r in results} != set(expected):
        raise ValueError(f"{path.name}: incomplete or duplicate diagnostic cases")
    if any(type(r["matches"]) is not bool or type(r["control"]) is not bool
           or r["control"] != expected[r["case"]] for r in results):
        raise ValueError(f"{path.name}: malformed diagnostic verdict or control")
    actual = {"cases": len(results), "differences": sum(not r["matches"] for r in results),
              "failed_controls": sum(r["control"] and not r["matches"] for r in results)}
    if any(summary.get(k) != v for k, v in actual.items()) or actual["failed_controls"]:
        raise ValueError(f"{path.name}: inconsistent summary or failed control")
    return actual


def verify_identity(identity, dependencies, version, module, cache):
    scala = module.rsplit("_", 1)[1]
    spark = [a for a in dependencies if a["group"] == "org.apache.spark"]
    if (identity["spark"] != version or not spark
            or any(a["version"] != version for a in spark)
            or not identity["scala"].startswith(scala + ".")
            or not identity["java"].startswith("17.")
            or type(identity["ansi_default"]) is not bool
            or not identity["substrait_spec"]):
        raise ValueError("the loaded runtime does not match the requested Spark/Scala/JDK profile")
    consumer = Path(unquote(urlparse(identity["consumer_loaded_from"]).path)).resolve()
    if consumer != (cache / "consumer-build/classes/scala/main").resolve():
        raise ValueError("consumer was not loaded from the fresh profile build")
    loaded = Path(unquote(urlparse(identity["spark_loaded_from"]).path))
    if loaded.name != f"spark-catalyst_{scala}-{version}.jar":
        raise ValueError("Spark SQLConf was loaded from an unexpected jar")


def execute(args, out):
    version, module = args.version, profiles()[args.version]
    versions = PROBE / ("versions-latest.env" if args.latest else "versions.env")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SUBSTRAIT_", "SPARK_", "PROBE_"))
           and k not in ("SETUP_ONLY", "LATEST", "SJ_EXPECT", "CLASSPATH", "JAVA_TOOL_OPTIONS",
                         "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS")}
    jdk = env.get("JAVA17_HOME") or env.get("JAVA_HOME")
    if not jdk or not (Path(jdk) / "bin/javac").is_file():
        raise ValueError("set JAVA_HOME or JAVA17_HOME to a JDK 17 installation")
    env.update(JAVA_HOME=jdk, JAVA17_HOME=jdk, PATH=str(Path(jdk) / "bin") + os.pathsep + env["PATH"])
    # Source the existing version registry rather than keeping a second Java revision pin.
    reference = subprocess.check_output(
        ["bash", "-c", '. "$1"; printf "%s" "$SUBSTRAIT_JAVA_COMMIT"', "bash", str(versions)],
        env=env, text=True)
    record = {"spark_requested": version, "consumer_module": module,
              "java_reference": reference, "corpus_commit": git(ROOT, "rev-parse", "HEAD"),
              "corpus_dirty": bool(git(ROOT, "status", "--porcelain")),
              "inputs_sha256": input_hashes()}
    write_json(out / "record.json", record)
    with tempfile.TemporaryDirectory(prefix="substrait-spark-") as temporary:
        cache = Path(temporary)
        env.update(SUBSTRAIT_VERSIONS=str(versions), SETUP_ONLY="substrait-java",
                   SUBSTRAIT_PROBE_ENV=str(cache), PROBE_CACHE=str(cache),
                   SUBSTRAIT_CLASSPATH=str(cache / "core_cp.txt"))
        sj = args.java_dir.resolve() if args.java_dir else cache / "substrait-java"
        if args.java_dir:
            env["SUBSTRAIT_JAVA_DIR"] = str(sj)
            if git(sj, "status", "--porcelain"):
                raise ValueError("the supplied substrait-java checkout has source changes or untracked files")
            if args.latest:
                raise ValueError("--latest uses a fresh clone; omit --java-dir")
            if git(sj, "rev-parse", "HEAD") != git(sj, "rev-parse", reference + "^{commit}"):
                raise ValueError("the supplied checkout is not at the pinned Java commit")
        run(["bash", PROBE / "setup.sh", cache], out, "setup", env)
        env["SUBSTRAIT_JAVA_DIR"] = str(sj)
        revision = git(sj, "rev-parse", "HEAD")
        if revision != git(sj, "rev-parse", reference + "^{commit}"):
            raise ValueError("setup produced the wrong Java revision")
        record["java_commit"] = revision
        write_json(out / "record.json", record)
        run([sj / "gradlew", "-I", PROBE / "spark_runtime.init.gradle",
             "-PcorpusSparkModule=" + module, "-PcorpusSparkVersion=" + version,
             "-PcorpusSparkOutput=" + str(cache), ":spark:" + module + ":writeCorpusSparkClasspath"],
            out, "build", env, cwd=sj)
        shutil.copyfile(cache / "dependencies.json", out / "dependencies.json")
        identity_path = run(["bash", PROBE / "spark_run.sh", "SparkRuntimeIdentity"],
                            out, "runtime-identity", env, timeout=120)
        identity = json.loads(identity_path.read_text())
        verify_identity(identity, json.loads((out / "dependencies.json").read_text()),
                        version, module, cache)
        # Local paths prove class loading above; the durable identity needs only versions.
        record["runtime"] = {k: v for k, v in identity.items() if not k.endswith("_loaded_from")}
        write_json(out / "record.json", record)
        names = {p.stem for p in (ROOT / "derived-schema").glob("*.json") if p.name != "manifest.json"}
        answers, summaries = {}, {}
        for ansi in (False, True):
            label = "ansi-on" if ansi else "ansi-off"
            mode_env = dict(env)
            if ansi:
                mode_env["SPARK_ANSI"] = "1"
            raw = run(["bash", PROBE / "spark_all.sh"], out, label + "-raw", mode_env, timeout=300)
            column = run([sys.executable, PROBE / "normalize.py", raw, "line",
                          f"SPARK: runtime {version}, ANSI {str(ansi).lower()}, Java {revision}"],
                         out, label, env)
            answers[label] = column_answers(column, names)
            check = run([sys.executable, PROBE / "check_expected.py", column, "spark"],
                        out, label + "-expected", env, allowed=(0, 1))
            text = check.read_text()
            if "INCOMPLETE:" in text or "unparsed by the check: 0," not in text:
                raise ValueError(f"{label}: expectation comparison is incomplete or unparsed")
            summaries[label] = text.splitlines()[-1]
            run([sys.executable, PROBE / "column_diff.py", ROOT / "results/SPARK.txt", column],
                out, label + "-saved-diff", env, allowed=(0, 1))
        overflow = run([sys.executable, PROBE / "spark_function_options.py"], out, "overflow", env)
        expected = {f"{fn}_{kind}_ansi_{ansi}": kind == "safe"
                    for fn in ("add", "multiply") for kind in ("safe", "overflow")
                    for ansi in ("false", "true")}
        overflow_summary = diagnostics(overflow, expected)
        decimal = run([sys.executable, PROBE / "structural_cases.py", "spark"], out, "decimal", env)
        expected = json.loads((PROBE / "structural-cases/expected.json").read_text())["spark"]
        decimal_summary = diagnostics(decimal, {k: v["control"] for k, v in expected.items()})
        if git(sj, "rev-parse", "HEAD") != revision or git(sj, "status", "--porcelain"):
            raise ValueError("the Java checkout changed during the run")
        if input_hashes() != record["inputs_sha256"]:
            raise ValueError("corpus inputs changed during the run")
        summary = {"runtime": record["runtime"], "corpus_cases_per_mode": len(names),
                   "schemas": summaries, "overflow": overflow_summary, "decimal": decimal_summary,
                   "ansi_changed_cases": sorted(n for n in names
                                                if answers["ansi-off"][n] != answers["ansi-on"][n])}
        write_json(out / "summary.json", summary)
        report = [f"Spark {version} / {module}", f"substrait-java: {revision}",
                  f"Corpus: {len(names)} cases in each ANSI mode", "",
                  *[f"{mode}: {value}" for mode, value in summaries.items()], "",
                  f"Overflow: {overflow_summary}", f"Decimal (ANSI off): {decimal_summary}",
                  "ANSI changed cases: " + ", ".join(summary["ansi_changed_cases"]), "",
                  "Differences are observations. Controls, completeness and runtime identity passed.",
                  "See *-saved-diff.txt for changes from the saved Spark column."]
        (out / "summary.txt").write_text("\n".join(report) + "\n")
        print("\n".join(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", choices=profiles())
    parser.add_argument("--list", action="store_true", help="print the JSON version list for CI")
    parser.add_argument("--out", type=Path, help="new or empty directory for logs and results")
    parser.add_argument("--java-dir", type=Path, help="reuse a clean checkout at the pinned Java revision")
    parser.add_argument("--latest", action="store_true", help="build today's Java main at the explicit Spark version")
    args = parser.parse_args()
    if args.list:
        print(json.dumps(list(profiles())))
        return
    if not args.version or not args.out:
        parser.error("version and --out are required")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("--out must be new or empty; old results must not survive a failed run")
    out.mkdir(parents=True, exist_ok=True)
    try:
        execute(args, out)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError) as exc:
        write_json(out / "failure.json", {"error": str(exc)})
        parser.exit(1, f"Spark runtime profile failed: {exc}\nArtifacts: {out}\n")


if __name__ == "__main__":
    main()
