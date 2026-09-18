"""Checks the saved deriver answers against the saved expectations, and nothing else.

    python3 deriver/check.py           # the tally, and every difference in full
    python3 deriver/check.py --quiet   # names only what is wrong

Deriving an answer needs a Substrait checkout; comparing two files here does not, which is why the
answers are saved. This runs in probe/selfcheck.sh, where the rule is that every fact checked is
one file in this repository against another.

What it establishes is narrow and worth saying exactly. `probe/expected.py` writes an expectation
by hand, case by case, from the specification. `deriver/` computes one from the plan, from the same
specification, by rules written separately. Where the two agree, one sentence of the specification
has been read twice and the readings match. Where they differ, one of the two is wrong or the
sentence does not decide the question. It does not establish that either reading is right.
"""
import json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HERE = os.path.dirname(os.path.abspath(__file__))
COLUMN = os.path.join(HERE, "DERIVED.txt")
PINS = os.path.join(HERE, "spec.pins")


def split_fields(text):
    """The columns of `[i64, struct(i64,i64?), dec(11,2)]`, splitting only at the top level."""
    out, depth, current = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        out.append(current.strip())
    return out


def read_column(path):
    """The saved answers, and the pins the header records, as (answers, pins)."""
    answers, pins = {}, {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#"):
            parts = line[1:].split()
            if len(parts) == 2:
                pins[parts[1]] = parts[0]
            continue
        if not line.strip() or line.startswith("DERIVER:"):
            continue
        name, _, answer = line.partition(" ")
        answers[name] = answer.strip()
    return answers, pins


def parse_schema(answer):
    """`[str, i64?]` as [["str", False], ["i64", True]], or None when the deriver declined."""
    if not answer.startswith("["):
        return None
    inner = answer[1:answer.rindex("]")]
    return [[f.rstrip("?"), f.endswith("?")] for f in split_fields(inner)] if inner.strip() else []


def main(argv):
    quiet = "--quiet" in argv
    failed = 0
    doc = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))
    expected, disputed = doc["expected"], doc["disputed"]
    unscored = set(doc["spec_silent"]) | set(doc["spec_says_invalid"])
    manifest = json.load(open(os.path.join(ROOT, "derived-schema", "manifest.json"),
                              encoding="utf-8"))
    answers, pins = read_column(COLUMN)

    # The header says which extension files the answers came from. If that has drifted from
    # deriver/spec.pins, the saved column and the program that would regenerate it are reading
    # different text, and the comparison below would be against neither.
    declared = {}
    for line in open(PINS, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line:
            sha, path = line.split()
            declared[path] = sha
    if pins != declared:
        print("FAILED: DERIVED.txt was derived from %s, deriver/spec.pins names %s"
              % (sorted(pins.items()), sorted(declared.items())))
        failed = 1

    # COVERAGE.txt is written by deriver/mutants.py, which needs a checkout; what can be checked
    # here is that it still describes the same set of readings the script tries. A mutation added
    # without regenerating the map would otherwise leave the map claiming coverage it never tested.
    failed |= _coverage_matches_mutants()
    failed |= _pinned_matches(expected)
    failed |= _mutations_still_apply()

    cases = [e["case"] for e in manifest]
    missing = [c for c in cases if c not in answers]
    extra = [c for c in answers if c not in cases]
    if missing or extra:
        print("FAILED: DERIVED.txt and the manifest name different cases: missing %s, extra %s"
              % (missing, extra))
        failed = 1

    agree, differ, declined, unmeasured = [], [], [], []
    for case in cases:
        answer = answers.get(case)
        if answer is None:
            continue
        got = parse_schema(answer)
        if case not in expected:
            (unmeasured if case in unscored or case in disputed else differ).append(
                (case, got, None, "no expectation and not recorded as unscored"))
            continue
        want = [[t, bool(n)] for t, n in expected[case]["schema"]]
        if got is None:
            declined.append((case, None, want, answer))
        elif got == want:
            agree.append(case)
        else:
            differ.append((case, got, want, expected[case].get("source", "")))

    if differ:
        failed = 1
        print("FAILED: %d derived schemas differ from the expectation" % len(differ))
    if not quiet:
        print("%d cases: agree %d, differ %d, declined %d, no expectation %d"
              % (len(cases), len(agree), len(differ), len(declined), len(unmeasured)))
    for case, got, want, source in differ:
        print("  %s\n    derived  %s\n    expected %s\n    from     %s"
              % (case, render(got), render(want), source))
    if declined and not quiet:
        print("declined (%d):" % len(declined))
        for case, _, _, why in declined:
            print("  %-46s %s" % (case, why))
    if unmeasured and not quiet:
        print("no expectation to compare against (%d):" % len(unmeasured))
        for case, got, _, _ in unmeasured:
            print("  %-46s %s" % (case, render(got)))
    return failed


def _coverage_matches_mutants():
    """Every reading COVERAGE.txt reports is one deriver/mutants.py still tries, and the reverse."""
    import re
    listed = set()
    for line in open(os.path.join(HERE, "COVERAGE.txt"), encoding="utf-8"):
        m = re.match(r"^  (\S.*?)\s+\d+ case\(s\):", line) or re.match(r"^  ([a-z].*)$", line)
        if m and not line.strip().startswith("the other reading:"):
            listed.add(m.group(1).strip())
    source = open(os.path.join(HERE, "mutants.py"), encoding="utf-8").read()
    tried = set(re.findall(r'^\s*\("[a-z_]+\.py", "([^"]+)",', source, re.M))
    if listed != tried:
        print("FAILED: deriver/COVERAGE.txt and deriver/mutants.py name different readings: "
              "only in the map %s, only in the script %s"
              % (sorted(listed - tried)[:3], sorted(tried - listed)[:3]))
        return 1
    return 0


def _mutations_still_apply():
    """Every mutation in deriver/mutants.py still finds the text it replaces.

    Running the probe needs a Substrait checkout, so a rule renamed or reworded in deriver/ would
    otherwise leave COVERAGE.txt and PINNED.txt standing as measurements of code that no longer
    exists, and the page would keep drawing dots from them. The replacement text is a literal, so
    whether it is still there is a question this repository can answer about itself.
    """
    import ast
    source = open(os.path.join(HERE, "mutants.py"), encoding="utf-8").read()
    tree = ast.parse(source)
    table = next((n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "MUTATIONS" for t in n.targets)), None)
    if table is None:
        print("FAILED: deriver/mutants.py no longer defines MUTATIONS as a literal table")
        return 1
    failed = 0
    for entry in table.elts:
        parts = [ast.literal_eval(e) for e in entry.elts]
        where, label, _, old = parts[0], parts[1], parts[2], parts[3]
        body = open(os.path.join(HERE, where), encoding="utf-8").read()
        if old not in body:
            print("FAILED: deriver/mutants.py replaces text %s no longer has, for %r"
                  % (where, label))
            failed = 1
    return failed


def _pinned_matches(expected):
    """deriver/PINNED.txt covers exactly the scored cases, and names only readings that exist.

    The page draws a dot from this file and says in prose how many cases carry one. Regenerating it
    needs a checkout, so what is checked here is that it still describes this corpus: a case added
    without rerunning the probe would otherwise be drawn as pinning nothing, which is a claim, not
    an absence.
    """
    import re
    listed, sole = set(), set()
    for line in open(os.path.join(HERE, "PINNED.txt"), encoding="utf-8"):
        m = re.match(r"^(\S+)\s+(\d+)(?:\s+-> (.+))?$", line.rstrip())
        if not m:
            continue
        listed.add(m.group(1))
        if m.group(3):
            sole.update(r.strip() for r in m.group(3).split(";"))
    failed = 0
    if listed != set(expected):
        print("FAILED: deriver/PINNED.txt covers %d cases, expected.json scores %d: only in the "
              "file %s, only scored %s"
              % (len(listed), len(expected), sorted(listed - set(expected))[:3],
                 sorted(set(expected) - listed)[:3]))
        failed = 1
    source = open(os.path.join(HERE, "mutants.py"), encoding="utf-8").read()
    tried = set(re.findall(r'^\s*\("[a-z_]+\.py", "([^"]+)",', source, re.M))
    unknown = sole - tried
    if unknown:
        print("FAILED: deriver/PINNED.txt names readings deriver/mutants.py does not try: %s"
              % sorted(unknown)[:3])
        failed = 1
    return failed


def render(schema):
    if schema is None:
        return "-"
    return "[%s]" % ", ".join(t + ("?" if n else "") for t, n in schema)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
