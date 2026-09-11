"""Checks results/relations/differed.json against the saved columns.

    python3 probe/relations/check_differed.py

The file says, per participant and case, why the answer differs. Those are judgements written by
hand, so what a machine can check is that they describe this run and no other: every differing cell
classified, nothing classified that no longer differs, and every reason's own test still holding
against the answer in the column.

A reason carries that test in its `check` field, as `got_matches` - a regular expression the saved
answer must match, per participant, since one reason can cover participants that answer differently.
Where one reason covers several cases whose answers have nothing in common to match, the value is a
mapping from case to expression instead: a pattern loose enough to fit all five emit cases would
have held for any answer that carried rows at all, which is a test that cannot fail and therefore
is not one. Without any of this the file would drift into describing a measurement that has moved,
and would be worse than no file at all.

Where a cause is one the 98-case corpus already records, the rule keeps that file's id and says so
in `same_as` rather than copying the prose: one engine should not get two stories, and two copies of
a reason are two things to keep in step. The id is checked to exist there.

Needs python3 and nothing else, like the self-check that calls it.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_column as cc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRIAGE = os.path.join(ROOT, "results", "relations", "differed.json")
OTHER = os.path.join(ROOT, "differed.json")
OUTCOMES = {"open", "reported", "fixed", "spec-question", "not-a-defect"}


def main():
    with open(TRIAGE, encoding="utf-8") as fh:
        doc = json.load(fh)
    with open(OTHER, encoding="utf-8") as fh:
        other = json.load(fh)
    rules, cells, kinds = doc["rules"], doc["cells"], doc["kinds"]
    bad = 0

    for rule_id, rule in sorted(rules.items()):
        if rule["kind"] not in kinds:
            print("FAILED: %s has kind %s, which the file does not define" % (rule_id, rule["kind"]))
            bad = 1
        if "same_as" in rule and rule["same_as"] not in other["rules"]:
            print("FAILED: %s says same_as %s, which differed.json does not carry"
                  % (rule_id, rule["same_as"]))
            bad = 1
        if not rule.get("check", {}).get("got_matches"):
            print("FAILED: %s carries no test of an output property" % rule_id)
            bad = 1
        for participant, outcome in rule.get("triage", {}).items():
            if outcome.get("outcome") not in OUTCOMES:
                print("FAILED: %s triages %s as %r, which is not one of %s"
                      % (rule_id, participant, outcome.get("outcome"), ", ".join(sorted(OUTCOMES))))
                bad = 1

    named = {rule_id for byname in cells.values() for rule_id in byname.values()}
    for rule_id in sorted(set(rules) - named):
        print("FAILED: %s is a reason no cell uses" % rule_id)
        bad = 1

    for participant in sorted(cells):
        path = os.path.join(ROOT, "results", "relations", "%s.txt" % participant)
        if not os.path.exists(path):
            print("FAILED: %s is triaged and has no column" % participant)
            bad = 1
            continue
        model = cc.score(path)
        differing = {case_id for case_id, _ in model["differed"]}
        answers = {c["id"]: text for c, (_, text) in
                   zip(model["cases"], [model["answers"][c["id"]] for c in model["cases"]])}
        triaged = cells[participant]

        for case_id in sorted(differing - set(triaged)):
            print("FAILED: %s differs on %s and no reason says why" % (participant, case_id))
            bad = 1
        for case_id in sorted(set(triaged) - differing):
            print("FAILED: %s carries a reason for %s, which no longer differs"
                  % (participant, case_id))
            bad = 1

        for case_id in sorted(set(triaged) & differing):
            rule_id = triaged[case_id]
            if rule_id not in rules:
                print("FAILED: %s/%s names rule %s, which is not in the file"
                      % (participant, case_id, rule_id))
                bad = 1
                continue
            pattern = rules[rule_id]["check"]["got_matches"].get(participant)
            if isinstance(pattern, dict):
                pattern = pattern.get(case_id)
                if pattern is None:
                    print("FAILED: %s covers %s/%s and carries no test for that case"
                          % (rule_id, participant, case_id))
                    bad = 1
                    continue
            if pattern is None:
                print("FAILED: %s covers %s and carries no test for it" % (rule_id, participant))
                bad = 1
            elif not re.search(pattern, answers[case_id]):
                print("FAILED: %s/%s no longer matches its reason %s\n         answer: %s"
                      % (participant, case_id, rule_id, answers[case_id][:120]))
                bad = 1

    if not bad:
        total = sum(len(v) for v in cells.values())
        print("ok      %d differing cells, %d reasons, every reason tested against the column"
              % (total, len(rules)))
    return bad


if __name__ == "__main__":
    sys.exit(main())
