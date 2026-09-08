"""Reduces any probe's output to one column: "<case name> <answer>".

    python3 normalize.py <raw output> <format> <header> > COLUMN.txt

There are two formats, because the probes are built differently:

  block - "##### name" on its own line, then "TAG VERDICT value" (DataFusion, DuckDB, substrait-go,
          Acero, the validator). A case without exactly one verdict is a hole rather than an empty
          answer, and such a case is named on stderr with a non-zero exit code.
  line  - "name value" on one line (substrait-python, Spark, Isthmus).

Why a file of its own: normalization used to live in one-off scripts, so the column that reached the
comparison was not tied to the run that produced it. Now it is.
"""
import re, sys

VERDICT = re.compile(r"^(DATAFUSION|DUCKDB|SUBSTRAITGO|ACERO|VALIDATOR|SPARK|ISTHMUS)\s+(\S+)\s*(.*)$")
# There is exactly one SCHEMA verdict per case. The row lines (ROW/ROWS) that DuckDB and Gluten
# print belong to a different check and do not count as verdicts here: otherwise every case with
# rows would look like a case with three verdicts and drop out of the column.
SCHEMA_KINDS = {"ACCEPTED", "REJECTED", "CRASH", "SCHEMA", "ERROR", "LOADFAIL", "WARN", "NOTIMPL"}
# Verdicts that mean the participant refused rather than answered. An error is a fact about the
# implementation, and it has to reach the comparison in a form the comparison tells apart from a
# parsed schema.
REFUSAL = {"REJECTED", "CRASH", "ERROR", "LOADFAIL", "WARN", "NOTIMPL"}
# The validator prints a schema AND diagnostics for one case, so "exactly one verdict" is
# unreachable for it. The schema outranks the diagnostics: if the participant derived a schema, that
# is the answer, and the messages beside it are a separate column of observations, not a second one.
PRIORITY = ["ACCEPTED", "SCHEMA", "REJECTED", "ERROR", "CRASH", "LOADFAIL", "NOTIMPL", "WARN"]
ACCEPTING = {"ACCEPTED", "SCHEMA"}
REFUSING = {"REJECTED", "CRASH", "LOADFAIL", "NOTIMPL"}

# protobuf varies this marker between runs on purpose, so that debug output is not parsed as data.
# Left as it comes, one Acero cell changes on every run for a reason that has nothing to do with the
# measurement, and every run that saves columns dirties that file.
REDACTION = re.compile(r"goo\.gle/debug\w*\s+")

# DuckDB's InternalException carries a stack trace, and the trace is not the answer. On macOS it is
# mangled symbol names; in a Linux container it is the path of the loaded .so, which in a venv built
# by the run is a temporary directory with a different name every time. Two cells of the DuckDB
# column therefore could not reproduce anywhere but the machine they were taken on - found by
# running probe/replay_column.sh in a container, which is the only way this could have been found.
# The message before the trace is what the participant said; the raw output keeps the rest.
TRACE = re.compile(r"\s*Stack Trace:.*$")

def stable(value):
    return TRACE.sub("", REDACTION.sub("goo.gle/debug ", value))

def blocks(text):
    name, verdicts = None, []
    for line in text.splitlines():
        if line.startswith("##### "):
            if name is not None:
                yield name, verdicts
            name, verdicts = line[6:].strip(), []
            continue
        m = VERDICT.match(line.strip())
        if m and name is not None and m.group(2) in SCHEMA_KINDS:
            verdicts.append((m.group(2), m.group(3).strip()))
    if name is not None:
        yield name, verdicts

# A participant's boundaries are part of its column, not a comment beside it. They used to live in
# hand-written headers, and the first run that updated the columns wiped them out.
BOUNDARY = {
    "DUCKDB": "BOUNDARY: carries no nullability in its logical types - types, arity and order are compared.",
    "ACERO":  "Carries nullability (the probe prints f.nullable); it is compared alongside the types.",
    "SPARK":  "Carries nullability (StructField.nullable). Its refusals are loud: a fact about support, not a divergence.",
    "GLUTEN": "BOUNDARY: carries no nullability; types, arity, column order and rows are checked.",
    "DATAFUSION": "BOUNDARY: DataFusion maps varchar/fixedchar to Utf8, which carries no length.",
}

def main():
    raw, fmt, header = open(sys.argv[1], encoding="utf-8").read(), sys.argv[2], sys.argv[3]
    rows, holes = [], []
    if fmt == "block":
        for name, verdicts in blocks(raw):
            if not verdicts:
                holes.append("%s (no verdicts)" % name)
                continue
            kinds = {k for k, _ in verdicts}
            # A schema beside a diagnostic is normal (that is how the validator prints). Accepted
            # AND rejected at once is a contradiction: the priority list would silently pick one and
            # hide the other.
            if kinds & ACCEPTING and kinds & REFUSING:
                holes.append("%s (mutually exclusive verdicts: %s)" % (name, ", ".join(sorted(kinds))))
                continue
            kind, value = min(verdicts, key=lambda kv: PRIORITY.index(kv[0])
                              if kv[0] in PRIORITY else len(PRIORITY))
            value = stable(value)
            rows.append((name, ("ERROR: " + value) if kind in REFUSAL else value))
    elif fmt == "line":
        for line in raw.splitlines():
            name, _, value = line.rstrip().partition(" ")
            if name and value.strip() and not name.startswith("#"):
                rows.append((name, stable(value.strip())))
    else:
        sys.exit("unknown format: %s" % fmt)

    seen = {}
    for n, _ in rows:
        seen[n] = seen.get(n, 0) + 1
    dupes = sorted(n for n, c in seen.items() if c > 1)

    print(header)
    col_name = header.split(":")[0].strip()
    if col_name in BOUNDARY:
        print(BOUNDARY[col_name])
    print()
    for n, v in rows:
        print("%-46s %s" % (n, v))

    problem = 0
    if holes:
        print("NORMALIZE: cases without exactly one verdict: %s" % ", ".join(holes), file=sys.stderr)
        problem = 1
    if dupes:
        print("NORMALIZE: repeated cases: %s" % ", ".join(dupes), file=sys.stderr)
        problem = 1
    if not rows:
        print("NORMALIZE: the column is empty", file=sys.stderr)
        problem = 1
    sys.exit(problem)

main()
