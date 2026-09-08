"""Checks the numbers the pages state in prose against the files they describe.

    python3 probe/check_pages.py

selfcheck.sh already compares the README's results table with `check_expected.py`, and that table
has never gone stale. The prose around it has: the corpus grew to 86 cases and four sentences went
on saying 80 expectations, and the per-participant counts in *What would help* stayed at a run two
cases old, so the one paragraph addressed to the maintainers of the implementations disagreed with
the table above it. Nothing noticed, because nothing was looking at sentences.

So the numbers a page states about the corpus are listed here with the file each comes from. A
claim that no longer matches its file fails; so does a claim whose sentence has been reworded past
its pattern, because a guard that quietly stops matching is worse than no guard - that is how three
checks in this repository came to be committed and unable to fire. Rewording a sentence therefore
means editing its pattern here, deliberately, in the same commit.

What this cannot do is notice a number nobody registered: the list below is written by hand, and a
sentence that acquires a new count is guarded only when its entry is added in the same commit.

What is not here: numbers that record a past event rather than the present state - the size of the
corpus when the swap experiment ran, the crashes a broken validator environment once produced.
Those are dated by their own sentences and do not rot.
"""
import io, json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

WORDS = {"no": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22, "twenty-three": 23,
         "twenty-four": 24, "twenty-five": 25, "twenty-six": 26, "twenty-seven": 27,
         "twenty-eight": 28, "twenty-nine": 29, "thirty": 30}

# The pages spell small numbers as words and large ones as digits, in the same sentence, so a
# pattern has to accept either. Anything else - "several", "a few" - is not a number this can check
# and says so rather than passing.
NUMBER = r"\b(\d+|[A-Za-z]+(?:-[A-Za-z]+)?)"


def number(text, where):
    if text.isdigit():
        return int(text)
    if text.lower() in WORDS:
        return WORDS[text.lower()]
    raise SystemExit("FAILED: %s: %r is not a number this check can read" % (where, text))


def plan_lines(case):
    with io.open(os.path.join(ROOT, "derived-schema", case + ".json"), encoding="utf-8") as f:
        return sum(1 for _ in f)


def facts():
    """Everything the prose is allowed to claim, read from the files that hold it."""
    cases = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, "derived-schema"))
                   if f.endswith(".json") and f != "manifest.json")
    exp = json.load(io.open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))
    dif = json.load(io.open(os.path.join(ROOT, "differed.json"), encoding="utf-8"))
    man = json.load(io.open(os.path.join(ROOT, "derived-schema/manifest.json"), encoding="utf-8"))

    sizes = [plan_lines(c) for c in cases]
    cells = [(p, case, dif["rules"][key]) for p, byname in dif["cells"].items()
             for case, key in byname.items()]
    triaged = [(p, key) for key, rule in dif["rules"].items()
               for p in rule.get("triage", {})]

    # The swap experiment ran over the corpus as it was that day, and its saved output names only
    # the cases it touched. So the size it ran against is read from its own header, and what the
    # pages may say is how far the corpus has moved past it: the cases added since, and how many of
    # those declare an output_type the swap never reached. Every case carrying one was touched then,
    # so the ones carrying one and absent from the table are exactly the new ones - which is checked
    # here rather than assumed.
    lie = io.open(os.path.join(ROOT, "results/LIE.txt"), encoding="utf-8").read()
    header = re.search(r"(\d+) of the (\d+) cases carry an\s+output_type", lie)
    if not header:
        raise SystemExit("FAILED: results/LIE.txt no longer says what it ran over")
    touched, swap_corpus = int(header.group(1)), int(header.group(2))
    in_table = {c for c in cases if re.search(r"^%s\s" % re.escape(c), lie, re.M)}
    declaring = {c for c in cases
                 if "outputType" in io.open(os.path.join(ROOT, "derived-schema", c + ".json"),
                                            encoding="utf-8").read()}
    if len(in_table) != touched or not in_table <= declaring:
        raise SystemExit("FAILED: results/LIE.txt lists %d cases where its header says %d"
                         % (len(in_table), touched))

    f = {
        "cases": len(cases),
        "scored": len(exp["expected"]),
        "unscored": len(cases) - len(exp["expected"]),
        "row cases": len(exp["rows"]),
        "cases naming a source issue": sum(1 for e in man if e.get("source")),
        "differing cells": len(cells),
        "cells that are not a divergence": sum(1 for _, _, r in cells if r["kind"] != "divergence"),
        "cells at a type-system limit": sum(1 for _, _, r in cells if r["kind"] == "boundary"),
        "cells with an unresolved type": sum(1 for _, _, r in cells if r["kind"] == "unresolved"),
        "triaged pairs": len(triaged),
        "open triaged pairs": sum(1 for key, rule in dif["rules"].items()
                                  for p, t in rule.get("triage", {}).items()
                                  if t["outcome"] == "open"),
        "cases pending a spec answer": len(exp["spec_silent"]),
        "lines in the example plan": plan_lines("aggregate_grouping_field_shared_by_sets"),
        "lines in the shortest plan": min(sizes),
        "lines in the longest plan": max(sizes),
        "cases added since the swap ran": len(cases) - swap_corpus,
        "of those declaring an output_type": len(declaring - in_table),
    }
    for p, byname in dif["cells"].items():
        f["cases differing for " + p] = len(byname)
    return f


# file, the fact it must equal, and the sentence it lives in. One entry per number in the prose.
# Spaces inside a pattern are \s+ because these pages wrap at 100 columns and a sentence moves
# across the wrap when a word before it changes: the first edit after this guard was written broke
# four patterns that way, which is a rewording the author did not make.
CLAIMS = [
    ("README.md", "cases", r"The main comparison corpus contains %s\s+plans" % NUMBER),
    ("README.md", "scored", r"an expected schema for %s of\s+them" % NUMBER),
    ("README.md", "cases", r"not counted in the saved %s-plan\s+matrix" % NUMBER),
    ("README.md", "scored", r"It is %s expectations written by\s+hand" % NUMBER),
    ("README.md", "cases differing for VALIDATOR", r"%s for the\s+validator" % NUMBER),
    ("README.md", "cases differing for DUCKDB", r"%s for\s+DuckDB" % NUMBER),
    ("README.md", "cases differing for PYTHON", r"%s for\s+substrait-python" % NUMBER),
    ("README.md", "cases differing for ACERO", r"%s for\s+Acero" % NUMBER),
    ("README.md", "cases pending a spec answer", r"%s cases here go\s+unscored" % NUMBER),
    ("README.md", "scored", r"They answer the %s cases that carry an\s+expectation" % NUMBER),
    ("README.md", "differing cells", r"gives all %s of them a\s+reason" % NUMBER),
    ("README.md", "cells that are not a divergence",
     r"marks %s as something other than\s+a divergence" % NUMBER),
    ("README.md", "cells at a type-system limit", r"%s are limits of a type\s+system" % NUMBER),
    ("README.md", "cells with an unresolved type",
     r"%s a type the validator never\s+resolved" % NUMBER),
    ("README.md", "cases", r"The corpus is `derived-schema/` — %s\s+plans" % NUMBER),
    ("README.md", "open triaged pairs",
     r"%s of the [a-z-]+\s+divergence-and-participant pairs" % NUMBER),
    ("README.md", "triaged pairs", r"of the %s\s+divergence-and-participant pairs" % NUMBER),
    ("README.md", "row cases", r"Rows are compared for three participants and %s\s+cases" % NUMBER),
    ("README.md", "scored", r"schemas for nine participants and %s\s+cases" % NUMBER),
    ("README.md", "cases naming a source issue", r"%s of the \d+ cases link to the\s+issue" % NUMBER),
    ("README.md", "cases", r"[A-Za-z]+ of the %s cases link to the\s+issue" % NUMBER),

    ("README.md", "lines in the example plan", r"—\s+%s lines for that case" % NUMBER),
    ("README.md", "lines in the shortest plan", r"lines for that case, between %s and" % NUMBER),
    ("README.md", "lines in the longest plan", r"between \d+ and %s across the\s+corpus" % NUMBER),

    ("METHOD.md", "unscored", r"%s cases carry no\s+expectation" % NUMBER),
    ("METHOD.md", "cases pending a spec answer", r"%s have\s+virtual-table row types" % NUMBER),
    ("METHOD.md", "cases added since the swap ran", r"%s cases have been added\s+since" % NUMBER),
    ("METHOD.md", "of those declaring an output_type",
     r"%s of them declaring an\s+`output_type`" % NUMBER),

    ("FINDINGS.md", "cases", r"outside the saved %s-plan\s+matrix" % NUMBER),

    ("probe/README.md", "cases", r"and the saved %s-plan\s+matrix" % NUMBER),
    ("probe/README.md", "cases", r"separate from the %s plans in the main\s+corpus" % NUMBER),
]


def main():
    known = facts()
    bad = 0
    for path, fact, pattern in CLAIMS:
        text = io.open(os.path.join(ROOT, path), encoding="utf-8").read()
        found = re.findall(pattern, text)
        if not found:
            print("FAILED: %s: no sentence matches %s - the sentence this guard watches was "
                  "reworded, so update the pattern in probe/check_pages.py with it" % (path, pattern))
            bad = 1
            continue
        for hit in found:
            got = number(hit if isinstance(hit, str) else hit[0], path)
            if got != known[fact]:
                print("FAILED: %s says %s where the files say %d (%s)"
                      % (path, hit, known[fact], fact))
                bad = 1
    if not bad:
        print("ok      %d numbers across %d pages, each matching the files it describes"
              % (len(CLAIMS), len({p for p, _, _ in CLAIMS})))
    return bad


if __name__ == "__main__":
    sys.exit(main())
