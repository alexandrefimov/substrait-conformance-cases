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
python3 probe/diffs.py 2>/dev/null | diff -q - results/DIFFS.md >/dev/null \
  && ok "results/DIFFS.md is what probe/diffs.py joins out of differed.json and the columns" \
  || fail "results/DIFFS.md differs from probe/diffs.py output"
# The picture in the README and the page on the site are generated from the same columns. A drawing
# that has drifted from them is the failure this repository exists to catch, and it drifts silently:
# nobody rereads an SVG.
for want in svg-light:docs/matrix.svg svg-dark:docs/matrix-dark.svg page:docs/index.html; do
  python3 probe/heatmap.py "${want%%:*}" 2>/dev/null | diff -q - "${want#*:}" >/dev/null \
    && ok "${want#*:} is what probe/heatmap.py draws from the saved columns" \
    || fail "${want#*:} differs from probe/heatmap.py output"
done

# The coverage block in the README is generated too, and unlike the files above it lives inside a
# page a person edits by hand, which is the one place a generated thing quietly gets improved.
python3 - <<'COVPY' || FAILED=1
import io, re, subprocess, sys
want = subprocess.run([sys.executable, "probe/coverage.py"], capture_output=True, text=True)
if want.returncode:
    print("FAILED: probe/coverage.py: %s" % want.stderr.strip().splitlines()[-1:])
    raise SystemExit(1)
page = io.open("README.md", encoding="utf-8").read()
got = re.search(r"<!-- coverage:.*?<!-- /coverage -->", page, re.S)
if not got:
    print("FAILED: the README no longer carries the coverage block probe/coverage.py writes")
    raise SystemExit(1)
if got.group(0).strip() != want.stdout.strip():
    print("FAILED: the README's coverage block differs from probe/coverage.py output")
    raise SystemExit(1)
print("ok      the README's coverage block is what probe/coverage.py counts from the plans")
COVPY

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
stamp = re.search(r"taken (\d{4}-\d{2}-\d{2}(?:, \d{4}-\d{2}-\d{2})*) against the versions", readme_text)
taken = {re.search(r"column from run (\d{4}-\d{2}-\d{2})",
                   io.open("results/" + c + ".txt", encoding="utf-8").readline()).group(1)
         for _, c, _ in COLUMNS}
if not stamp:
    print("FAILED: the README no longer dates the results table")
    raise SystemExit(1)
if stamp.group(1) != ", ".join(sorted(taken)):
    print("FAILED: the README dates the table %s, the columns were taken %s"
          % (stamp.group(1), ", ".join(sorted(taken))))
    raise SystemExit(1)
print("ok      the table is dated %s, matching every column" % stamp.group(1))

# Parameter widths and nullability must survive normalization independently of
# the particular widths in the saved stringlen_declared result.
src = io.open("probe/check_expected.py", encoding="utf-8").read()
parsers = {"__file__": "probe/check_expected.py"}
exec(src[:src.index("# --- the command line starts here ---")], parsers)
sample = "[a:extension<varchar{length:17}>, b:extension<fixed_char{length:8}>?, c:fixed_size_binary[6], d:binary?]"
if parsers["parse_acero"](sample) != [["vchar(17)", False], ["fchar(8)", True], ["fbin(6)", False], ["bin", True]]:
    print("FAILED: Acero parameterized-type parser lost a width, kind or nullability")
    raise SystemExit(1)
print("ok      Acero parameterized types retain widths, kinds and nullability")

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
echo "### the drawn matrix agrees with the check, cell by cell"
python3 - <<'DRAWPY' || FAILED=1
import io, json, re, subprocess, sys

# docs/ is byte-identical to probe/heatmap.py output by the check above, which says the files match
# the generator - not that the generator reads a column the way check_expected.py does. It has its
# own loop over the saved columns, and two loops over the same files are exactly how a drawing comes
# to disagree with the numbers beside it. So the cells are compared with the check itself: the same
# per-participant tallies, and the differing cases by name rather than by count, since a swap of one
# case for another keeps every count intact.
COLUMNS = [("substrait-java", "JAVA", "java"), ("substrait-python", "PYTHON", "py"),
           ("substrait-go", "GO", "go"), ("substrait-validator", "VALIDATOR", "py"),
           ("Isthmus/Calcite", "ISTHMUS", "calcite"), ("DataFusion", "DATAFUSION", "df"),
           ("DuckDB", "DUCKDB", "duckdb"), ("Spark", "SPARK", "spark"), ("Acero", "ACERO", "acero")]
DIFFERING = (1, 2, 3)   # divergence, type-system boundary, unresolved - see probe/heatmap.py

page = io.open("docs/index.html", encoding="utf-8").read()
found = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
if not found:
    print("FAILED: docs/index.html carries no data for the matrix")
    raise SystemExit(1)
drawn = json.loads(found.group(1))

bad = 0
for label, col, fmt in COLUMNS:
    out = subprocess.run([sys.executable, "probe/check_expected.py", "results/%s.txt" % col, fmt],
                         capture_output=True, text=True).stdout
    summary = re.search(r"^matched: (\d+), differed: (\d+), unsupported by the participant: (\d+)",
                        out, re.M)
    if not summary:
        print("FAILED: %s: the check did not reach its summary" % col)
        bad = 1
        continue
    want = [int(summary.group(i)) for i in (1, 2, 3)]
    named = set(re.findall(r"^  (\S+)\s+expected ", out, re.M))
    c = drawn["participants"].index(label)
    cells = {drawn["cases"][r] for r in range(len(drawn["cases"]))
             if drawn["cells"][r][c] in DIFFERING}
    if drawn["scored"][label] != want:
        print("FAILED: %s: the drawing tallies %s, the check %s" % (label, drawn["scored"][label], want))
        bad = 1
    if cells != named:
        only = sorted(named - cells) or sorted(cells - named)
        print("FAILED: %s: the drawing and the check disagree on %d cases: %s"
              % (label, len(named ^ cells), ", ".join(only[:4])))
        bad = 1
    if drawn["scored"][label] == want and cells == named:
        print("ok      %-20s %s, %d differing cases by name" % (label, want, len(named)))
raise SystemExit(bad)
DRAWPY

echo
echo "### the picture draws the cells the page carries"
python3 - <<'SVGPY' || FAILED=1
import collections, io, json, re, sys

# The cell check above reads docs/index.html, which carries the verdicts as data. The two SVGs carry
# them only as shapes, and nobody rereads an SVG: a drawing loop that skipped a state would keep the
# files byte-identical to the generator and agree with every number on the page. So the shapes are
# counted by their fill and compared with the cells - one more of each than the matrix holds, since
# the legend draws one swatch per state.
sys.path.insert(0, "probe")
import heatmap   # for the palette only; the counts come from the drawn files and the page

page = io.open("docs/index.html", encoding="utf-8").read()
found = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
if not found:
    print("FAILED: docs/index.html carries no data for the matrix")
    raise SystemExit(1)
cells = collections.Counter(s for row in json.loads(found.group(1))["cells"] for s in row)

bad = 0
for theme, path in (("light", "docs/matrix.svg"), ("dark", "docs/matrix-dark.svg")):
    t = heatmap.THEMES[theme]
    svg = io.open(path, encoding="utf-8").read()
    drawn = {
        heatmap.MATCH: svg.count('fill="%s"' % t["match"]),
        heatmap.DIVERGENCE: svg.count('fill="%s"' % t["divergence"]),
        heatmap.UNRESOLVED: svg.count('fill="%s"' % t["unresolved"]),
        heatmap.BOUNDARY: svg.count('fill="url(#hatch)"'),
        heatmap.NOSPEC: svg.count('fill="url(#dots)"'),
        heatmap.UNSUPPORTED: len(re.findall(r'fill="none" stroke="%s" stroke-width="0.8"' % t["rule"], svg)),
    }
    off = {heatmap.STATE_NAME[s]: (n, cells[s] + 1) for s, n in drawn.items() if n != cells[s] + 1}
    if off:
        print("FAILED: %s draws %s where the page has %s"
              % (path, {k: v[0] for k, v in off.items()}, {k: v[1] for k, v in off.items()}))
        bad = 1
    else:
        print("ok      %-22s %d shapes, one per cell and one per legend swatch"
              % (path, sum(drawn.values())))
raise SystemExit(bad)
SVGPY

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

# The swap table moved to METHOD.md when the README was split by audience, so both pages are read
# as one. Which file a table sits in is a decision about readers; the check is about the numbers.
readme, inside = {}, False
for line in list(io.open("README.md", encoding="utf-8")) + list(io.open("METHOD.md", encoding="utf-8")):
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
echo "### the virtual-table corpus is what its generator produces"
python3 - <<'VTPY' || FAILED=1
import filecmp, os, shutil, subprocess, sys, tempfile

# derived-schema-virtual-tables/ is generated by probe/to_virtual_tables.py and committed next to it,
# and nothing checked the pair: an edit to either could sit there until someone regenerated by hand.
# Everything else generated here is either checked below or rebuilt by reverify.sh; this one needs no
# Java and no environment, so it belongs in the seconds-long check.
tmp = tempfile.mkdtemp()
try:
    r = subprocess.run([sys.executable, "probe/to_virtual_tables.py", "derived-schema", tmp],
                       capture_output=True, text=True)
    if r.returncode:
        print("FAILED: to_virtual_tables.py returned %d: %s" % (r.returncode, r.stderr.strip()[:120]))
        raise SystemExit(1)
    left = sorted(f for f in os.listdir("derived-schema-virtual-tables"))
    right = sorted(os.listdir(tmp))
    if left != right:
        print("FAILED: the virtual-table corpus has a different set of files than its generator makes")
        raise SystemExit(1)
    match, mismatch, errors = filecmp.cmpfiles("derived-schema-virtual-tables", tmp, left, shallow=False)
    if mismatch or errors:
        print("FAILED: %d differ from what the generator produces: %s"
              % (len(mismatch) + len(errors), ", ".join((mismatch + errors)[:4])))
        raise SystemExit(1)
    print("ok      %d cases, byte-identical to probe/to_virtual_tables.py output" % len(match))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
VTPY

echo
echo "### every differing cell is classified"
python3 probe/check_differed.py || FAILED=1

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
# The prose lives on whichever page suits the reader - the count moved to METHOD.md when the README
# was split - so both are searched rather than the sentence being pinned to one file.
pages = "".join(io.open(f, encoding="utf-8").read() for f in ("README.md", "METHOD.md"))
claim = re.search(r"([A-Za-z]+|\d+) cases have one so far", pages)
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
echo "### the pages state the numbers the files hold"
# The table above is checked against check_expected.py; the sentences around it were not checked at
# all, and that is where the numbers went stale.
python3 probe/check_pages.py || FAILED=1

echo
echo "### every link between the pages resolves"
python3 - <<'LINKPY' || FAILED=1
import io, os, re, sys

# The pages point at each other and at files in the repository, and a split of the README moves
# targets around. A broken link here is the kind of thing a reader finds and the author never does.
#
# The pages are found by walking the tree rather than by asking git: selfcheck-negative.sh runs in a
# copy with no .git, where `git ls-files` returns nothing, and the first version of this check passed
# there by examining no pages at all. Finding none is now a failure rather than a clean run.
pages = []
for here, dirs, names in os.walk("."):
    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".probe-env")]
    pages += [os.path.normpath(os.path.join(here, n)) for n in names if n.endswith(".md")]
if len(pages) < 3:
    print("FAILED: only %d pages found to check links in; that is not this repository" % len(pages))
    raise SystemExit(1)
bad = 0
checked = 0
for page in pages:
    base = os.path.dirname(page)
    text = io.open(page, encoding="utf-8").read()
    targets = [m.group(1) for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", text)]
    targets += [m.group(1) for m in re.finditer(r'(?:src|srcset)="([^"]+)"', text)]
    for target in targets:
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        checked += 1
        path = os.path.normpath(os.path.join(base, target.split("#")[0]))
        if not os.path.exists(path):
            print("FAILED: %s links to %s, which does not exist" % (page, target))
            bad = 1
            continue
        # A wrong anchor is the quiet half of a broken link: the page opens, at the top, and the
        # reader is left looking for a section that was renamed. Only headings in these pages are
        # checked, by the slug GitHub builds from them.
        anchor = target.split("#")[1] if "#" in target else ""
        if anchor and path.endswith(".md"):
            headings = io.open(path, encoding="utf-8").read()
            slugs = set()
            for line in headings.splitlines():
                m = re.match(r"^#+\s+(.*?)\s*$", line)
                if m:
                    slug = re.sub(r"[^\w\- ]", "", m.group(1).lower()).replace(" ", "-")
                    slugs.add(slug)
            if anchor not in slugs:
                print("FAILED: %s links to %s, and %s has no heading with that anchor"
                      % (page, target, path))
                bad = 1
if not bad:
    print("ok      %d links across %d pages, all resolving" % (checked, len(pages)))
raise SystemExit(bad)
LINKPY

echo
echo "### the participants CI retakes are the ones the script accepts"
# Five places name that list: the case labels in replay_column.sh, the two usage lines beside them,
# and the matrix of each workflow. Adding a participant to the script and not to a workflow leaves a
# column nobody retakes while the pages say otherwise, and adding it to one workflow and not the
# other leaves it checked against the pin but never against a release. Neither is visible in a diff.
python3 - <<'MATRIXPY' || FAILED=1
import io, re, sys

script = io.open("probe/replay_column.sh", encoding="utf-8").read()
# Anchored on SETUP_KEY, so the usage line and the catch-all arm cannot be mistaken for a case.
cases = set(re.findall(r"^\s*([A-Z]+)\)\s+SETUP_KEY=", script, re.M))
if not cases:
    print("FAILED: no participants found in probe/replay_column.sh")
    raise SystemExit(1)

sources = {"probe/replay_column.sh case labels": cases}
for m in re.finditer(r"replay_column\.sh ([A-Z|]+)", script):
    line = script[:m.start()].count("\n") + 1
    sources["probe/replay_column.sh:%d" % line] = set(m.group(1).split("|"))
for wf in ("selfcheck", "drift"):
    path = ".github/workflows/%s.yml" % wf
    text = io.open(path, encoding="utf-8").read()
    m = re.search(r"^\s*column:\s*\[([^\]]*)\]", text, re.M)
    if not m:
        print("FAILED: %s has no column matrix" % path)
        raise SystemExit(1)
    sources[path] = {n.strip() for n in m.group(1).split(",") if n.strip()}

bad = 0
for name, got in sorted(sources.items()):
    if got != cases:
        print("FAILED: %s names %s; the script accepts %s"
              % (name, ", ".join(sorted(got)) or "nobody", ", ".join(sorted(cases))))
        bad = 1
if not bad:
    print("ok      %d participants, the same in the script, its usage and both workflows: %s"
          % (len(cases), ", ".join(sorted(cases))))
raise SystemExit(bad)
MATRIXPY

echo
echo "### the drift log says what it claims to say"
# results/DRIFT.txt is the one file in this repository a workflow writes rather than a person, and
# it is written a week at a time by a job nobody watches. What can be checked is its shape: that
# every block names a day, one of the participants the replay accepts and the revision it was built
# from; that the days do not run backwards; and that each block carries the two lines that let a
# reader tell a moved answer from a changed corpus. A malformed block would otherwise sit there
# looking like a record.
python3 - <<'DRIFTPY' || FAILED=1
import io, re, sys

LOG = "results/DRIFT.txt"
script = io.open("probe/replay_column.sh", encoding="utf-8").read()
known = set(re.findall(r"^\s*([A-Z]+)\)\s+SETUP_KEY=", script, re.M))

lines = io.open(LOG, encoding="utf-8").read().split("\n")
HEAD = re.compile(r"^##### (\d{4}-\d{2}-\d{2})  ([A-Z]+)  (\S.*)$")
bad, blocks, previous = 0, 0, ""
for i, line in enumerate(lines):
    if not line.startswith("#####"):
        continue
    m = HEAD.match(line)
    if not m:
        print("FAILED: %s:%d is not a block header: %r" % (LOG, i + 1, line)); bad = 1; continue
    day, who, revision = m.groups()
    blocks += 1
    if who not in known:
        print("FAILED: %s:%d names %s, which the replay does not accept" % (LOG, i + 1, who)); bad = 1
    if day < previous:
        print("FAILED: %s:%d is dated %s, after a block dated %s" % (LOG, i + 1, day, previous)); bad = 1
    previous = max(previous, day)
    # The line under the header is what tells a participant that moved from a corpus that changed.
    if i + 1 >= len(lines) or not re.match(r"^corpus \S+, inputs [0-9a-f]+$", lines[i + 1]):
        print("FAILED: %s:%d has no corpus and fingerprint line under it"
              % (LOG, i + 1)); bad = 1
    # And the block has to end in the summary the comparison prints, or it records no count at all.
    tail = [l for l in lines[i + 2:] if l.startswith("#####")][:1]
    stop = lines.index(tail[0]) if tail else len(lines)
    if not any(re.match(r"^%s: \d+ of \d+ answers moved" % who, l) for l in lines[i + 2:stop]):
        print("FAILED: the block at %s:%d never says how many answers moved" % (LOG, i + 1)); bad = 1
if not bad:
    print("ok      %d recorded move(s), each dated, attributed and counted" % blocks)
raise SystemExit(bad)
DRIFTPY

echo
echo "### the comparison a replayed column is judged by can tell a difference"
# probe/replay_column.sh rebuilds a participant's environment and requires the answers to be
# identical to the saved column. Everything about that run - the pinned version, the fresh venv, the
# workflow - is worth nothing if the comparison at the end cannot report a difference, and a
# comparison that always agrees looks exactly like a column that always reproduces. So it is given
# columns that differ in each of the ways a column can differ, and required to say so.
python3 - <<'DIFFPY' || FAILED=1
import io, os, subprocess, sys, tempfile

COLUMN = "results/GO.txt"


def rows(text):
    head, _, body = text.partition("\n\n")
    return head, [l for l in body.split("\n") if l.strip()]


def written(tmp, name, lines, head):
    path = os.path.join(tmp, name)
    io.open(path, "w", encoding="utf-8").write(head + "\n\n" + "\n".join(lines) + "\n")
    return path


def diff(a, b):
    p = subprocess.run([sys.executable, "probe/column_diff.py", a, b, "T"],
                       capture_output=True, text=True)
    return p.returncode, p.stdout


head, body = rows(io.open(COLUMN, encoding="utf-8").read())
schema = next(i for i, l in enumerate(body) if not l.split(None, 1)[1].startswith("ERROR:"))
refusal = next(i for i, l in enumerate(body) if l.split(None, 1)[1].startswith("ERROR:"))
bad = 0

with tempfile.TemporaryDirectory() as tmp:
    same = written(tmp, "same.txt", body, "T: a second take")
    rc, out = diff(COLUMN, same)
    if rc != 0 or "0 of %d answers moved" % len(body) not in out:
        print("FAILED: two takes of one column were not called identical: %s" % out.strip()); bad = 1

    # The three ways an answer can move. They are not one case: a schema that became a refusal and a
    # refusal that became a schema are opposite findings, and the second is what an upstream fix
    # looks like from here.
    for label, index, value, kind in (
        ("a changed schema", schema, "[made:up]", "answer"),
        ("an answer that became a refusal", schema, "ERROR: made up", "lost"),
        ("a refusal that became an answer", refusal, "[made:up]", "gained"),
    ):
        lines = list(body)
        name = lines[index].split(None, 1)[0]
        lines[index] = "%-46s %s" % (name, value)
        rc, out = diff(COLUMN, written(tmp, "moved.txt", lines, "T: a second take"))
        if rc == 0:
            print("FAILED: %s was not reported as a difference" % label); bad = 1
        elif name not in out or "1 %s" % kind not in out:
            print("FAILED: %s was reported, but not as '%s' against %s: %s"
                  % (label, kind, name, out.strip().splitlines()[-1])); bad = 1

    # A case that stopped being answered at all. The count guard in replay_column.sh catches a short
    # column first, but the comparison must not call a missing case an agreement either.
    lines = [l for i, l in enumerate(body) if i != schema]
    rc, out = diff(COLUMN, written(tmp, "short.txt", lines, "T: a second take"))
    if rc == 0 or "1 gone" not in out:
        print("FAILED: a case dropped from the column was not reported: %s" % out.strip()); bad = 1

if not bad:
    print("ok      identical columns agree; a changed, lost, gained or dropped answer is reported")
raise SystemExit(bad)
DIFFPY

echo
echo "### syntax"
python3 probe/test_spark_runtime.py \
  && ok "Spark runtime checks reject incomplete results and incorrect runtimes" \
  || fail "Spark runtime result checks failed"
python3 probe/structural_cases.py --verify-fixtures \
  && ok "focused structural fixtures and their controls are complete" \
  || fail "focused structural fixtures are incomplete"
SYNTAX=0
for f in probe/*.py; do python3 -m py_compile "$f" || { fail "python syntax: $f"; SYNTAX=1; }; done
for f in probe/*.sh gen/*.sh; do bash -n "$f" || { fail "bash syntax: $f"; SYNTAX=1; }; done
rm -rf probe/__pycache__
[ "$SYNTAX" -eq 0 ] && ok "python and bash sources parse"

echo
echo "### hygiene"
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # Tracked files and new ones that are not ignored. Tracked alone meant a file was exempt until it
  # was staged, so "selfcheck green, then commit" said nothing about the file being added - which is
  # exactly how a new script carrying an absolute path went in and turned CI red.
  FILES="$(git -C "$ROOT" ls-files --cached --others --exclude-standard)"
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
