"""Turns the Gluten probe's output into a column, the way normalize.py does for the others.

    python3 probe/gluten_column.py <raw output> "<header line>" [--no-boundary] > results/GLUTEN.txt

Gluten is run in a cluster rather than by reverify.sh, so its column used to be assembled by hand
after each run. That left the one transformation nobody could repeat: how a Velox exception - which
arrives with a Retriable flag, a function, a file, a line and a forty-frame stack - becomes the one
line a column holds. It is kept here instead: everything from " Retriable:" onwards is dropped, and
what remains is the message Velox actually raised.
"""
import io, re, sys

RAW, HEADER = sys.argv[1], sys.argv[2]
# The rows variant carries its own header and says what it is for; the boundary line belongs to the
# schema column, where the numbers are read against the expectations.
WITH_BOUNDARY = "--no-boundary" not in sys.argv[3:]
BOUNDARY = ("BOUNDARY: carries no nullability; types, arity, column order and rows are checked.")

rows = []
for line in io.open(RAW, encoding="utf-8"):
    m = re.match(r"^CASE (\S+) \| (.*)$", line.rstrip("\n"))
    if not m:
        continue
    answer = m.group(2)
    for cut in (" Retriable:", " Stack trace:"):
        at = answer.find(cut)
        if at >= 0:
            answer = answer[:at]
    rows.append((m.group(1), answer))

# A run that produced nothing, or half a corpus, used to be indistinguishable from a column of
# refusals once it was written to a file.
if len(rows) < 70:
    raise SystemExit("FAILED: only %d cases in %s; that is not a whole run" % (len(rows), RAW))
seen = {}
for name, _ in rows:
    seen[name] = seen.get(name, 0) + 1
dupes = [n for n, c in seen.items() if c > 1]
if dupes:
    raise SystemExit("FAILED: %s appears more than once" % ", ".join(sorted(dupes)[:4]))

# The header can carry more than one line: this column records, besides the run, what the corpus
# variant does to an empty table, which is the difference between 19 accepted cases and 25.
print(HEADER.rstrip("\n"))
if WITH_BOUNDARY and BOUNDARY not in HEADER:
    print(BOUNDARY)
print()
for name, answer in sorted(rows):
    print("%s  %s" % (name, answer))
