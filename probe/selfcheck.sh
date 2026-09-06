#!/bin/bash
# Checks the repository against itself: no external checkout, no probe environment, no network.
# Every fact it checks is one file here against another file here.
#
#   bash probe/selfcheck.sh
#
# What it catches is the failure this corpus is most prone to: an edit to expected.py, to a column
# or to the README that leaves the three describing different things. Regenerating the corpus needs
# a substrait-java checkout and is not part of this; probe/reverify.sh does that.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAILED=0
fail() { echo "FAILED: $*" >&2; FAILED=1; }
ok()   { echo "ok      $*"; }

command -v python3 >/dev/null || { echo "FAILED: no python3" >&2; exit 1; }

echo "### generated files match their sources"
python3 probe/expected.py 2>/dev/null | diff -q - expected.json >/dev/null \
  && ok "expected.json is what probe/expected.py produces" \
  || fail "expected.json differs from probe/expected.py output"
python3 probe/matrix.py 2>/dev/null | diff -q - results/MATRIX.txt >/dev/null \
  && ok "results/MATRIX.txt is what probe/matrix.py produces from the saved columns" \
  || fail "results/MATRIX.txt differs from probe/matrix.py output"

echo
echo "### the saved columns agree with the expectations and with the README"
python3 - <<'PY' || FAILED=1
import io, re, subprocess, sys

COLUMNS = [("substrait-java", "JAVA", "java"), ("substrait-python", "PYTHON", "py"),
           ("substrait-go", "GO", "go"), ("substrait-validator", "VALIDATOR", "py"),
           ("Isthmus/Calcite", "ISTHMUS", "calcite"), ("DataFusion", "DATAFUSION", "df"),
           ("DuckDB", "DUCKDB", "duckdb"), ("Spark", "SPARK", "spark"), ("Acero", "ACERO", "acero")]
SUMMARY = re.compile(r"^matched: (\d+), differed: (\d+), unsupported by the participant: (\d+), "
                     r"unparsed by the check: (\d+),")

# The README carries a matched/differed/unsupported table. Nothing else checks those numbers, and a
# stale one is exactly the kind of lie this corpus exists to catch elsewhere.
#
# The table is found by its own header rather than by row shape: the README holds a second table of
# three numbers per implementation (how many answers move under a swapped declaration), and reading
# by shape alone silently took the wrong one.
HEADER = "| | matched | differed | unsupported |"
ROW = re.compile(r"^\|\s*([A-Za-z/-]+(?: [A-Za-z]+)?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*$")
readme, inside = {}, False
for line in io.open("README.md", encoding="utf-8"):
    if line.strip() == HEADER:
        inside = True
        continue
    if inside:
        m = ROW.match(line)
        if m:
            readme[m.group(1).strip()] = tuple(int(m.group(i)) for i in (2, 3, 4))
        elif not line.startswith("|"):
            inside = False
if not readme:
    print("FAILED: no results table found in README.md under %r" % HEADER)
    raise SystemExit(1)

# The README dates the table. That date went stale the first time the columns were retaken, and the
# tallies did not move, so nothing noticed. Gluten is left out: its column is taken in a cluster and
# carries its own date, and it is not in this table.
readme_text = io.open("README.md", encoding="utf-8").read()
stamp = re.search(r"taken (\d{4}-\d{2}-\d{2}) against the versions", readme_text)
taken = {re.search(r"column from run (\d{4}-\d{2}-\d{2})",
                   io.open("results/" + c + ".txt", encoding="utf-8").readline()).group(1)
         for _, c, _ in COLUMNS}
if not stamp:
    print("FAILED: the README no longer dates the results table")
    raise SystemExit(1)
if taken != {stamp.group(1)}:
    print("FAILED: the README dates the table %s, the columns were taken %s"
          % (stamp.group(1), ", ".join(sorted(taken))))
    raise SystemExit(1)
print("ok      the table is dated %s, matching every column" % stamp.group(1))

bad = 0
for label, col, fmt in COLUMNS:
    out = subprocess.run([sys.executable, "probe/check_expected.py", "results/" + col + ".txt", fmt],
                         capture_output=True, text=True).stdout
    if "INCOMPLETE" in out:
        print("FAILED: %s: %s" % (col, [l for l in out.splitlines() if l.startswith("INCOMPLETE")][0]))
        bad = 1
        continue
    m = SUMMARY.match(out.splitlines()[-1] if out.strip() else "")
    if not m:
        print("FAILED: %s: the check did not reach its summary" % col)
        bad = 1
        continue
    got = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if int(m.group(4)):
        print("FAILED: %s: the check could not parse %s answers" % (col, m.group(4)))
        bad = 1
    want = readme.get(label)
    if want is None:
        print("FAILED: %s: no row for %s in the README table" % (col, label))
        bad = 1
    elif want != got:
        print("FAILED: %s: README says %s, the check says %s" % (col, want, got))
        bad = 1
    else:
        print("ok      %-20s %s" % (label, got))
raise SystemExit(bad)
PY

echo
echo "### the swap table agrees with results/LIE.txt"
python3 - <<'LIEPY' || FAILED=1
import io, json, re, sys

# The README's second table says how many answers move when the declared output_type is swapped.
# results/LIE.txt is the per-case run behind it, so the counts can be derived from the file rather than
# trusted. "Moved" is follows plus changed: both mean the answer depends on the declaration, and the
# difference between them is only whether it matched the swap exactly.
MOVED = {"follows", "changed"}
lines = io.open("results/LIE.txt", encoding="utf-8").read().splitlines()
head = next(i for i, l in enumerate(lines) if l.startswith("case "))
names = lines[head].split()[1:]
verdicts = {n: {} for n in names}
for line in lines[head + 1:]:
    if not line.strip() or not line[0].isalnum():
        break
    cells = re.findall(r"\S+(?: \S+)?(?=\s{2,}|$)", line.rstrip())
    case, cells = cells[0], cells[1:]
    for n, v in zip(names, cells):
        verdicts[n][case] = v.strip()

have = set(json.load(open("expected.json", encoding="utf-8"))["expected"])
LABEL = {"JAVA": "substrait-java", "PYTHON": "substrait-python",
         "VALIDATOR": "substrait-validator", "DUCKDB": "DuckDB"}
counts = {}
for col, label in LABEL.items():
    moved = [c for c, v in verdicts.get(col, {}).items() if v in MOVED]
    counts[label] = (len(moved), len([c for c in moved if c in have]))

readme, inside = {}, False
for line in io.open("README.md", encoding="utf-8"):
    if line.strip().startswith("| | answers that move |"):
        inside = True
        continue
    if inside:
        m = re.match(r"^\|\s*([A-Za-z/-]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
        if m:
            readme[m.group(1).strip()] = (int(m.group(2)), int(m.group(3)))
        elif not line.startswith("|"):
            inside = False
bad = 0
if not readme:
    print("FAILED: no swap table found in README.md")
    bad = 1
for label, got in sorted(counts.items()):
    want = readme.get(label)
    if want is None:
        print("FAILED: %s: no row in the README swap table" % label); bad = 1
    elif want != got:
        print("FAILED: %s: README says %s, results/LIE.txt gives %s" % (label, want, got)); bad = 1
    else:
        print("ok      %-20s moved %d, of them with an expectation %d" % (label, got[0], got[1]))
raise SystemExit(bad)
LIEPY

echo
echo "### the corpus is whole"
python3 - <<'PY' || FAILED=1
import json, os, sys
cases = {f[:-5] for f in os.listdir("derived-schema") if f.endswith(".json") and f != "manifest.json"}
bins  = {f[:-4] for f in os.listdir("derived-schema") if f.endswith(".bin")}
vt    = {f[:-5] for f in os.listdir("derived-schema-virtual-tables") if f.endswith(".json")}
exp   = json.load(open("expected.json", encoding="utf-8"))
named = set(exp["expected"]) | set(exp["disputed"])
bad = 0
for what, got in (("binary protobuf", bins), ("derived-schema-virtual-tables", vt), ("expected.json", named)):
    if got != cases:
        print("FAILED: %s does not cover the same cases: missing %s, extra %s"
              % (what, sorted(cases - got)[:4], sorted(got - cases)[:4]))
        bad = 1
if not bad:
    print("ok      %d cases, each with a .bin, a virtual-table variant and an entry in expected.json"
          % len(cases))
raise SystemExit(bad)
PY

echo
echo "### the manifest agrees with the corpus and with the expectations"
python3 - <<'MANPY' || FAILED=1
import glob, io, json, os, re

# The manifest is rebuilt from the generators by gen/make_manifest.sh, which needs a substrait-java
# checkout. What can be checked here without one is that it still describes this corpus and these
# expectations, which is what goes stale first.
man = json.load(open("derived-schema/manifest.json", encoding="utf-8"))
exp = json.load(open("expected.json", encoding="utf-8"))
corpus = {os.path.basename(f)[:-5] for f in glob.glob("derived-schema/*.json")
          if not f.endswith("manifest.json")}
bad = 0
named = {e["case"] for e in man}
if named != corpus:
    print("FAILED: the manifest does not cover the corpus: missing %s, extra %s"
          % (sorted(corpus - named)[:4], sorted(named - corpus)[:4]))
    bad = 1
# A reason that points at its neighbour is a reason that stops being true when the file is sorted,
# and expected.json is written sorted by key. One "same" ended up under an unrelated entry and said
# something false about the case it belonged to.
BACKREF = {"same", "ditto", "as above", "the same", "same as above"}
for case, why in sorted(exp["disputed"].items()):
    if why.strip().strip(".").lower() in BACKREF:
        print("FAILED: %s: its reason for being disputed points at another entry: %r" % (case, why))
        bad = 1

for e in man:
    for field in ("plan", "binary", "generator", "note", "expectation"):
        if not e.get(field):
            print("FAILED: %s: the manifest entry has no %s" % (e["case"], field)); bad = 1
    for field, suffix in (("plan", ".json"), ("binary", ".bin")):
        if e.get(field) and not os.path.exists(os.path.join("derived-schema", e[field])):
            print("FAILED: %s: %s does not exist" % (e["case"], e[field])); bad = 1
    want = exp["expected"].get(e["case"])
    got = e.get("expectation", {})
    if want and got.get("schema") != want["schema"]:
        print("FAILED: %s: the manifest schema differs from expected.json" % e["case"]); bad = 1
    if not want and "schema" in got:
        print("FAILED: %s: the manifest carries a schema the expectations do not" % e["case"]); bad = 1
# The README states in prose how many cases name a source issue. That number went stale the first
# time one was added, so it is checked here with the rest.
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10}
with_source = sum(1 for e in man if "source" in e)
claim = re.search(r"([A-Za-z]+|\d+) cases have one so far", io.open("README.md", encoding="utf-8").read())
if not claim:
    print("FAILED: the README no longer says how many cases name a source issue"); bad = 1
else:
    said = WORDS.get(claim.group(1).lower(), None)
    if said is None and claim.group(1).isdigit():
        said = int(claim.group(1))
    if said != with_source:
        print("FAILED: the README says %s cases name a source issue, the manifest has %d"
              % (claim.group(1), with_source))
        bad = 1
if not bad:
    print("ok      %d entries, %d naming a source issue, all expectations matching expected.json"
          % (len(man), with_source))
raise SystemExit(bad)
MANPY

echo
echo "### syntax"
SYNTAX=0
for f in probe/*.py; do python3 -m py_compile "$f" || { fail "python syntax: $f"; SYNTAX=1; }; done
for f in probe/*.sh gen/*.sh; do bash -n "$f" || { fail "bash syntax: $f"; SYNTAX=1; }; done
rm -rf probe/__pycache__
[ "$SYNTAX" -eq 0 ] && ok "python and bash sources parse"

echo
echo "### hygiene"
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  FILES="$(git -C "$ROOT" ls-files)"
else
  FILES="$(find . -type f -not -path "./.git/*" -not -path "./.probe-env/*" -not -path "./gen/out/*" \
           -not -name classpath.txt | sed 's|^\./||')"
fi
FILES="$FILES" python3 - <<'PY' || FAILED=1
import io, os, re, sys
files = os.environ["FILES"].split()
bad = 0
# An absolute path into one machine's home or scratch directory is what made the harness unrunnable
# for anyone else; it must not come back. Nor must untranslated text.
#
# Both patterns are assembled from parts rather than written out, so that this file does not match
# itself: a check that trips on its own source is a check nobody keeps.
ROOTS = ["Users", "home", "private/tmp", "opt/homebrew", "Library/Java"]
PATHS = re.compile(r"(?:^|[\"' =(])" + "/(?:%s)/" % "|".join(ROOTS))
CYRILLIC = re.compile("[\u0400-\u04ff]")
for name in files:
    if name in ("LICENSE", "gen/classpath.txt"):
        continue
    try:
        text = io.open(name, encoding="utf-8").read()
    except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
        continue
    for line_no, line in enumerate(text.splitlines(), 1):
        if PATHS.search(line):
            print("FAILED: absolute path in %s:%d" % (name, line_no)); bad = 1
        if CYRILLIC.search(line):
            print("FAILED: untranslated text in %s:%d" % (name, line_no)); bad = 1
if "gen/classpath.txt" in files:
    print("FAILED: gen/classpath.txt is committed; it is machine-specific"); bad = 1
if not bad:
    print("ok      %d tracked files, no absolute paths, no untranslated text" % len(files))
raise SystemExit(bad)
PY

echo
if [ "$FAILED" -ne 0 ]; then echo "RESULT: the repository contradicts itself"; exit 1; fi
echo "RESULT: the repository agrees with itself"
