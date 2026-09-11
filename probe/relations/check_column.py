"""Reads a saved relations column and says what it found.

    python3 probe/relations/check_column.py results/relations/DUCKDB.txt
    python3 probe/relations/check_column.py results/relations/DUCKDB.txt --cases

Three things separate a verdict here from one in the 98-case corpus.

Only KIND_POSITIVE is scored, and the column says so per line. The other kinds carry no expectation
at all, so an answer to one of them is recorded and counted apart. A summary that folded them in
would report more agreement than the corpus asked for.

A case is not one assertion. Most declare rows as well as a schema, and one pair -
join_physical/hash_right_semi and hash_right_anti - emits the same columns with the same
nullability and differs in nothing but the rows. So a participant that derives schemas without
executing is not scored on rows as though it had agreed: its unreached row assertions are counted
and named, and the semi/anti pair is called out by name, because a schema-only participant answers
both of them identically and would otherwise read as two agreements.

Comparison stops at the participant's boundary, from probe/relations/participants.py. DuckDB's
logical types carry no nullability, so the expectation is compared with the nullability markers
dropped from both sides - an unobservable property is not a disagreement, and it is not a match
either; the head of the column is where a reader learns which.

Needs python3 and nothing else. The extract it compares against is checked back against the
committed bundles by their SHA-256 first, so a column is never scored against an expectation taken
from a case that has since been recompiled.
"""

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from participants import participant  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPECTED = os.path.join(ROOT, "results", "relations", "expected.json")
BUNDLES = os.path.join(ROOT, "tests", "relations", "bundles")

# The two cases the corpus can tell apart only by their rows. Named rather than derived: deriving
# them would mean two cases with identical schemas and different rows, which is a property of this
# pair today and not a rule about the corpus.
ROWS_ONLY_PAIR = ("join_physical/hash_right_semi/wire-6", "join_physical/hash_right_anti/wire-8")

REFUSAL = ("ERROR:", "CRASH:", "HARNESS-ERROR")
LINE = re.compile(r"^(score|observe)\s+(\S+)\s*(.*)$")


def load_extract():
    with open(EXPECTED, encoding="utf-8") as fh:
        doc = json.load(fh)
    stale = []
    on_disk = set()
    for dirpath, _, files in os.walk(BUNDLES):
        for f in files:
            if f.endswith(".pb"):
                on_disk.add(os.path.relpath(os.path.join(dirpath, f), BUNDLES))
    for missing in sorted(on_disk - {c["bundle"] for c in doc["cases"]}):
        # A case added to the corpus and not extracted would otherwise be measured by nobody and
        # missed by everybody: no column would carry it and no count would be short.
        stale.append("%s is a bundle the extract does not name" % missing)
    for case in doc["cases"]:
        path = os.path.join(BUNDLES, case["bundle"])
        if not os.path.exists(path):
            stale.append("%s: %s is gone" % (case["id"], case["bundle"]))
            continue
        with open(path, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != case["sha256"]:
                stale.append("%s: %s has changed since the extract was written"
                             % (case["id"], case["bundle"]))
    if stale:
        sys.exit("expected.json no longer describes the bundles; rerun"
                 " probe/relations/expected.py --write\n  " + "\n  ".join(stale))
    return doc


def read_column(path):
    """The head down to the first blank line says what the run was; the body is the answers."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    head, _, body = text.partition("\n\n")
    answers = {}
    for line in body.splitlines():
        if not line.strip():
            continue
        m = LINE.match(line)
        if not m:
            sys.exit("%s: cannot read line: %s" % (os.path.relpath(path, ROOT), line))
        answers[m.group(2)] = (m.group(1), m.group(3).strip())
    return head, answers


def strip_nullability(text):
    """Drop the `?` that ends a type, and only that one.

    `corpus.render_schema` writes `?` for a column whose name it has no type for and one for a type
    it has no name for, so a blanket replace would edit an arity mismatch into something else -
    which is the very answer a participant that miscounts its output columns gives.
    """
    return re.sub(r"(?<!:)\?(?=,|\]|$)", "", text)


def split_answer(text):
    """`[a:i64] rows (1)` into its schema and its rows. Absent rows are None, not an empty set:
    a participant that did not run the plan has said nothing about rows.

    An empty set is `[a:i64] rows`, with nothing after the word: a runner writes `rows ` and an
    empty list, and column.py strips the space that would have held them. A schema always ends in
    `]`, so the word at the end can only be this.
    """
    if text.startswith(REFUSAL):
        return None, None
    if text.endswith(" rows"):
        return text[:-len(" rows")].strip(), ""
    schema, sep, rows = text.partition(" rows ")
    return schema.strip(), rows.strip() if sep else None


def compare_schema(got, want, caps):
    if not caps["nullability"]:
        got, want = strip_nullability(got), strip_nullability(want)
    if not caps["names"]:
        got = "[%s]" % ", ".join(c.split(":", 1)[-1] for c in got.strip("[]").split(", ") if c)
        want = "[%s]" % ", ".join(c.split(":", 1)[-1] for c in want.strip("[]").split(", ") if c)
    return got == want


# What a scored case came to. The picture draws these and the summary counts them, out of one
# procedure: a second loop over the same columns is exactly how a drawing comes to disagree with the
# numbers beside it, which is the failure this repository is about.
MATCHED, SCHEMA_ONLY, DIFFERED, UNSUPPORTED, OBSERVED = range(5)
STATE_NAME = {MATCHED: "matched", SCHEMA_ONLY: "matched, rows not observed",
              DIFFERED: "differed", UNSUPPORTED: "not accepted", OBSERVED: "observed, never scored"}


def score(path):
    """Reads a saved column and returns what each case came to, with the head that names the run."""
    extract = load_extract()
    cases = extract["cases"]
    head, answers = read_column(path)
    # The column names itself in its first line. Taking the name from the file name instead would
    # tie a saved column's meaning to where it happens to sit, and a run compared out of a
    # temporary file would be read against the wrong participant's boundary.
    name = head.split(":", 1)[0].strip()
    caps = participant(name)
    if extract["fingerprint"] not in head:
        sys.exit("%s was taken against another state of the corpus: its head does not carry"
                 " fingerprint %s. Retake the column, or check out the cases it answers."
                 % (os.path.relpath(path, ROOT), extract["fingerprint"]))

    missing = [c["id"] for c in cases if c["id"] not in answers]
    extra = [i for i in answers if i not in {c["id"] for c in cases}]
    if missing or extra:
        sys.exit("%s is not a whole column%s%s" % (
            os.path.relpath(path, ROOT),
            "\n  absent: " + ", ".join(missing) if missing else "",
            "\n  not in the corpus: " + ", ".join(extra) if extra else ""))

    matched, differed, unsupported, observed = [], [], [], []
    rows_compared, rows_unreached, rows_unobserved = [], [], []
    state = {}
    for case in cases:
        mark, text = answers[case["id"]]
        if mark != case["mark"]:
            sys.exit("%s: the column marks %s as %s, the corpus says %s"
                     % (os.path.relpath(path, ROOT), case["id"], mark, case["mark"]))
        if mark == "observe":
            observed.append((case["id"], text))
            state[case["id"]] = OBSERVED
            continue
        got_schema, got_rows = split_answer(text)
        if got_schema is None:
            unsupported.append((case["id"], text))
            state[case["id"]] = UNSUPPORTED
            if case["rows"] is not None:
                rows_unreached.append(case["id"])
            continue
        why = []
        if not compare_schema(got_schema, case["schema"], caps):
            why.append("schema %s, expected %s" % (got_schema, case["schema"]))
        if case["rows"] is not None:
            if got_rows is None:
                rows_unobserved.append(case["id"])
            elif got_rows != case["rows"]:
                rows_compared.append(case["id"])
                why.append("rows %s, expected %s" % (got_rows, case["rows"]))
            else:
                rows_compared.append(case["id"])
        (differed if why else matched).append((case["id"], "; ".join(why) or got_schema))
        # A case whose rows the participant never looked at is not the same agreement as one it
        # answered whole, and the two must not share a colour: most cases assert rows, and one pair
        # is separated by nothing else.
        state[case["id"]] = (DIFFERED if why
                             else SCHEMA_ONLY if case["id"] in rows_unobserved
                             else MATCHED)

    return {
        "name": name, "head": head, "caps": caps, "cases": cases, "answers": answers,
        "state": state, "matched": matched, "differed": differed, "unsupported": unsupported,
        "observed": observed, "rows_compared": rows_compared, "rows_unreached": rows_unreached,
        "rows_unobserved": rows_unobserved,
    }


def main():
    path = sys.argv[1]
    verbose = "--cases" in sys.argv[2:]
    model = score(path)
    name, caps, cases, head = model["name"], model["caps"], model["cases"], model["head"]
    matched, differed = model["matched"], model["differed"]
    unsupported, observed = model["unsupported"], model["observed"]
    rows_compared, rows_unreached = model["rows_compared"], model["rows_unreached"]
    rows_unobserved = model["rows_unobserved"]

    scored = len(matched) + len(differed) + len(unsupported)
    declaring_rows = sum(1 for c in cases if c["rows"] is not None)
    print("%s  %s" % (name, head.splitlines()[0].split(": ", 1)[1]))
    print("  scored %d of %d: matched %d, differed %d, unsupported %d"
          % (scored, len(cases), len(matched), len(differed), len(unsupported)))
    print("  observed %d, never scored" % len(observed))
    if caps["executes"]:
        print("  rows: %d cases declare them, %d compared, %d not reached"
              % (declaring_rows, len(rows_compared), len(rows_unreached)))
        if rows_unobserved:
            # The participant ran the plan and the runner brought back no rows. That is a hole in
            # the runner, not an answer about the engine, and counting those cases as matched on
            # their schema alone would hide it.
            sys.exit("  %s answered these cases without the rows they declare, though it executes:"
                     " %s" % (name, ", ".join(rows_unobserved)))
    else:
        print("  rows: %d cases declare them, none observed - this participant derives schemas"
              " and does not execute" % declaring_rows)
    pair = [i for i in ROWS_ONLY_PAIR if i in dict(matched)]
    if len(pair) == 2 and not caps["executes"]:
        print("  %s and %s agree on their schemas and differ only in their rows, so these two"
              " matches rest on one answer" % ROWS_ONLY_PAIR)
    if verbose:
        for label, group in (("differed", differed), ("unsupported", unsupported),
                             ("observed", observed), ("matched", matched)):
            for case_id, detail in group:
                print("  %-9s %-57s %s" % (label, case_id, detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
