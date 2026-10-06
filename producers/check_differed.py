"""Checks producers/differed.json against the producer columns.

    python3 producers/check_differed.py

Every call a column reports as differing, missing or unbound, and every root whose names do not
count out, has to be matched by exactly one reason for that producer, and every reason has to match
at least one such line. A reason's `match` is a regular expression per producer over the line as
check.py prints it, with runs of spaces read as one; that pattern is also the reason's machine-
testable claim, so a boundary that says "the declared type is the derived one made nullable" says
it as a pattern that fails the moment a line does not have that shape.

A divergence carries a triage per producer: reported, spec-question, ours or open.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results", "producers")
OUTCOMES = {"reported", "spec-question", "ours", "open"}


def differing(producer):
    """[(query, line)] for everything the producer's column reports as not matching."""
    out, query = [], None
    for raw in open(os.path.join(RESULTS, producer + ".txt")):
        m = re.match(r"^(\S+)\s+(calls|REFUSED|MISSING)", raw)
        if m:
            query = m.group(1)
            names = re.search(r"names \d+ for \S+ named fields", raw)
            if names:
                out.append((query, names.group(0)))
        elif raw.startswith("  ") and raw.strip():
            out.append((query, re.sub(r"\s+", " ", raw.strip())))
    return out


def main():
    doc = json.load(open(os.path.join(HERE, "differed.json")))
    rules, bad = doc["rules"], []
    used = set()
    # One column per producer directory in producers/plans; CONSUME.txt beside them is not one.
    producers = sorted(p.upper() for p in os.listdir(os.path.join(HERE, "plans"))
                       if os.path.isdir(os.path.join(HERE, "plans", p)))
    for name, rule in rules.items():
        if rule.get("kind") not in doc["kinds"]:
            bad.append("%s: kind %r is not one of %s" % (name, rule.get("kind"), sorted(doc["kinds"])))
        for p in rule["match"]:
            if p not in producers:
                bad.append("%s: matches %s, which has no column" % (name, p))
        if rule.get("kind") == "divergence":
            for p in rule["match"]:
                t = rule.get("triage", {}).get(p)
                if not t or t.get("outcome") not in OUTCOMES:
                    bad.append("%s: no triage for %s with an outcome in %s" % (name, p, sorted(OUTCOMES)))
    for p in producers:
        for q, line in differing(p):
            hits = [n for n, r in rules.items() if p in r["match"] and re.search(r["match"][p], line)]
            if len(hits) != 1:
                bad.append("%s %s: '%s' is matched by %s" % (p, q, line, hits or "no reason"))
            used.update((n, p) for n in hits)
    for name, rule in rules.items():
        for p in rule["match"]:
            if (name, p) not in used:
                bad.append("%s: matches nothing in %s's column any more" % (name, p))
    if bad:
        for b in bad:
            print("FAILED every differing producer call has one reason: %s" % b)
        return 1
    print("ok      every differing producer call has one reason (%d reasons)" % len(rules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
