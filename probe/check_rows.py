"""Compares a participant's ROWS against the examples in the spec (the rows section of
expected.json).

    python3 probe/check_rows.py <raw probe output> <TAG>

Schema and rows are separate checks. check_expected.py does the schema; this compares the rows an
engine actually returned against the examples the spec prints for set operations. Rows are the one
part of the corpus where the answer does not depend on the participant's type system, so this
applies to engines that carry no nullability in their logical types too.

Row order is not compared: set operations do not fix it. Multisets are.
"""
import json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROWS = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))["rows"]

raw, tag = open(sys.argv[1], encoding="utf-8").read(), sys.argv[2]
# What this file can compare is narrower than what a row expectation could say, and the gap is not
# harmless. Every probe prints a ROWS line only for a single-column result, so an expectation of
# another shape arrives here as no line at all - and the branch below reads "no line, plan accepted"
# as the participant returning nothing, which is a divergence recorded against the participant for a
# limit of this harness. Refuse instead. probe/selfcheck.sh asserts the same shape, so this is the
# second line of defence rather than the first.
for _case, _exp in sorted(ROWS.items()):
    if not isinstance(_exp["rows"], list) or not all(isinstance(v, int) and not isinstance(v, bool)
                                                     for v in _exp["rows"]):
        sys.exit("FAILED: the row expectation for %s is not a multiset of integers; this check "
                 "compares what the probes print, and they print one column of integers" % _case)
# Empty input is a broken probe, not "the participant returned no rows": without this check an
# absence of data gave 0/0/8 and exit 0, which looked like success.
if not [l for l in raw.splitlines() if l.startswith("##### ")]:
    sys.exit("FAILED: no blocks at all in the %s output - the probe produced nothing" % tag)
# Three states, not two: the participant returned rows; the participant accepted the plan but
# returned no rows (a divergence, if the spec prints an example for that case); the participant
# rejected the plan (unsupported).
seen, accepted, name = {}, set(), None
ACCEPT = re.compile(r"^%s (ACCEPTED|SCHEMA)\b" % re.escape(tag))
for line in raw.splitlines():
    if line.startswith("##### "):
        name = line[6:].strip()
    elif name and ACCEPT.match(line.strip()):
        accepted.add(name)
    elif name and line.startswith(tag + " ROWS"):
        body = line.split("ROWS", 1)[1].strip()
        seen[name] = [int(x) for x in re.findall(r"-?\d+", body)]

ok = bad = absent = 0
for case, exp in sorted(ROWS.items()):
    got = seen.get(case)
    if got is None:
        if case in accepted:
            # Plan accepted, no rows. For a case the spec prints an example for that is a
            # divergence: an empty result is as much an answer as a wrong one.
            bad += 1
            print("  %-34s expected %s" % (case, exp["rows"]))
            print("  %-34s got      plan accepted, no rows returned" % "")
        else:
            absent += 1
        continue
    if sorted(got) == sorted(exp["rows"]):
        ok += 1
    else:
        bad += 1
        print("  %-34s expected %s" % (case, exp["rows"]))
        print("  %-34s got      %s" % ("", got))

print("rows: matched %d, differed %d, no rows returned %d (of %d cases with an example)"
      % (ok, bad, absent, len(ROWS)))
sys.exit(1 if bad else 0)
