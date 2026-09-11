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
# The row half of the corpus is narrower than the schema half, and the narrowness is load-bearing.
# All three executing probes print a ROWS line only for a single-column result, and the DataFusion
# one collects Int64 alone; probe/check_rows.py then compares what it reads as a multiset of
# integers. A row expectation of any other shape has no path: the probes emit nothing, and
# check_rows.py reports "plan accepted, no rows returned", which lands on the participant as a
# divergence when the limit is this harness's. So the shape is asserted here, where a new expectation
# is added, rather than discovered on a full sweep that needs every toolchain to run at all.
python3 - <<'ROWSPY' || FAILED=1
import io, json, sys
rows = json.load(io.open("expected.json", encoding="utf-8"))["rows"]
bad = [c for c, e in sorted(rows.items())
       if not isinstance(e["rows"], list) or not all(isinstance(v, int) and not isinstance(v, bool)
                                                     for v in e["rows"])]
if bad:
    print("FAILED: %s carr%s a row expectation that is not a list of integers, which no probe can "
          "produce and probe/check_rows.py cannot compare" % (", ".join(bad), "ies" if len(bad) == 1 else "y"))
    raise SystemExit(1)
print("ok      %d row expectations, each a multiset of integers, which is what the probes emit"
      % len(rows))
ROWSPY

# The picture in the README and the page on the site are generated from the same columns. A drawing
# that has drifted from them is the failure this repository exists to catch, and it drifts silently:
# nobody rereads an SVG.
for want in svg-light:docs/matrix.svg svg-dark:docs/matrix-dark.svg page:docs/index.html; do
  python3 probe/heatmap.py "${want%%:*}" 2>/dev/null | diff -q - "${want#*:}" >/dev/null \
    && ok "${want#*:} is what probe/heatmap.py draws from the saved columns" \
    || fail "${want#*:} differs from probe/heatmap.py output"
done

# The coverage block is generated too, and unlike the files above it lives inside a page a person
# edits by hand, which is the one place a generated thing quietly gets improved. It sits in
# METHOD.md: breadth of a corpus is what that page is for, and the README had grown into a second
# copy of the site.
python3 - <<'COVPY' || FAILED=1
import io, re, subprocess, sys
want = subprocess.run([sys.executable, "probe/coverage.py"], capture_output=True, text=True)
if want.returncode:
    print("FAILED: probe/coverage.py: %s" % want.stderr.strip().splitlines()[-1:])
    raise SystemExit(1)
page = io.open("METHOD.md", encoding="utf-8").read()
got = re.search(r"<!-- coverage:.*?<!-- /coverage -->", page, re.S)
if not got:
    print("FAILED: METHOD.md no longer carries the coverage block probe/coverage.py writes")
    raise SystemExit(1)
if got.group(0).strip() != want.stdout.strip():
    print("FAILED: METHOD.md's coverage block differs from probe/coverage.py output")
    raise SystemExit(1)
print("ok      METHOD.md's coverage block is what probe/coverage.py counts from the plans")
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
differed = json.load(io.open("differed.json", encoding="utf-8"))
refused = json.load(io.open("refused.json", encoding="utf-8"))

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

# The page exposes the triage beside a cell. Check the denormalized cell-shaped payload against the
# reason/participant record, so a report cannot silently move to another implementation or case.
tracked, links = 0, set()
for label, col, _ in COLUMNS:
    c = drawn["participants"].index(label)
    for r, case in enumerate(drawn["cases"]):
        rule = drawn["answers"][r][c][1]
        want = (differed["rules"].get(rule, {}).get("triage", {}).get(col)
                or refused["rules"].get(rule, {}).get("triage", {}).get(col))
        got = drawn["tracking"][r][c]
        if got != want:
            print("FAILED: %s/%s: page tracking is %r, triage records say %r"
                  % (col, case, got, want))
            bad = 1
        if got:
            tracked += 1
            links.update(got.get("at", []))
if tracked:
    print("ok      page carries triage for %d cells, linking %d unique issues or PRs"
          % (tracked, len(links)))
else:
    print("FAILED: page carries no cell tracking")
    bad = 1
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
echo "### the relation table on the page carries the verdicts the columns hold"
# The page draws its own table from its own JSON, and nobody rereads that JSON. A cell drawn from a
# stale model would keep index.html byte-identical to the generator and agree with every number
# beside it, so the data is compared with probe/relations/check_column.py, which is where a verdict
# comes from.
python3 - <<'RELPAGE' || FAILED=1
import io, json, re, sys
sys.path.insert(0, "probe/relations")
import check_column as cc

page = io.open("docs/index.html", encoding="utf-8").read()
found = re.search(r'<script type="application/json" id="relations-data">(.*?)</script>', page, re.S)
if not found:
    print("FAILED: docs/index.html carries no data for the relation table")
    raise SystemExit(1)
drawn = json.loads(found.group(1))

bad = 0
for label, name in (("substrait-java", "JAVA"), ("substrait-go", "GO"), ("DuckDB", "DUCKDB")):
    model = cc.score("results/relations/%s.txt" % name)
    if label not in drawn["cells"]:
        print("FAILED: the page draws no column for %s" % label)
        bad = 1
        continue
    off = {c: (drawn["cells"][label].get(c), s) for c, s in model["state"].items()
           if drawn["cells"][label].get(c) != s}
    if off:
        case_id, (page_state, real) = sorted(off.items())[0]
        print("FAILED: the page has %s/%s as %s, the column makes it %s (%d cells differ)"
              % (label, case_id, page_state, real, len(off)))
        bad = 1
    answers = {c: t for c, (_, t) in model["answers"].items()}
    if drawn["answers"][label] != answers:
        print("FAILED: the page's answers for %s are not the ones in its column" % label)
        bad = 1
if not bad:
    print("ok      %d cells and their answers, the same on the page as in the columns"
          % sum(len(v) for v in drawn["cells"].values()))
raise SystemExit(bad)
RELPAGE

echo
echo "### the relation corpus picture is what its generator draws"
# Two checks, and the second is the one that matters. The first says the committed SVGs are the
# generator's output; that alone would stay true if the drawing loop skipped a state, since the
# files would match a generator that skips it too. So the shapes are also counted by their fill and
# compared with the verdicts probe/relations/check_column.py forms - one more of each than the grid
# holds, because the legend draws one swatch per state.
for want in svg-light:docs/relations.svg svg-dark:docs/relations-dark.svg; do
  python3 probe/relations/picture.py "${want%%:*}" 2>/dev/null | diff -q - "${want#*:}" >/dev/null \
    && ok "${want#*:} is what probe/relations/picture.py draws from the saved columns" \
    || fail "${want#*:} differs from probe/relations/picture.py output"
done
python3 - <<'RELSVG' || FAILED=1
import collections, io, re, sys
sys.path.insert(0, "probe/relations")
sys.path.insert(0, "probe")
import check_column as cc
import heatmap as base
import picture

model = picture.build()
cells = collections.Counter(s for states in model["cells"].values() for s in states.values())
bad = 0
for theme, path in (("light", "docs/relations.svg"), ("dark", "docs/relations-dark.svg")):
    t = base.THEMES[theme]
    svg = io.open(path, encoding="utf-8").read()
    hatched = svg.count('fill="url(#hatch)"')
    drawn = {
        cc.SCHEMA_ONLY: hatched,
        cc.DIFFERED: svg.count('fill="%s"' % t["divergence"]),
        cc.OBSERVED: svg.count('fill="url(#dots)"'),
        cc.UNSUPPORTED: len(re.findall(r'fill="none" stroke="%s" stroke-width="0.8"' % t["rule"], svg)),
        # A hatched cell is drawn as a filled box and a hatch over it, so the match colour counts
        # both states; the plain matches are what is left after the hatched ones are taken out.
        cc.MATCHED: svg.count('fill="%s"' % t["match"]) - hatched,
    }
    off = {cc.STATE_NAME[s]: (n, cells[s] + 1) for s, n in drawn.items() if n != cells[s] + 1}
    if off:
        print("FAILED: %s draws %s where the columns say %s"
              % (path, {k: v[0] for k, v in off.items()}, {k: v[1] for k, v in off.items()}))
        bad = 1
    else:
        print("ok      %-24s %d shapes, one per cell and one per legend swatch"
              % (path, sum(drawn.values())))
raise SystemExit(bad)
RELSVG

echo
echo "### every differing relation cell has a reason, and the reason still describes it"
python3 probe/relations/check_differed.py || FAILED=1

echo
echo "### the relations columns agree with the corpus they were taken on"
# The bundles under tests/relations are protobuf and this check needs python3 and nothing else, so
# the tie runs through results/relations/expected.json: probe/relations/check_column.py hashes every
# committed bundle against the extract before it scores anything. An edited case, a case the extract
# does not name and a column with a hole all fail here rather than in a number nobody recomputes.
if [ -d results/relations ]; then
  cols=$(find results/relations -name '*.txt' | sort)
  if [ -z "$cols" ]; then
    fail "results/relations holds an expectation extract and no column: nothing measures the corpus"
  else
    for col in $cols; do
      if out=$(python3 probe/relations/check_column.py "$col" 2>&1); then
        ok "$(echo "$out" | sed -n '2p' | sed 's/^  //') - $(basename "$col" .txt)"
      else
        fail "$col: $(echo "$out" | head -3 | tr '\n' ' ')"
      fi
    done
  fi
fi

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
# Six places name that list: the case labels in replay_column.sh, the two usage lines beside them,
# the matrix of each workflow, and the loop in drift.yml that collects what the matrix left behind.
# The relation corpus has five of its own: the case labels in its replay.sh, the usage line of its
# setup.sh, a matrix in each workflow, and its own loop in drift.yml. Adding a participant to
# the script and not to a workflow leaves a column nobody retakes while the pages say otherwise, and
# adding it to one workflow and not the other leaves it checked against the pin but never against a
# release. Neither is visible in a diff.
#
# There are two measurements and therefore two matrices, so each is attributed to the job it belongs
# to rather than taken as the first one in the file. Read by position instead, adding the relations
# job above the other made its three participants look like the nine, and moving it lower would have
# silenced that without checking anything.
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
def jobs(path):
    """Every job in a workflow, with the matrix it fans out over and the scripts it runs.

    Attributed by what the job invokes rather than by what it is called: there are two measurements
    and two matrices now, and reading the first `column:` in the file made the relations job's three
    participants look like the nine. Job names differ between the workflows anyway - `column` here,
    `drift` there - so the name was never the thing to key on.
    """
    text = io.open(path, encoding="utf-8").read()
    found, job = {}, None
    for line in text.splitlines():
        m = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
        if m:
            job = m.group(1)
            found[job] = {"matrix": None, "runs": set(), "run_line": {}, "needs": set(),
                          "artifact": None, "artifact_path": None, "text": ""}
        if job is None:
            continue
        found[job]["text"] += line + "\n"
        m = re.match(r"^\s*column:\s*\[([^\]]*)\]", line)
        if m:
            found[job]["matrix"] = {n.strip() for n in m.group(1).split(",") if n.strip()}
        m = re.match(r"^    needs:\s*\[?([^\]]*)\]?\s*$", line)
        if m:
            found[job]["needs"] = {n.strip() for n in m.group(1).split(",") if n.strip()}
        m = re.match(r"^\s+name:\s*(\S+)\$\{\{ matrix\.column \}\}\s*$", line)
        if m:
            found[job]["artifact"] = m.group(1)
        m = re.match(r"^\s+path:\s*(\S+?)/?\s*$", line)
        if m and found[job]["artifact"] is not None:
            found[job]["artifact_path"] = m.group(1)
        for script in ("probe/relations/replay.sh", "probe/replay_column.sh"):
            if script in line:
                found[job]["runs"].add(script)
                found[job]["run_line"][script] = line
                break
    return found

# The relation corpus is measured by its own script over its own participants, and each workflow
# needs a job for it as it does for the other: selfcheck.yml holds a column to its pin, drift.yml to
# today's release, and a script missing from one of them is a question nobody asks of its columns.
relations = io.open("probe/relations/replay.sh", encoding="utf-8").read()
relations_cases = set(re.findall(r"^\s*([A-Z]+)\)\s+runner=", relations, re.M))
if not relations_cases:
    print("FAILED: no participants found in probe/relations/replay.sh")
    raise SystemExit(1)
WANTED = {"probe/replay_column.sh": cases, "probe/relations/replay.sh": relations_cases}
usage = re.search(r"probe/relations/setup\.sh \[([A-Z|]+)\]",
                  io.open("probe/relations/setup.sh", encoding="utf-8").read())
sources["probe/relations/setup.sh usage line"] = (
    set(usage.group(1).split("|")) if usage else set(), "probe/relations/replay.sh")

bad = 0
workflow = {}
for wf, asks in (("selfcheck", "against the pin"), ("drift", "against today's release")):
    path = ".github/workflows/%s.yml" % wf
    workflow[wf] = jobs(path)
    seen = set()
    for name, job in sorted(workflow[wf].items()):
        for script in job["runs"]:
            seen.add(script)
            if job["matrix"] is None:
                print("FAILED: %s job %s runs %s over no matrix" % (path, name, script))
                raise SystemExit(1)
            sources["%s job %s" % (path, name)] = (job["matrix"], script)
            # Which question a job asks is one variable on its run line. Without it a drift job
            # holds its columns to their pins, finds nothing to record, and stays green.
            latest = "LATEST=1" in job["run_line"][script]
            if latest != (wf == "drift"):
                print("FAILED: %s job %s runs %s %s LATEST=1, so it retakes its columns %s"
                      % (path, name, script, "with" if latest else "without",
                         "against today's release" if latest else "against the pin"))
                bad = 1
    for script in sorted(set(WANTED) - seen):
        print("FAILED: no job in %s runs %s, so its columns are never retaken %s"
              % (path, script, asks))
        raise SystemExit(1)

# The job that writes results/DRIFT.txt collects the blocks by participant, one loop per corpus, and
# a participant the matrix retakes and the loop does not name has its moves thrown away unread. So
# are those of a job the collector does not wait for, and of one whose artifact it looks for under
# another name or whose run keeps its blocks somewhere the artifact does not take.
record = io.open(".github/workflows/drift.yml", encoding="utf-8").read()
loops = re.findall(r'for c in ([A-Z ]+); do\n\s*f="runs/(drift-(?:relations-)?)\$c/', record)
collector = [n for n, j in workflow["drift"].items() if "runs/drift-" in j["text"]]
if len(collector) != 1:
    print("FAILED: .github/workflows/drift.yml has %d jobs collecting drift blocks, not one"
          % len(collector))
    raise SystemExit(1)
collector = workflow["drift"][collector[0]]
for corpus, script in (("drift-", "probe/replay_column.sh"),
                       ("drift-relations-", "probe/relations/replay.sh")):
    named = [set(names.split()) for names, which in loops if which == corpus]
    if len(named) != 1:
        print("FAILED: .github/workflows/drift.yml has %d loops collecting the blocks %s leaves,"
              " not one" % (len(named), script))
        raise SystemExit(1)
    sources[".github/workflows/drift.yml record loop over runs/%s*" % corpus] = (named[0], script)
    for name, job in sorted(workflow["drift"].items()):
        if script not in job["runs"]:
            continue
        if name not in collector["needs"]:
            print("FAILED: the job that writes results/DRIFT.txt does not wait for drift job %s,"
                  " so it can finish before that job's blocks exist" % name)
            bad = 1
        if job["artifact"] != corpus:
            print("FAILED: drift job %s uploads its artifact as %s<NAME>, and the record loop reads"
                  " %s<NAME>" % (name, job["artifact"], corpus))
            bad = 1
        out = re.search(r"\bOUT=(\S+)", job["run_line"][script])
        if not out or out.group(1).rstrip("/") != job["artifact_path"]:
            print("FAILED: drift job %s keeps its run in %s and uploads %s"
                  % (name, out.group(1) if out else "nothing", job["artifact_path"]))
            bad = 1

for name, got in sorted(sources.items()):
    if isinstance(got, tuple):
        matrix, script = got
        if matrix != WANTED[script]:
            print("FAILED: %s names %s; %s accepts %s"
                  % (name, ", ".join(sorted(matrix)) or "nobody", script,
                     ", ".join(sorted(WANTED[script]))))
            bad = 1
    elif got != cases:
        print("FAILED: %s names %s; the script accepts %s"
              % (name, ", ".join(sorted(got)) or "nobody", ", ".join(sorted(cases))))
        bad = 1
if not bad:
    print("ok      %d participants in probe/replay_column.sh, its usage and both workflows: %s"
          % (len(cases), ", ".join(sorted(cases))))
    print("ok      %d in probe/relations/replay.sh, its setup's usage line and both workflows: %s"
          % (len(relations_cases), ", ".join(sorted(relations_cases))))
raise SystemExit(bad)
MATRIXPY

echo
echo "### the drift log says what it claims to say"
# results/DRIFT.txt is the one file in this repository a workflow writes rather than a person, and
# it is written a week at a time by a job nobody watches. What can be checked is its shape: that
# every block names a day, one of the participants a replay accepts and the revision it was built
# from; that the days do not run backwards; and that each block carries the two lines that let a
# reader tell a moved answer from a changed corpus. A malformed block would otherwise sit there
# looking like a record.
python3 - <<'DRIFTPY' || FAILED=1
import io, re, sys

LOG = "results/DRIFT.txt"
script = io.open("probe/replay_column.sh", encoding="utf-8").read()
plain = set(re.findall(r"^\s*([A-Z]+)\)\s+SETUP_KEY=", script, re.M))
# Both corpora write into this one log. A relation column is named by its path under results/, so a
# move in the DuckDB of one corpus is never read as a move in the DuckDB of the other.
relations = io.open("probe/relations/replay.sh", encoding="utf-8").read()
relation = {"relations/" + n for n in re.findall(r"^\s*([A-Z]+)\)\s+runner=", relations, re.M)}
known = plain | relation
HEAD = re.compile(r"^##### (\d{4}-\d{2}-\d{2})  ((?:relations/)?[A-Z]+)  (\S.*)$")


def problems(lines, where):
    found, blocks, previous = [], 0, ""
    for i, line in enumerate(lines):
        if not line.startswith("#####"):
            continue
        m = HEAD.match(line)
        if not m:
            found.append("%s:%d is not a block header: %r" % (where, i + 1, line)); continue
        day, who, revision = m.groups()
        blocks += 1
        if who not in known:
            found.append("%s:%d names %s, which the replay does not accept" % (where, i + 1, who))
        if day < previous:
            found.append("%s:%d is dated %s, after a block dated %s" % (where, i + 1, day, previous))
        previous = max(previous, day)
        # The line under the header tells a participant that moved from a corpus that changed.
        if i + 1 >= len(lines) or not re.match(r"^corpus \S+, inputs [0-9a-f]+$", lines[i + 1]):
            found.append("%s:%d has no corpus and fingerprint line under it" % (where, i + 1))
        # And the block has to end in the summary the comparison prints, or it records no count at
        # all. The next header is found by position. Looked up by its text, the next header after
        # two blocks under one header - a second run on the same day that finds the same move - is
        # the first block's own, and a whole block reads as empty.
        stop = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("#####")), len(lines))
        if not any(re.match(r"^%s: \d+ of \d+ answers moved" % re.escape(who), l)
                   for l in lines[i + 2:stop]):
            found.append("the block at %s:%d never says how many answers moved" % (where, i + 1))
    return found, blocks


# The log in the repository holds no block yet, so the check is also given one that holds each kind
# a run can write - a column of each corpus, and a second block under a header already used - and
# required to accept it. A check that only ever refuses would pass here and reject the first real
# relation block the workflow commits.
def block(day, who, corpus):
    return ["##### %s  %s  a revision" % (day, who), "corpus %s, inputs 0123456789abcdef" % corpus,
            "  some/case/id                                  answer",
            "%s: 1 of 71 answers moved (1 answer), 0 gone, 0 new" % who, ""]
one, other = sorted(plain)[0], sorted(relation)[0]
sample = (["What moved, and when.", ""] + block("2026-01-05", one, "aaaaaaa")
          + block("2026-01-05", other, "aaaaaaa") + block("2026-01-05", other, "bbbbbbb"))
refused, _ = problems(sample, "a well-formed log")
bad = 0
if refused:
    print("FAILED: the drift log check refuses a well-formed log: %s" % refused[0]); bad = 1

found, blocks = problems(io.open(LOG, encoding="utf-8").read().split("\n"), LOG)
for problem in found:
    print("FAILED: %s" % problem); bad = 1
if not bad:
    print("ok      %d recorded move(s), each dated, attributed and counted; a well-formed log of"
          " both corpora accepted" % blocks)
raise SystemExit(bad)
DRIFTPY

echo
echo "### the comparison a replayed column is judged by can tell a difference"
# probe/replay_column.sh and probe/relations/replay.sh rebuild a participant's environment and
# require the answers to be identical to the saved column. Everything about that run - the pinned
# version, the fresh venv, the workflow - is worth nothing if the comparison at the end cannot report
# a difference, and a comparison that always agrees looks exactly like a column that always
# reproduces. So it is given columns that differ in each of the ways a column can differ, and
# required to say so - a column of each corpus, since a relation line carries a mark before the case
# and a relation column writes a dead process as CRASH rather than ERROR.
python3 - <<'DIFFPY' || FAILED=1
import io, os, re, subprocess, sys, tempfile

COLUMNS = (("results/GO.txt", "ERROR:"), ("results/relations/DUCKDB.txt", "CRASH:"))
LINE = re.compile(r"^((?:score|observe)\s+)?(\S+)\s+(.*)$")


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


bad = 0
for column, refused in COLUMNS:
    head, body = rows(io.open(column, encoding="utf-8").read())
    parsed = [LINE.match(l).groups() for l in body]
    schema = next(i for i, (_, _, a) in enumerate(parsed) if a.startswith("["))
    # The refusal is written in rather than looked for. A column with none left to offer - DuckDB's,
    # the day its set operations stop crashing - would otherwise end this check in a traceback.
    refusal = next(i for i in range(len(body)) if i != schema)
    mark, name, _ = parsed[refusal]
    body[refusal] = "%s%-46s %s" % (mark or "", name, refused + " a refusal written in")
    parsed[refusal] = (mark, name, refused + " a refusal written in")

    with tempfile.TemporaryDirectory() as tmp:
        base = written(tmp, "base.txt", body, head)
        same = written(tmp, "same.txt", body, "T: a second take")
        rc, out = diff(base, same)
        if rc != 0 or "0 of %d answers moved" % len(body) not in out:
            print("FAILED: two takes of %s were not called identical: %s" % (column, out.strip()))
            bad = 1

        # The three ways an answer can move. They are not one case: a schema that became a refusal
        # and a refusal that became a schema are opposite findings, and the second is what an
        # upstream fix looks like from here.
        for label, index, value, kind in (
            ("a changed schema", schema, "[made:up]", "answer"),
            ("an answer that became a refusal", schema, refused + " made up", "lost"),
            ("a refusal that became an answer", refusal, "[made:up]", "gained"),
        ):
            lines = list(body)
            mark, name, _ = parsed[index]
            lines[index] = "%s%-46s %s" % (mark or "", name, value)
            rc, out = diff(base, written(tmp, "moved.txt", lines, "T: a second take"))
            if rc == 0:
                print("FAILED: in %s, %s was not reported as a difference" % (column, label)); bad = 1
            elif name not in out or "1 %s" % kind not in out:
                print("FAILED: in %s, %s was reported, but not as '%s' against %s: %s"
                      % (column, label, kind, name, out.strip().splitlines()[-1])); bad = 1

        # A case that stopped being answered at all. The count guard in replay_column.sh catches a
        # short column first, but the comparison must not call a missing case an agreement either.
        lines = [l for i, l in enumerate(body) if i != schema]
        rc, out = diff(base, written(tmp, "short.txt", lines, "T: a second take"))
        if rc == 0 or "1 gone" not in out:
            print("FAILED: a case dropped from %s was not reported: %s" % (column, out.strip()))
            bad = 1

if not bad:
    print("ok      identical columns agree; a changed, lost, gained or dropped answer is reported,"
          " in a column of each corpus")
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
