#!/bin/bash
# Checks that probe/selfcheck.sh can fail.
#
#   bash probe/selfcheck-negative.sh
#
# A check nobody checks is a comment the interpreter happens to run. Three guards in this repository
# were written, committed, looked right and could never fire - one compared refusals against the
# number of cases while the check counts only those with an expectation, one matched its own source,
# one read a version out of a file that had not been sourced yet. All three were found from outside:
# by a cold machine or by someone else reading. None was found here.
#
# So each invariant selfcheck.sh states is broken in turn, in a copy, and the check is required to
# fail AND to name that invariant - a mutation that trips some other check would otherwise pass for
# the wrong reason. Nothing here touches the working tree.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -a "$ROOT/." "$WORK/"
rm -rf "$WORK/.git"
cd "$WORK"

PASS=0 MISS=0

mutate() { # <name> <expected fragment of the failure> <command that breaks one invariant>
  local name="$1" want="$2"; shift 2
  cp -a "$ROOT/." "$WORK.tmp" 2>/dev/null || { mkdir -p "$WORK.tmp"; cp -a "$ROOT/." "$WORK.tmp"; }
  rm -rf "$WORK"; mv "$WORK.tmp" "$WORK"; rm -rf "$WORK/.git"; cd "$WORK"
  if ! "$@" >/dev/null 2>&1; then
    echo "MISSED  $name: the mutation itself did not apply"; MISS=$((MISS + 1)); return
  fi
  local out; out="$(bash probe/selfcheck.sh 2>&1)"; local rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "MISSED  $name: selfcheck still passed"; MISS=$((MISS + 1)); return
  fi
  if ! printf '%s' "$out" | grep -qi -- "$want"; then
    echo "MISSED  $name: it failed, but not on this invariant"
    printf '%s\n' "$out" | grep -m1 -i FAILED | sed 's/^/          /'
    MISS=$((MISS + 1)); return
  fi
  echo "ok      $name"; PASS=$((PASS + 1))
}

sub() { python3 - "$@"; }   # sub <file> <old> <new>
replace() {
  python3 - "$1" "$2" "$3" <<'PY'
import io, sys
p, old, new = sys.argv[1:4]
s = io.open(p, encoding="utf-8").read()
if old not in s:
    raise SystemExit(1)
io.open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
PY
}

echo "### each invariant broken in turn, in a copy"

mutate "expected.json against its generator" "expected.json" \
  replace probe/expected.py '"is_null returns a required boolean"' '"is_null returns something else"'

mutate "MATRIX.txt against its generator" "MATRIX.txt" \
  replace results/MATRIX.txt "Schema derivation matrix" "Schema derivation MATRIX"

mutate "the drawn matrix against its generator" "matrix.svg differs" \
  replace docs/matrix.svg "9 implementations" "8 implementations"

mutate "the page against its generator" "index.html differs" \
  python3 -c "
import io, re
s = io.open('docs/index.html', encoding='utf-8').read()
m = re.search(r'All (\\d+) cases', s)
if not m: raise SystemExit(1)
io.open('docs/index.html', 'w', encoding='utf-8').write(
    s[:m.start()] + 'All %d cases' % (int(m.group(1)) - 1) + s[m.end():])"

# The generator and the files it writes move together, the way a real edit would arrive: changing
# only the generator leaves docs/ stale and the byte comparison above fires instead, which says
# nothing about whether the cells themselves are checked.
drawn_cells() {
  replace probe/heatmap.py '"boundary": BOUNDARY' '"boundary": MATCH' &&
  python3 probe/heatmap.py svg-light > docs/matrix.svg &&
  python3 probe/heatmap.py svg-dark > docs/matrix-dark.svg &&
  python3 probe/heatmap.py page > docs/index.html
}
mutate "a drawn cell the check calls a difference" "the drawing" drawn_cells

# A state the drawing loop stops painting: the files stay byte-identical to the generator and the
# page keeps every verdict, so only the count of shapes in the SVG can notice.
unpainted_state() {
  replace probe/heatmap.py '    elif state == NOSPEC:
        box(x, y, w, h, fill="url(#dots)")' '    elif state == NOSPEC:
        pass' &&
  python3 probe/heatmap.py svg-light > docs/matrix.svg &&
  python3 probe/heatmap.py svg-dark > docs/matrix-dark.svg &&
  python3 probe/heatmap.py page > docs/index.html
}
mutate "a state the picture stops drawing" "where the page has" unpainted_state

# The mutations below derive what they change from the file rather than naming it. A literal here
# is a date, a tally or a case count that a rerun moves, and when it moves the replacement stops
# matching: the mutation then "does not apply" and the check it stands for goes untested. That is
# how this file failed CI the first time a column was retaken.
mutate "the date on the results table" "dates the table" \
  python3 -c "
import io, re
s = io.open('README.md', encoding='utf-8').read()
m = re.search(r'taken (\\d{4})-(\\d{2})-(\\d{2}) against', s)
if not m: raise SystemExit(1)
day = '01' if m.group(3) != '01' else '02'
io.open('README.md', 'w', encoding='utf-8').write(
    s[:m.start()] + 'taken %s-%s-%s against' % (m.group(1), m.group(2), day) + s[m.end():])"

mutate "a number in the results table" "README says" \
  python3 -c "
import io, re
s = io.open('README.md', encoding='utf-8').read()
m = re.search(r'^\\| substrait-validator \\| (\\d+) \\| (\\d+) \\| (\\d+) \\|$', s, re.M)
if not m: raise SystemExit(1)
io.open('README.md', 'w', encoding='utf-8').write(
    s[:m.start()] + '| substrait-validator | %s | %d | %s |'
    % (m.group(1), int(m.group(2)) + 1, m.group(3)) + s[m.end():])"

mutate "the swap table against LIE.txt" "LIE.txt gives" \
  python3 -c "
import io
s = io.open('results/LIE.txt', encoding='utf-8').read()
head = s.find(chr(10) + 'case ')   # the verdict table; 'follows' also appears in the legend above it
at = s.find('follows', head) if head > 0 else -1
if at < 0: raise SystemExit(1)
io.open('results/LIE.txt', 'w', encoding='utf-8').write(s[:at] + 'held   ' + s[at + len('follows'):])"

mutate "the virtual-table corpus against its generator" "generator produces" \
  replace derived-schema-virtual-tables/decimal_add.json '"precision": 11' '"precision": 12'

mutate "a case without its binary" "binary protobuf" \
  rm -f derived-schema/decimal_add.bin

mutate "a case missing from the manifest" "does not cover the corpus" \
  python3 -c "
import io, json
m = json.load(open('derived-schema/manifest.json', encoding='utf-8'))
io.open('derived-schema/manifest.json', 'w', encoding='utf-8').write(
    json.dumps([e for e in m if e['case'] != 'join_inner'], ensure_ascii=False, indent=1))"

# The generator and the file it writes are changed together, the way a real edit would arrive:
# changing only the generator leaves expected.json stale, the earlier check fires instead, and that
# says nothing about this one.
back_reference() {
  replace probe/expected.py '"a nullable literal in a column the schema declares required: the spec does not say which "
        "wins, the row or the schema"' '"same"' &&
  python3 probe/expected.py > expected.json
}
mutate "a reason that only points at its neighbour" "points at another entry" back_reference

mutate "a differing cell with no reason" "with no reason" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['cells']['GO'].pop('aggregate_grouping_sets_declared_order')
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason that names no rule" "which is not defined" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['cells']['GO']['aggregate_grouping_sets_declared_order'] = 'no-such-rule'
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming only nullability is lost" "the types differ too" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['acero-drops-a-fixed-size-binary']['check'] = {'nullable_only': True}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming the answer is one input" "which for these inputs means" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['isthmus-setop-nullable-if-any-input-is']['check'] = {'first_input': True}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason allowing a column the answer really appends" "which for these inputs means" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['python-join-concatenates-the-inputs']['check'] = {'inputs_concatenated': {}}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason with no test at all" "makes no claim a machine can test" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
del d['rules']['decimal-own-derivation']['check']
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a misspelled check that would never run" "has unknown checks" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['decimal-own-derivation']['check'] = {'all_decimall': True}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a disabled check counted as evidence" "nullable_only must be true" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['spark-decimal-result-nullable']['check'] = {'nullable_only': False}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a misspelled input-check option" "has unknown options" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['validator-join-concatenates-the-inputs']['check'] = {'inputs_concatenated': {'mark_sufix': True}}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "an input check hidden by another input check" "has multiple input checks" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['validator-join-concatenates-the-inputs']['check']['first_input'] = True
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "an empty pattern that checks no output" "must be a nonempty regular expression" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['duckdb-timestamp-is-microseconds']['check']['got_matches'] = ''
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming every column is required" "a field of the answer is nullable" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['grouping-key-nullability']['check'] = {'no_field_nullable': True}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming the answer is a decimal" "decimal field(s)" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['duckdb-decimal-divide-returns-double']['check'] = {'all_decimal': {}}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming a second difference the answer lacks" "differs in precision and scale alone" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['decimal-own-derivation']['check'] = {'all_decimal': {'nullable_in': ['SPARK']}}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming every field is one type" "so every field should be" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['validator-does-not-resolve']['check'] = {'all_fields_are': 'i64'}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason applied to a precision it does not cover" "which is only about precisions" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['duckdb-timestamp-is-microseconds']['check']['declared_precision_in'] = [0, 3, 9]
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "one participant's answer asserted of another" "whose answer should match" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
m = d['rules']['no-string-with-length']['check']['got_matches']
m['DATAFUSION'] = m['DUCKDB']
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason saying the answer stops short of an answer that does not" "should be shorter than the input" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['read-projection-ignored']['check'] = {'first_input': {'leading': True}}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a reason claiming what the answer looks like" "whose answer should match" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['duckdb-timestamp-is-microseconds']['check']['got_matches'] = '^.c:DATE.$'
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a count the README states about the reasons" "the README does not say" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['duckdb-timestamp-is-microseconds']['kind'] = 'divergence'
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "the count of cases naming a source" "name a source issue" \
  python3 -c "
import io, re
# The sentence lives on whichever page suits the reader and has already moved once, so it is found
# rather than named: the check reads both pages, and so does this.
for name in ('README.md', 'METHOD.md'):
    s = io.open(name, encoding='utf-8').read()
    m = re.search(r'(Five|Six|Seven|Eight|Nine|Ten|\\d+) cases have one so far', s)
    if not m: continue
    swap = 'Six' if m.group(1) != 'Six' else 'Seven'
    io.open(name, 'w', encoding='utf-8').write(
        s[:m.start()] + '%s cases have one so far' % swap + s[m.end():])
    raise SystemExit(0)
raise SystemExit(1)"

mutate "a link to a page that is not there" "which does not exist" \
  python3 -c "
import io
s = io.open('README.md', encoding='utf-8').read()
old = '(METHOD.md)'
if old not in s: raise SystemExit(1)
io.open('README.md', 'w', encoding='utf-8').write(s.replace(old, '(METHODS.md)', 1))"

mutate "broken python" "python syntax" \
  sh -c "printf 'def (\n' >> probe/matrix.py"

mutate "a missing focused JSON plan" "focused structural fixtures are incomplete" \
  rm probe/structural-cases/validator/one_column.json

mutate "a missing focused binary plan" "focused structural fixtures are incomplete" \
  rm probe/structural-cases/go/join_common_absent.bin

mutate "a focused group without controls" "focused structural fixtures are incomplete" \
  python3 -c "
import json
from pathlib import Path
p = Path('probe/structural-cases/expected.json')
d = json.loads(p.read_text())
for case in d['go'].values(): case['control'] = False
p.write_text(json.dumps(d))"

# Assembled rather than written out, for the same reason the patterns in selfcheck.sh are: a file
# carrying the literal would be flagged by the check it is testing.
mutate "an absolute path" "absolute path in" \
  sh -c 'printf "\n# see %s\n" "/$(printf Users)/someone/scratch" >> probe/setup.sh' 

# Written with python3, which this repository requires anyway, rather than with printf: dash's
# printf has no \xNN escape, so on Linux the bytes were never written, no untranslated text appeared,
# and the check correctly stayed silent - a mutation that could not mutate, found by running the
# suite somewhere other than where it was written.
mutate "untranslated text" "untranslated text in" \
  python3 -c "import io; f=io.open('probe/setup.sh','a',encoding='utf-8'); f.write(u'\n# \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430\n'); f.close()"

echo
echo "invariants that could be broken and were caught: $PASS"
[ "$MISS" -eq 0 ] || { echo "RESULT: $MISS check(s) did not fire on their own invariant"; exit 1; }
echo "RESULT: every invariant selfcheck.sh states can fail, and fails on itself"
