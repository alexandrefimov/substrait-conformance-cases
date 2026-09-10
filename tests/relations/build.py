"""Compile every case to its bundle, and refresh the coverage baseline.

The bundle is what a consumer reads: one serialised `substrait.test.RelationTestCase`
per case, committed so that reading the corpus needs protobuf bindings and nothing
else. `--check` (the default) reports what would change; `--write` writes it.

    python3 tests/relations/build.py --check
    python3 tests/relations/build.py --write
"""

import json
import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from tests.relations.lib import gate, paths


def main(argv):
    write = "--write" in argv
    if not paths.bindings_available():
        print("protobuf bindings are absent; run tests/relations/bootstrap.sh first")
        return 2

    ext = paths.extensions_dir()
    changed, failed, coverage = [], [], gate.Counter()
    for path in gate.case_files():
        try:
            case = gate.Case(path, ext)
        except Exception as e:
            failed.append(
                (os.path.relpath(path, paths.RELATIONS), f"{type(e).__name__}: {e}")
            )
            continue
        gate.coverage(case.plan, coverage)
        out = os.path.join(paths.bundles_dir(), case.area, case.name + ".pb")
        old = open(out, "rb").read() if os.path.exists(out) else None
        if old != case.blob:
            changed.append(os.path.relpath(out, paths.RELATIONS))
            if write:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                open(out, "wb").write(case.blob)

    baseline = paths.baseline_path()
    counts = dict(sorted(coverage.items()))
    old = json.load(open(baseline)) if os.path.exists(baseline) else None
    if old != counts:
        changed.append(os.path.relpath(baseline, paths.RELATIONS))
        if write:
            with open(baseline, "w") as f:
                json.dump(counts, f, indent=1)
                f.write("\n")

    for name, why in failed:
        print(f"  {name}: {why}")
    verb = "wrote" if write else "would change"
    print(
        f"{len(gate.case_files())} cases, {len(failed)} failed to compile, "
        f"{verb} {len(changed)} files"
    )
    for c in changed[:20]:
        print(f"    {c}")
    return 1 if failed or (changed and not write) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
