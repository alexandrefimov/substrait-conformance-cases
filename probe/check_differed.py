"""Checks differed.json against the saved columns.

    python3 probe/check_differed.py

differed.json says, per participant and case, why the answer differs: a limit of that type system,
a type the participant never resolved, or a divergence. Those are judgements written by hand, so
what can be checked is that they describe this run and no other - every differing cell classified,
nothing classified that no longer differs - and, where a reason makes a claim a machine can test,
that the claim holds. A reason carries that test in its own `check` field:

    nullable_only   the answer has the expected types and every field nullable
    got_matches     the raw answer matches this regular expression

Without any of this the file would drift into describing a measurement that has moved, and would
be more misleading than no file at all.
"""
import io, json, os, re, subprocess, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COLS = [("PYTHON", "py"), ("GO", "go"), ("VALIDATOR", "py"), ("ISTHMUS", "calcite"),
        ("DATAFUSION", "df"), ("DUCKDB", "duckdb"), ("SPARK", "spark"), ("ACERO", "acero")]

# check_expected.py is a script, not a module: it reads sys.argv at import time. Its parsers are
# taken by running the source down to that line, so the two files cannot disagree about what an
# answer means.
src = io.open(os.path.join(ROOT, "probe/check_expected.py"), encoding="utf-8").read()
P = {"__file__": os.path.join(ROOT, "probe/check_expected.py")}
exec(src[:src.index("path, fmt = sys.argv")], P)
PARSE = {"java": "parse_java", "py": "parse_py", "df": "parse_df", "duckdb": "parse_duckdb",
         "acero": "parse_acero", "go": "parse_go", "spark": "parse_spark", "calcite": "parse_calcite"}

doc = json.load(open(os.path.join(ROOT, "differed.json"), encoding="utf-8"))
expected = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))["expected"]
bad = 0

def fail(msg):
    global bad
    print("FAILED: " + msg)
    bad = 1

def answers(name):
    out, in_header = {}, True
    for line in io.open(os.path.join(ROOT, "results/%s.txt" % name), encoding="utf-8"):
        line = line.rstrip()
        if in_header:
            in_header = bool(line)
            continue
        if line:
            case, _, value = line.partition(" ")
            out[case.strip()] = value.strip()
    return out

for rid, r in doc["rules"].items():
    if r["kind"] not in doc["kinds"]:
        fail("rule %s has an unknown kind %r" % (rid, r["kind"]))

total = 0
for col, fmt in COLS:
    out = subprocess.run([sys.executable, os.path.join(ROOT, "probe/check_expected.py"),
                          os.path.join(ROOT, "results/%s.txt" % col), fmt],
                         capture_output=True, text=True).stdout.splitlines()
    differing = {m.group(1) for m in (re.match(r"^  (\S+)\s+expected ", l) for l in out) if m}
    said = doc["cells"].get(col, {})
    missing, extra = sorted(differing - set(said)), sorted(set(said) - differing)
    if missing:
        fail("%s: %d differing cells with no reason: %s" % (col, len(missing), ", ".join(missing[:4])))
    if extra:
        fail("%s: %d classified cells that no longer differ: %s" % (col, len(extra), ", ".join(extra[:4])))
    total += len(differing)

    data = answers(col)
    for case in sorted(set(said) & differing):
        rule = doc["rules"].get(said[case])
        if rule is None:
            fail("%s/%s names rule %r, which is not defined" % (col, case, said[case]))
            continue
        check = rule.get("check")
        if not check:
            continue
        got_raw = data[case]
        if "got_matches" in check and not re.search(check["got_matches"], got_raw):
            fail("%s/%s says %s, whose answer should match %s: %s"
                 % (col, case, said[case], check["got_matches"], got_raw))
        if check.get("nullable_only"):
            got = P[PARSE[fmt]](got_raw)
            want = expected[case]["schema"]
            if got is None or [t for t, _ in got] != [t for t, _ in want]:
                fail("%s/%s says %s - the expected types with nullability lost - but the types "
                     "differ too: %s against %s" % (col, case, said[case], got, want))
            elif not all(n for _, n in got):
                fail("%s/%s says %s, but not every field of the answer is nullable: %s"
                     % (col, case, said[case], got_raw))

kinds, checked = {}, 0
for cs in doc["cells"].values():
    for rid in cs.values():
        k = doc["rules"].get(rid, {})
        kinds[k.get("kind")] = kinds.get(k.get("kind"), 0) + 1
        checked += 1 if k.get("check") else 0
filed = sum(1 for r in doc["rules"].values() if re.search(r"[Ff]iled as", r["what"]))

# The README puts these counts in prose, where nothing would notice them going stale.
WORD = {6: "six", 8: "eight", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
        14: "fourteen", 17: "seventeen"}
readme = " ".join(io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read().split())
for sentence in ("gives all %d of them a reason and marks %d as something other than"
                 % (total, total - kinds.get("divergence", 0)),
                 "%s are limits of a type system, %s a type the validator never resolved"
                 % (WORD.get(kinds.get("boundary")), WORD.get(kinds.get("unresolved"))),
                 "%s of its %s reasons name an issue" % (WORD.get(filed), WORD.get(len(doc["rules"])))):
    if sentence not in readme:
        fail("the README does not say %r" % sentence)

if not bad:
    print("ok      %d differing cells, %d reasons (%d naming an issue), %s; %d cells machine-checked"
          % (total, len(doc["rules"]), filed,
             ", ".join("%s %d" % kv for kv in sorted(kinds.items())), checked))
raise SystemExit(bad)
