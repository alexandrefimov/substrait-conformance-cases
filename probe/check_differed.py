"""Checks differed.json against the saved columns.

    python3 probe/check_differed.py

differed.json says, per participant and case, why the answer differs: a limit of that type system,
a type the participant never resolved, or a divergence. Those are judgements written by hand, so
what can be checked is that they describe this run and no other - every differing cell classified,
nothing classified that no longer differs - and, where a reason makes a claim a machine can test,
that the claim holds. A reason carries that test in its own `check` field:

    nullable_only          the answer has the expected types and every field nullable
    got_matches            the raw answer matches this regular expression; a mapping of column
                           name to expression when participants under one reason answer differently
    no_field_nullable      the answer has the expected types and no field nullable
    all_decimal            the answer has as many fields as expected and every one is a decimal
    all_fields_are         every field of the answer has this type
    declared_precision_in  the precision the case declares is one of these
    inputs_concatenated    the answer is the relation's inputs one after another, with their own
                           nullability; `mark_suffix` allows one trailing boolean
    first_input            the answer is the first input, types and nullability alike; `leading`
                           requires it to stop short instead - the columns the input starts with and
                           fewer of them, so an answer that returns the input whole fails
    nullable_if_any_input  the answer has a nullable field wherever any input does

Without any of this the file would drift into describing a measurement that has moved, and would
be more misleading than no file at all.
"""
import io, json, os, re, subprocess, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COLS = [("PYTHON", "py"), ("GO", "go"), ("VALIDATOR", "py"), ("ISTHMUS", "calcite"),
        ("DATAFUSION", "df"), ("DUCKDB", "duckdb"), ("SPARK", "spark"), ("ACERO", "acero"),
        ("JAVA", "java")]

# check_expected.py is a script, not a module: it reads sys.argv at import time. Its parsers are
# taken by running the source down to that line, so the two files cannot disagree about what an
# answer means.
src = io.open(os.path.join(ROOT, "probe/check_expected.py"), encoding="utf-8").read()
P = {"__file__": os.path.join(ROOT, "probe/check_expected.py")}
exec(src[:src.index("path, fmt = sys.argv")], P)
# TYPES_ONLY is assigned after that line, and it is a boundary rather than a detail: it names the
# participants whose logical types carry no nullability. Taking it from the same file keeps the two
# checks from drifting into disagreeing about what a participant claims to say.
exec(re.search(r"^TYPES_ONLY = .*$", src, re.M).group(0), P)
PARSE = {"java": "parse_java", "py": "parse_py", "df": "parse_df", "duckdb": "parse_duckdb",
         "acero": "parse_acero", "go": "parse_go", "spark": "parse_spark", "calcite": "parse_calcite"}

# The inputs of the relation under test, in the order the plan declares them. Reading them from the
# case rather than restating them here is the point: a reason that says "the inputs concatenated" is
# then checked against the inputs, not against a copy of them that can go stale on its own.
PROTO_TYPE = {"i64": "i64", "i32": "i32", "i16": "i16", "i8": "i8", "bool": "bool", "string": "str",
              "fp64": "fp64", "fp32": "fp32", "binary": "bin", "date": "date"}

def case_precisions(case):
    """The precisions the case's schema declares. Read from the plan, not from the expectation:
    the two agree here only because the expectation of a bare read is its base_schema, and a
    declaration disagreeing with what is derived from it is the thing this corpus exists to catch."""
    plan = json.load(open(os.path.join(ROOT, "derived-schema/%s.json" % case), encoding="utf-8"))
    found = []
    def walk(node):
        if isinstance(node, dict):
            if "precisionTimestamp" in node:
                found.append(node["precisionTimestamp"].get("precision", 0))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(plan)
    return found

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

# check_expected.py compares DuckDB on types, arity and order alone, because its logical types do
# not carry nullability; comparing it there would record the boundary of its type system as a
# divergence. A reason's predicate has to honour the same boundary, or it would fail a participant
# for something it never claimed to say. Today every DuckDB case here happens to be required on both
# sides, so this changes no result - it stops one from appearing the moment a nullable case is added.
def comparable(fmt, fields):
    if fields is None:
        return None
    return [[t, False] for t, _ in fields] if fmt in P["TYPES_ONLY"] else [list(f) for f in fields]

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

FLAGS = {"nullable_only", "no_field_nullable", "nullable_if_any_input"}
OPTIONS = {"inputs_concatenated": {"mark_suffix"}, "first_input": {"leading"},
           "all_decimal": {"nullable_in"}}
INPUT_CHECKS = set(OPTIONS) | {"nullable_if_any_input"}
# all_fields_are takes a type name, declared_precision_in a list of precisions; got_matches takes an
# expression, or a mapping from column name to one where the participants under a single reason
# answer differently and a shared expression would only assert what they have in common.
VALUED = {"all_fields_are", "declared_precision_in"}
CHECKS = FLAGS | set(OPTIONS) | VALUED | {"got_matches"}
INPUT_CHECKS = INPUT_CHECKS - {"all_decimal"}

for rid, r in doc["rules"].items():
    if r["kind"] not in doc["kinds"]:
        fail("rule %s has an unknown kind %r" % (rid, r["kind"]))
    # Every reason here turned out to be testable once it was stated precisely enough, and the
    # imprecise ones were where the mistakes were: reasons that held for most of their cells and
    # described the rest wrongly. So a reason without a test is refused rather than allowed as an
    # exception - if nothing can be tested about it, it is not yet saying what it observed.
    check = r.get("check")
    if not isinstance(check, dict) or not check:
        fail("rule %s makes no claim a machine can test" % rid)
        continue
    unknown = set(check) - CHECKS
    if unknown:
        fail("rule %s has unknown checks: %s" % (rid, ", ".join(sorted(unknown))))
    if len(set(check) & INPUT_CHECKS) > 1:
        fail("rule %s has multiple input checks; only one can run" % rid)
    for name, value in check.items():
        if name in FLAGS and value is not True:
            fail("rule %s check %s must be true" % (rid, name))
        elif name == "got_matches":
            by_column = value if isinstance(value, dict) else {None: value}
            if not by_column or not all(isinstance(v, str) and v for v in by_column.values()):
                fail("rule %s got_matches must be a nonempty regular expression, or a mapping of "
                     "column name to one" % rid)
            else:
                for column, expression in by_column.items():
                    if column is not None and column not in dict(COLS):
                        fail("rule %s got_matches names %r, which is not a column" % (rid, column))
                    try:
                        re.compile(expression)
                    except re.error as e:
                        fail("rule %s has an invalid got_matches expression: %s" % (rid, e))
        elif name == "all_fields_are":
            if not isinstance(value, str) or not value:
                fail("rule %s all_fields_are must be a type name" % rid)
        elif name == "declared_precision_in":
            if not isinstance(value, list) or not value or not all(isinstance(v, int) for v in value):
                fail("rule %s declared_precision_in must be a nonempty list of precisions" % rid)
        elif name in OPTIONS:
            if name == "first_input" and value is True:
                continue
            if not isinstance(value, dict):
                fail("rule %s check %s needs an options object" % (rid, name))
                continue
            if set(value) - OPTIONS[name]:
                fail("rule %s check %s has unknown options" % (rid, name))
            for option, setting in value.items():
                # nullable_in names the columns a second difference applies to; the rest are flags.
                if option == "nullable_in":
                    if (not isinstance(setting, list) or not setting
                            or any(c not in dict(COLS) for c in setting)):
                        fail("rule %s check %s nullable_in must be a nonempty list of columns"
                             % (rid, name))
                elif type(setting) is not bool:
                    fail("rule %s check %s option %s must be true or false"
                         % (rid, name, option))

if bad:
    raise SystemExit(bad)

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
        if "got_matches" in check:
            pattern = check["got_matches"]
            if isinstance(pattern, dict):
                pattern = pattern.get(col)
                if pattern is None:
                    fail("%s/%s says %s, which says nothing about this participant"
                         % (col, case, said[case]))
            if pattern is not None and not re.search(pattern, got_raw):
                fail("%s/%s says %s, whose answer should match %s: %s"
                     % (col, case, said[case], pattern, got_raw))
        if "all_fields_are" in check:
            got = P[PARSE[fmt]](got_raw)
            if got is None or not all(t == check["all_fields_are"] for t, _ in got):
                fail("%s/%s says %s, so every field should be %s: %s"
                     % (col, case, said[case], check["all_fields_are"], got_raw))
        if "declared_precision_in" in check:
            declared = case_precisions(case)
            if sorted(set(declared)) != sorted(set(declared) & set(check["declared_precision_in"])):
                fail("%s/%s says %s, which is only about precisions %s, and this case declares %s"
                     % (col, case, said[case], check["declared_precision_in"], declared))
        if check.get("nullable_only"):
            got = P[PARSE[fmt]](got_raw)
            want = expected[case]["schema"]
            if got is None or [t for t, _ in got] != [t for t, _ in want]:
                fail("%s/%s says %s - the expected types with nullability lost - but the types "
                     "differ too: %s against %s" % (col, case, said[case], got, want))
            elif not all(n for _, n in got):
                fail("%s/%s says %s, but not every field of the answer is nullable: %s"
                     % (col, case, said[case], got_raw))
        if "all_decimal" in check:
            got = comparable(fmt, P[PARSE[fmt]](got_raw))
            want = comparable(fmt, expected[case]["schema"])
            if got is None or len(got) != len(want) or not all(t.startswith("dec(") for t, _ in got):
                fail("%s/%s says %s, so the answer should be %d decimal field(s): %s"
                     % (col, case, said[case], len(want), got_raw))
            else:
                # A cell can carry two differences at once. Naming which participants lose
                # nullability on top of the precision keeps the second half from going unstated,
                # which is how it went unnoticed here in the first place.
                also = col in (check["all_decimal"] or {}).get("nullable_in", [])
                nullable = [n for _, n in got]
                if also and nullable != [True] * len(got):
                    fail("%s/%s says %s is also nullable here, and it is not: %s"
                         % (col, case, said[case], got_raw))
                if not also and nullable != [n for _, n in want]:
                    fail("%s/%s says %s differs in precision and scale alone, but its nullability "
                         "differs too: %s against %s" % (col, case, said[case], got, want))
        if check.get("no_field_nullable"):
            got, want = P[PARSE[fmt]](got_raw), expected[case]["schema"]
            if got is None or [t for t, _ in got] != [t for t, _ in want]:
                fail("%s/%s says %s - the expected types, none of them nullable - but the types "
                     "differ too: %s against %s" % (col, case, said[case], got, want))
            elif any(n for _, n in got):
                fail("%s/%s says %s, but a field of the answer is nullable: %s"
                     % (col, case, said[case], got_raw))
        if {"inputs_concatenated", "first_input", "nullable_if_any_input"} & set(check):
            try:
                inputs = case_inputs(case)
            except KeyError as e:
                fail("%s/%s says %s, which is read against the case's inputs, and %s"
                     % (col, case, said[case], e.args[0]))
                continue
            got = comparable(fmt, P[PARSE[fmt]](got_raw))
            inputs = [comparable(fmt, one) for one in inputs]
            if "inputs_concatenated" in check:
                want = [f for one in inputs for f in one]
                tail = got[len(want):] if got else []
                if check["inputs_concatenated"].get("mark_suffix") and tail == [["bool", True]]:
                    got = got[:len(want)]
            elif "first_input" in check:
                want = inputs[0]
                if isinstance(check["first_input"], dict) and check["first_input"].get("leading"):
                    # A prefix, and a proper one: without this an answer returning the input whole
                    # passes a reason that says it stops short, which is what the participants under
                    # the neighbouring reason do.
                    if got is not None and len(got) < len(want):
                        want = want[:len(got)]
                    else:
                        fail("%s/%s says %s, so the answer should be shorter than the input's %d "
                             "columns: %s" % (col, case, said[case], len(want), got_raw))
                        continue
            else:
                want = [[t, any(one[i][1] for one in inputs)]
                        for i, (t, _) in enumerate(inputs[0])]
            if got != want:
                fail("%s/%s says %s, which for these inputs means %s: %s"
                     % (col, case, said[case], want, got))

# What came of a divergence, as opposed to what it is. The reason says what the participant does;
# this says whether anyone has taken it anywhere - and it is kept per participant, because a rule
# can span four of them and no single report covers all four.
#
# "open" is a first-class answer. Requiring a link would push a cell towards a bug report before
# anyone had read it, and a report filed to satisfy a check is worse than an untriaged cell that
# says so.
OUTCOMES = {
    "reported":      "covered by an implementation issue or PR, with limits in the note",
    "spec-question": "the spec text does not settle it",
    "ours":          "the expectation or this harness is wrong",
    "open":          "still needs investigation",
}
NEEDS_URL = {"reported", "spec-question"}
ISSUE_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+$")

# Every link the data names has to appear in the map a reader is sent to, or the map falls behind
# the data silently - which is how probe/README.md came to carry findings differed.json did not.
findings = io.open(os.path.join(ROOT, "FINDINGS.md"), encoding="utf-8").read()

parties = {}
for col, cs in doc["cells"].items():
    for case, rid in cs.items():
        parties.setdefault(rid, set()).add(col)

triage_pairs, triage_open, rules_with_a_report = 0, 0, 0
REFERENCE = re.compile(r"[\w.-]+/[\w.-]+#\d+|https://github\.com/\S+")

for rid, rule in doc["rules"].items():
    # A report belongs in the triage, not in the sentence beside it. Both carried them until now
    # and nothing compared the two, so a reason could name one issue in its prose and another in
    # its record - and the prose was the half nothing checked, since it is a sentence.
    stray = REFERENCE.findall(rule["what"])
    if stray:
        fail("%s names %s in its prose; a report goes in the triage, where it is checked"
             % (rid, ", ".join(stray)))
    triage = rule.get("triage")
    if rule["kind"] != "divergence":
        # A boundary or an unresolved type is a statement about a type system, not something to
        # report to anyone. Letting the field appear there would make it mean two things.
        if triage is not None:
            fail("%s is %s, and only a divergence carries a triage" % (rid, rule["kind"]))
        continue
    if not isinstance(triage, dict) or not triage:
        fail("%s is a divergence with no triage; every one of them says what came of it, "
             "and \"open\" is an allowed answer" % rid)
        continue
    if set(triage) != parties[rid]:
        fail("%s is triaged for %s and its cells belong to %s"
             % (rid, ", ".join(sorted(triage)) or "nobody", ", ".join(sorted(parties[rid]))))
    if any(v.get("at") for v in triage.values()):
        rules_with_a_report += 1
    for col, entry in sorted(triage.items()):
        triage_pairs += 1
        outcome, at = entry.get("outcome"), entry.get("at", [])
        if outcome not in OUTCOMES:
            fail("%s/%s: %r is not one of %s" % (rid, col, outcome, ", ".join(sorted(OUTCOMES))))
            continue
        if outcome == "open":
            triage_open += 1
        if outcome in NEEDS_URL and not at:
            fail("%s/%s says %s and names nothing to follow" % (rid, col, outcome))
        if outcome not in NEEDS_URL and at:
            fail("%s/%s says %s, which names no report, and carries %s" % (rid, col, outcome, at))
        for url in at:
            if not ISSUE_URL.match(url):
                fail("%s/%s: %s is not an issue or pull request" % (rid, col, url))
            elif url not in findings:
                fail("%s/%s names %s, which FINDINGS.md does not" % (rid, col, url))

# --- refused.json: the refusals that are defects rather than absences ------------------------------
#
# A participant that produced no comparable schema is counted as unsupported, and 201 of those cells
# carry no reason at all. Most of them do not need one: "this engine does not implement that
# relation" is what the answer already says, and restating it in a sentence would assert nothing.
# Eleven are different. There the process died - the answer is a signal, not a message - and an
# engine that says it cannot do something is not in the same condition as one that dies trying,
# whatever its support. Those are recorded the way divergences are: a reason with a predicate the
# answer has to satisfy, and a record of what came of it.
#
# Nothing else lives in refused.json yet. The general answer to the other 190 would be to compare a
# refusal against what the engine declares it supports, and the spec ships no such declaration
# today: at v0.102.0 dialects/ holds the schema and its fixtures and not one engine's file.
CRASH = re.compile(r"^ERROR: signal/exit \d+$")
refused = json.load(open(os.path.join(ROOT, "refused.json"), encoding="utf-8"))

seen_crashes = {}
for col, _fmt in COLS:
    for case, answer in answers(col).items():
        if CRASH.match(answer):
            seen_crashes.setdefault(col, {})[case] = answer

listed = {c: set(v) for c, v in refused["cells"].items()}
found = {c: set(v) for c, v in seen_crashes.items()}
if listed != found:
    for col in sorted(set(listed) | set(found)):
        extra, missing = listed.get(col, set()) - found.get(col, set()), found.get(col, set()) - listed.get(col, set())
        if missing:
            fail("%s died on %s, and refused.json does not say so" % (col, ", ".join(sorted(missing))))
        if extra:
            fail("refused.json says %s died on %s, and the column says otherwise"
                 % (col, ", ".join(sorted(extra))))

crash_pairs, crash_open = 0, 0
for rid, rule in refused["rules"].items():
    if rule["kind"] not in refused["kinds"]:
        fail("%s is of kind %r, which refused.json does not define" % (rid, rule["kind"]))
    stray = REFERENCE.findall(rule["what"])
    if stray:
        fail("%s names %s in its prose; a report goes in the triage" % (rid, ", ".join(stray)))
    covers = {c for c, m in refused["cells"].items() if rid in m.values()}
    triage = rule.get("triage") or {}
    if set(triage) != covers:
        fail("%s is triaged for %s and its cells belong to %s"
             % (rid, ", ".join(sorted(triage)) or "nobody", ", ".join(sorted(covers))))
    for col, entry in sorted(triage.items()):
        crash_pairs += 1
        outcome, at = entry.get("outcome"), entry.get("at", [])
        if outcome not in OUTCOMES:
            fail("%s/%s: %r is not one of %s" % (rid, col, outcome, ", ".join(sorted(OUTCOMES))))
            continue
        if outcome == "open":
            crash_open += 1
        if outcome in NEEDS_URL and not at:
            fail("%s/%s says %s and names nothing to follow" % (rid, col, outcome))
        if outcome not in NEEDS_URL and at:
            fail("%s/%s says %s, which names no report, and carries %s" % (rid, col, outcome, at))
        for url in at:
            if not ISSUE_URL.match(url):
                fail("%s/%s: %s is not an issue or pull request" % (rid, col, url))
            elif url not in findings:
                fail("%s/%s names %s, which FINDINGS.md does not" % (rid, col, url))
    # The predicate, as for a divergence: a reason that cannot be tested against the answer is a
    # sentence, and this file exists because a sentence was not enough for the differing cells.
    want = (rule.get("check") or {}).get("got_matches")
    if not isinstance(want, dict) or not want:
        fail("%s carries no got_matches, so nothing tests it against the answers" % rid)
        continue
    for col, pattern in want.items():
        for case in sorted(c for c, r in refused["cells"].get(col, {}).items() if r == rid):
            got = seen_crashes.get(col, {}).get(case, "")
            if not re.match(pattern, got):
                fail("%s/%s/%s: %r does not match %r" % (rid, col, case, got, pattern))

kinds, checked = {}, 0
for cs in doc["cells"].values():
    for rid in cs.values():
        k = doc["rules"].get(rid, {})
        kinds[k.get("kind")] = kinds.get(k.get("kind"), 0) + 1
        checked += 1 if k.get("check") else 0
# Counted from the triage rather than from the words "Filed as" in the reason's own prose, which
# was a proxy: it counted the sentence, not the record, and could not see a report filed for one
# participant of a rule that covers four.
filed = rules_with_a_report

# The README puts these counts in prose, where nothing would notice them going stale.
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
        "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

def word(n):
    """The English for a count under a hundred, so that a number moving past a hand-kept list
    cannot turn a checked sentence into one nothing can satisfy."""
    if n < 20:
        return ONES[n]
    return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")

class _Word:
    def get(self, n, default=None):
        return word(n) if isinstance(n, int) and 0 <= n < 100 else default

WORD = _Word()
# README.md and METHOD.md are one page split by audience, and a sentence can move between them; the
# claim has to be somewhere on it, not in a particular file.
readme = " ".join(" ".join(io.open(os.path.join(ROOT, f), encoding="utf-8").read()
                           for f in ("README.md", "METHOD.md")).split())
for sentence in ("gives all %d of them a reason and marks %d as something other than"
                 % (total, total - kinds.get("divergence", 0)),
                 "%s are limits of a type system, %s a type the validator never resolved"
                 % (WORD.get(kinds.get("boundary")), WORD.get(kinds.get("unresolved"))),
                 "%s of its %s reasons link an issue or PR" % (WORD.get(filed), WORD.get(len(doc["rules"]))),
                 "%s cells where a participant died rather than refused"
                 % WORD.get(sum(len(v) for v in refused["cells"].values())),
                 "%s of those %s still need investigation"
                 % (WORD.get(triage_open), WORD.get(triage_pairs))):
    if sentence not in readme:
        fail("the README does not say %r" % sentence)

if not bad:
    print("ok      %d differing cells, %d reasons (%d linking an issue or PR), %s; %d cells machine-checked, "
          "%d triaged pairs (%d open)"
          % (total, len(doc["rules"]), filed,
             ", ".join("%s %d" % kv for kv in sorted(kinds.items())), checked,
             triage_pairs, triage_open))
    print("ok      %d cells where a participant died rather than refused, %d reasons (%d open)"
          % (sum(len(v) for v in refused["cells"].values()), len(refused["rules"]), crash_open))
raise SystemExit(bad)
