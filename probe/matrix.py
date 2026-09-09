"""Builds results/MATRIX.txt from the saved columns: case x implementation.

    python3 probe/matrix.py [column directory] > results/MATRIX.txt

By default the columns are read from results/, where `reverify.sh UPDATE_COLUMNS=1` puts them.

The list of cases comes from the corpus, not from the columns: otherwise a case lost by every
participant at once would vanish from the table instead of showing an empty row.
"""
import io, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COLDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results")
CASES = os.path.join(ROOT, "derived-schema")

COLUMNS = [("substrait-java", "JAVA"), ("Isthmus", "ISTHMUS"), ("python", "PYTHON"),
           ("validator", "VALIDATOR"), ("substrait-go", "GO"), ("Spark", "SPARK"),
           ("DataFusion", "DATAFUSION"), ("DuckDB", "DUCKDB"), ("Acero", "ACERO"),
           ("Gluten", "GLUTEN")]
WIDTH = 34

corpus = sorted(f[:-5] for f in os.listdir(CASES)
                if f.endswith(".json") and not f.endswith("manifest.json"))
cset = set(corpus)

def load(stem):
    path = os.path.join(COLDIR, stem + ".txt")
    out = {}
    if not os.path.exists(path):
        return out
    for line in io.open(path, encoding="utf-8"):
        name, _, value = line.rstrip().partition(" ")
        if name in cset:
            out[name] = value.strip()
    return out

data = {label: load(stem) for label, stem in COLUMNS}

def short(v):
    v = (v.replace("Struct{nullable=false, fields=[", "{")
          .replace("nullable=true", "N").replace("nullable=false", "R")
          .replace("ERROR: ", "- "))
    return v if len(v) <= WIDTH else v[:WIDTH - 1] + "…"

# A column that does not cover the whole corpus is a hole, not a detail: without an explicit check
# the table called itself "10 x 78" while Gluten had 74 answers. Partial coverage is allowed only
# with a recorded reason, and then it is printed in the header rather than passed over.
EXPECTED_PARTIAL = {
    "Gluten": "four *_ALL cases are not expressible in its proto (see results/GLUTEN.txt)",
}

header = ("%-46s" % "case"
          + "".join("%-*s" % (WIDTH, label) for label, _ in COLUMNS)).rstrip()
missing = [label for label, _ in COLUMNS if not data[label]]
partial = [(label, len(data[label])) for label, _ in COLUMNS
           if data[label] and len(data[label]) < len(corpus)]
undeclared = [(l, n) for l, n in partial if l not in EXPECTED_PARTIAL]

print("Schema derivation matrix: %d implementations x %d cases." % (len(COLUMNS), len(corpus)))
print("Built by probe/matrix.py from the columns in %s." % os.path.relpath(COLDIR, ROOT))
# One table out of columns taken on different days reads as one snapshot unless it says otherwise:
# nine are retaken together by reverify.sh, and the Gluten column is taken in a cluster on its own
# schedule. Each date is read from the column's own first line, and a column whose header carries no
# date is named as undated rather than dropped - the first version of this looked for the wording
# reverify.sh writes, did not find it in the Gluten header, which is written by hand, and announced
# that every column had been taken on the same day.
taken = {}
for label, stem in COLUMNS:
    path = os.path.join(COLDIR, stem + ".txt")
    if not os.path.exists(path):
        continue
    when = re.search(r"\d{4}-\d{2}-\d{2}", io.open(path, encoding="utf-8").readline())
    taken.setdefault(when.group(0) if when else "an undated run", []).append(label)
if len(taken) == 1:
    print("Every column taken %s." % next(iter(taken)))
else:
    main = max(taken.items(), key=lambda kv: len(kv[1]))
    others = "; ".join("%s %s" % (", ".join(sorted(v)), d)
                       for d, v in sorted(taken.items()) if d != main[0])
    print("Columns taken %s, except: %s." % (main[0], others))
print("Versions are in probe/versions.env. Full values and each participant's boundaries are in results/<NAME>.txt.")
print("BOUNDARIES: DuckDB is the only participant carrying no nullability - for it types, arity and")
print("order are compared. Acero and Spark carry it and are compared on it. Gluten takes no part in")
print("the comparison against the expectations at all.")
print("String length is lost by DataFusion and DuckDB: their type systems have no string with a length.")
print("\u00b7 means the case was not run through that implementation.")
if missing:
    print("NO COLUMN: %s" % ", ".join(missing))
for label, n in partial:
    print("PARTIAL COLUMN: %s - %d of %d%s"
          % (label, n, len(corpus),
             ", " + EXPECTED_PARTIAL[label] if label in EXPECTED_PARTIAL else ""))
print()
print(header)
print("-" * len(header))
for case in corpus:
    # rstrip, because every column is padded to WIDTH including the last, so a short answer there -
    # "·", or a one-word rejection - left the line ending in spaces. `git diff --check` is a
    # repository gate and reads only added lines, so a file already carrying them passed until a new
    # case was added, and then the gate failed on a row nobody had written by hand.
    print(("%-46s" % case + "".join("%-*s" % (WIDTH, short(data[label].get(case, "·")))
                                    for label, _ in COLUMNS)).rstrip())

if missing or undeclared:
    sys.exit("the matrix is incomplete: %s" % ", ".join(missing + [l for l, _ in undeclared]))
