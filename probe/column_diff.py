"""What moved between two takes of one column, and in which direction.

    python3 column_diff.py <saved column> <new column> [label] [new raw output]

Prints one line per case whose answer changed, the cases present in one take and not the other, and
a summary. Exit 1 if anything moved, 0 if nothing did - the caller decides which of those is a
failure. For probe/replay_column.sh against the pinned versions a move is a failure; under LATEST=1
a move is what the run went looking for.

A move is classified, because the four kinds are not read the same way:

    answer      both takes derived a schema, and the schemas differ
    lost        the participant answered before and refuses now
    gained      it refused before and answers now - a fix upstream reads exactly like this
    refusal     it refused both times, with a different message

The refusals are worth telling apart further, and the column cannot: normalize.py writes REJECTED,
CRASH, ERROR and NOTIMPL all as "ERROR: ...", because for the comparison against an expectation they
are one thing. The raw output can, so when it is passed the new side is labelled with the verdict
the runner actually printed. The old side has no raw beside it - results/ keeps columns, not runs -
so it is only ever "answered" or "refused".

Headers are not compared. A column's first line names the day it was taken and the revision it was
taken against, so two takes never agree on it, and a participant's boundary line may follow it;
both sit above the blank line that opens the answers.

A relation column, from probe/relations/replay.sh, is read the same way. Its lines start with a mark
before the case id - `score` or `observe`, which probe/relations/column.py takes from the corpus -
and a process that died is written `CRASH:` rather than folded into `ERROR:`, so both are refusals.
"""
import io, re, sys

VERDICT = re.compile(r"^(?:DATAFUSION|DUCKDB|SUBSTRAITGO|ACERO|VALIDATOR|SPARK|ISTHMUS)\s+(\S+)")
MARK = re.compile(r"^(?:score|observe)\s+")


def answers(path):
    """The case-name-to-answer mapping, from the first blank line on."""
    rows, started = {}, False
    for line in io.open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not started:
            # The header ends at the first blank line. Anything above it - the revision, a
            # participant's boundary - describes the column rather than answering a case.
            if not line.strip():
                started = True
            continue
        if not line.strip():
            continue
        name, _, value = MARK.sub("", line, count=1).partition(" ")
        rows[name] = value.strip()
    return rows


def verdicts(path):
    """Per case, the verdict word its runner printed: ACCEPTED, REJECTED, CRASH and the rest.

    Only the block-format runners print one. A line-format runner (substrait-python, Spark,
    Isthmus) prints the answer alone, and this comes back empty for it - which is why the caller
    passes the raw output rather than this being required.
    """
    kinds, name = {}, None
    for line in io.open(path, encoding="utf-8", errors="replace"):
        if line.startswith("##### "):
            name = line[6:].strip()
            continue
        m = VERDICT.match(line.strip())
        if m and name and name not in kinds:
            kinds[name] = m.group(1)
    return kinds


def refused(value):
    return value.startswith(("ERROR: ", "CRASH: "))


def main():
    old_path, new_path = sys.argv[1], sys.argv[2]
    label = sys.argv[3] if len(sys.argv) > 3 else "column"
    kinds = verdicts(sys.argv[4]) if len(sys.argv) > 4 else {}
    old, new = answers(old_path), answers(new_path)
    if not old:
        sys.exit("column_diff: %s carries no answers" % old_path)
    if not new:
        sys.exit("column_diff: %s carries no answers" % new_path)

    moved = [n for n in sorted(set(old) & set(new)) if old[n] != new[n]]
    gone = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))

    tally = {"answer": 0, "lost": 0, "gained": 0, "refusal": 0}
    for n in moved:
        was, now = refused(old[n]), refused(new[n])
        kind = ("refusal" if was and now else "lost" if now else "gained" if was else "answer")
        tally[kind] += 1
        # The verdict is printed beside the kind rather than instead of it: "lost" says the
        # comparison changed shape, the verdict says whether the engine rejected the plan or died
        # on it, and a run that turns rejections into crashes is a different finding from one that
        # rejects more.
        seen = kinds.get(n)
        print("  %-46s %s%s" % (n, kind, " (%s)" % seen if seen else ""))
        print("  %-46s was %s" % ("", old[n]))
        print("  %-46s now %s" % ("", new[n]))
    for n in gone:
        print("  %-46s answered before, absent now (was %s)" % (n, old[n]))
    for n in added:
        print("  %-46s answered now, absent before (%s)" % (n, new[n]))

    detail = ", ".join("%d %s" % (v, k) for k, v in tally.items() if v)
    print("%s: %d of %d answers moved%s, %d gone, %d new"
          % (label, len(moved), len(old), " (%s)" % detail if detail else "", len(gone), len(added)))
    sys.exit(1 if (moved or gone or added) else 0)


main()
