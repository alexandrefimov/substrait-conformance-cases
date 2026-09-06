"""Checks differed.json against the saved columns.

    python3 probe/check_differed.py

differed.json says, per participant and case, why the answer differs: a limit of that type system,
a type the participant never resolved, or a divergence. Those are judgements written by hand, so
what can be checked is that they describe this run and no other - every differing cell classified,
nothing classified that no longer differs - and, where a reason makes a claim a machine can test,
that the claim holds. A reason carries that test in its own `check` field:

    nullable_only          the answer has the expected types and every field nullable
    got_matches            the raw answer matches this regular expression
    no_field_nullable      no field of the answer is nullable
    all_decimal            every field of the answer is a decimal
    inputs_concatenated    the answer is the relation's inputs one after another, with their own
                           nullability; `mark_suffix` allows one trailing boolean
    first_input            the answer is the first input, types and nullability alike; `leading`
                           allows it to stop short, matching only the columns the input starts with
    nullable_if_any_input  the answer has a nullable field wherever any input does

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

# The inputs of the relation under test, in the order the plan declares them. Reading them from the
# case rather than restating them here is the point: a reason that says "the inputs concatenated" is
# then checked against the inputs, not against a copy of them that can go stale on its own.
PROTO_TYPE = {"i64": "i64", "i32": "i32", "i16": "i16", "i8": "i8", "bool": "bool", "string": "str",
              "fp64": "fp64", "fp32": "fp32", "binary": "bin", "date": "date"}

def case_inputs(case):
    plan = json.load(open(os.path.join(ROOT, "derived-schema/%s.json" % case), encoding="utf-8"))
    found = []
    def walk(node):
        if isinstance(node, dict):
            schema = node.get("baseSchema")
            if schema:
                fields = []
                for t in schema["struct"]["types"]:
                    (kind, body), = t.items()
                    if kind not in PROTO_TYPE:
                        raise KeyError("%s: unmapped proto type %r" % (case, kind))
                    fields.append([PROTO_TYPE[kind],
                                   body.get("nullability") == "NULLABILITY_NULLABLE"])
                found.append(fields)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(plan)
    return found

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
    # Every reason here turned out to be testable once it was stated precisely enough, and the
    # imprecise ones were where the mistakes were: reasons that held for most of their cells and
    # described the rest wrongly. So a reason without a test is refused rather than allowed as an
    # exception - if nothing can be tested about it, it is not yet saying what it observed.
    if not r.get("check"):
        fail("rule %s makes no claim a machine can test" % rid)

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
        if check.get("all_decimal"):
            got = P[PARSE[fmt]](got_raw)
            if got is None or not all(t.startswith("dec(") for t, _ in got):
                fail("%s/%s says %s, but the answer is not a decimal: %s"
                     % (col, case, said[case], got_raw))
        if check.get("no_field_nullable"):
            got = P[PARSE[fmt]](got_raw)
            if got is None or any(n for _, n in got):
                fail("%s/%s says %s, but a field of the answer is nullable: %s"
                     % (col, case, said[case], got_raw))
        if {"inputs_concatenated", "first_input", "nullable_if_any_input"} & set(check):
            try:
                inputs = case_inputs(case)
            except KeyError as e:
                fail("%s/%s says %s, which is read against the case's inputs, and %s"
                     % (col, case, said[case], e.args[0]))
                continue
            got = P[PARSE[fmt]](got_raw)
            if "inputs_concatenated" in check:
                want = [f for one in inputs for f in one]
                tail = got[len(want):] if got else []
                if check["inputs_concatenated"].get("mark_suffix") and tail == [["bool", True]]:
                    got = got[:len(want)]
            elif "first_input" in check:
                want = inputs[0]
                if isinstance(check["first_input"], dict) and check["first_input"].get("leading"):
                    if got and len(got) < len(want):
                        want = want[:len(got)]
            else:
                want = [[t, any(one[i][1] for one in inputs)]
                        for i, (t, _) in enumerate(inputs[0])]
            if got != want:
                fail("%s/%s says %s, which for these inputs means %s: %s"
                     % (col, case, said[case], want, got))

kinds, checked = {}, 0
for cs in doc["cells"].values():
    for rid in cs.values():
        k = doc["rules"].get(rid, {})
        kinds[k.get("kind")] = kinds.get(k.get("kind"), 0) + 1
        checked += 1 if k.get("check") else 0
filed = sum(1 for r in doc["rules"].values() if re.search(r"[Ff]iled as", r["what"]))

# The README puts these counts in prose, where nothing would notice them going stale.
WORD = {6: "six", 8: "eight", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
        14: "fourteen", 17: "seventeen", 18: "eighteen", 21: "twenty-one", 22: "twenty-two", 19: "nineteen", 20: "twenty"}
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
