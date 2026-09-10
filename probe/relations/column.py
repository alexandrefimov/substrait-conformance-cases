"""Turns a relations runner's answers into a column, and refuses one that is not whole.

    <runner> | python3 probe/relations/column.py <NAME> "<revision>" > results/relations/<NAME>.txt

A runner prints `<case id><TAB><answer>`, one line per case, in whatever order it got through them.
Everything that makes those lines a column - the case list, the order, the marks, the head that says
what the run was and how far this participant can be read - is decided here, so that two columns
differ in their answers and in nothing else.

Two facts have to be in the file rather than beside it.

The revision. A column taken elsewhere cannot be read without it: pip and a community extension give
whatever is current there, so a difference from the saved column could be a defect, a platform, or
another version of the participant, and the file would not say which.

The mark. Only KIND_POSITIVE carries an expectation, so only KIND_POSITIVE can be scored; the other
kinds are recorded and never scored. Left implicit, a column reads as 39 answers all of which could
be right, and the corpus starts flattering whoever runs it. The mark comes from
results/relations/expected.json, which is generated from the bundles themselves.

This file needs python3 and nothing else, so the column can be assembled and checked in the same
environment as probe/selfcheck.sh.
"""

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from participants import participant  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPECTED = os.path.join(ROOT, "results", "relations", "expected.json")

ID_WIDTH = 57
MARK_WIDTH = 7


def load_extract():
    with open(EXPECTED, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: column.py <NAME> <revision>")
    name, revision = sys.argv[1], sys.argv[2]
    extract = load_extract()
    cases = extract["cases"]
    mark = {c["id"]: c["mark"] for c in cases}

    answers, repeated, unknown = {}, [], []
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        case_id, _, value = line.partition("\t")
        case_id, value = case_id.strip(), value.strip()
        if case_id not in mark:
            unknown.append(case_id)
        elif case_id in answers:
            repeated.append(case_id)
        else:
            answers[case_id] = value or "ERROR: the runner returned an empty answer"

    missing = [c["id"] for c in cases if c["id"] not in answers]
    harness = sorted(i for i, v in answers.items() if v.startswith("HARNESS-ERROR"))
    # A participant that answered nothing at all is a broken environment, not a finding about it.
    dead = sorted(i for i, v in answers.items() if v.startswith(("ERROR:", "CRASH:")))

    observed = sum(1 for c in cases if c["mark"] == "observe")
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    # The corpus this column answers, not only the participant it answers with. Without it a
    # column and an expectation extract taken from two different states of tests/relations compare
    # cleanly against each other and disagree about a case neither of them is wrong about.
    out = ["%s: relations column from run %s, %s" % (name, stamp, revision),
           "Corpus tests/relations at fingerprint %s, %d cases."
           % (extract["fingerprint"], len(cases))]
    out += participant(name)["boundary"]
    out.append("score = the case carries an expectation and is compared with it. observe ="
               " KIND_INVALID_PLAN or KIND_UNRESOLVED: recorded, never scored, %d of the %d cases."
               % (observed, len(cases)))
    out.append("")
    for case in cases:
        out.append("%-*s %-*s %s" % (MARK_WIDTH, case["mark"], ID_WIDTH, case["id"],
                                     answers.get(case["id"], "")))
    print("\n".join(out))

    problem = 0
    for label, names in (("cases the runner did not answer", missing),
                         ("cases answered more than once", repeated),
                         ("answers for cases that are not in the corpus", unknown),
                         ("cases the harness could not put to the participant", harness)):
        if names:
            print("COLUMN: %s: %s" % (label, ", ".join(sorted(names))), file=sys.stderr)
            problem = 1
    if len(dead) == len(cases):
        print("COLUMN: every case failed - that is a broken environment, not a participant",
              file=sys.stderr)
        problem = 1
    return problem


if __name__ == "__main__":
    sys.exit(main())
