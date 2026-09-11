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
# The tracked repository is about 3 MB. The probe environment beside it is several gigabytes of
# virtualenvs, engine checkouts and jars, and `cp -a` knows nothing about .gitignore, so copying
# $ROOT wholesale carried all of it into every one of the seventy mutations - which is how a gate
# AGENTS.md lists as fast came to take the better part of an hour on a working checkout. Nothing in
# the copy ever reads it: .git is removed right after, so probe/selfcheck.sh takes its non-git
# branch, whose file list excludes .probe-env in the first place.
copy_repo() {  # <destination>
  rm -rf "$1"; mkdir -p "$1"
  for entry in "$ROOT"/* "$ROOT"/.[!.]*; do
    [ -e "$entry" ] || continue
    case "${entry##*/}" in .git|.probe-env) continue ;; esac
    cp -a "$entry" "$1/"
  done
}

copy_repo "$WORK"
cd "$WORK"

PASS=0 MISS=0

# Every result below is read as "the check noticed this mutation". That reading needs the copy to
# have been clean to begin with: a tree already failing with the substring a mutation expects lets
# that mutation pass for the wrong reason. The tree is also live - the author may be editing it
# while this runs - so the baseline is checked here rather than assumed.
if ! bash probe/selfcheck.sh >/dev/null 2>&1; then
  echo "FAILED: the copied tree does not pass probe/selfcheck.sh before anything is broken;" >&2
  echo "        no result below would mean what it says." >&2
  bash probe/selfcheck.sh 2>&1 | grep -m3 FAILED | sed 's/^/          /' >&2
  exit 1
fi
echo "ok      the copied tree passes before anything is broken"

mutate() { # <name> <expected fragment of the failure> <command that breaks one invariant>
  local name="$1" want="$2"; shift 2
  copy_repo "$WORK.tmp"
  rm -rf "$WORK"; mv "$WORK.tmp" "$WORK"; cd "$WORK"
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
m = re.search(r'taken (\\d{4})-(\\d{2})-(\\d{2})', s)
if not m: raise SystemExit(1)
day = '01' if m.group(3) != '01' else '02'
io.open('README.md', 'w', encoding='utf-8').write(
    s[:m.start()] + 'taken %s-%s-%s' % (m.group(1), m.group(2), day) + s[m.end():])"

mutate "an Acero parameterized type normalized to a plain type" "Acero parameterized-type parser" \
  replace probe/check_expected.py '{"varchar": "vchar", "fixed_char": "fchar"}' '{"varchar": "str", "fixed_char": "str"}'

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

# The two ways a sentence stops telling the truth: the number in it goes stale, and the sentence is
# reworded so that nothing is looking at it any more. The second is the one that hides.
# These four mutate whatever number is there rather than a number written down here: a mutation
# that names today's count stops applying the day the corpus grows, and a mutation that cannot
# apply is reported as MISSED but reads, in a green CI log, like one more guard that works.
bump() { # <file> <regex with one \d+ group> - change that number to something else
  python3 - "$1" "$2" <<'PY'
import io, re, sys
path, pattern = sys.argv[1:3]
s = io.open(path, encoding="utf-8").read()
m = re.search(pattern, s)
if not m:
    raise SystemExit(1)
io.open(path, "w", encoding="utf-8").write(
    s[:m.start(1)] + str(int(m.group(1)) + 7) + s[m.end(1):])
PY
}

mutate "a report named in a note without its repository" "names a report as" \
  python3 -c "
import io, json, re
d = json.load(io.open('differed.json', encoding='utf-8'))
raw = io.open('differed.json', encoding='utf-8').read()
for rid, rule in d['rules'].items():
    for col, entry in (rule.get('triage') or {}).items():
        note = entry.get('note', '')
        m = re.search(r'[\\w.-]+/[\\w.-]+(#\\d+)', note)
        if m:
            io.open('differed.json', 'w', encoding='utf-8').write(
                raw.replace(m.group(0), m.group(1), 1))
            raise SystemExit(0)
raise SystemExit(1)"

mutate "the per-participant page against its generator" "DIFFS.md differs" \
  bump results/DIFFS.md '## DuckDB — (\d+) cases'

mutate "a hand-improved coverage block" "coverage block differs" \
  bump METHOD.md '\| `join` \| (\d+) \|'

mutate "a number in the prose gone stale" "where the files say" \
  bump README.md 'They answer the (\d+) cases'

mutate "a guarded sentence reworded past its pattern" "was reworded" \
  python3 -c "
import io, re
s = io.open('README.md', encoding='utf-8').read()
new = re.sub(r'\| (\d+) generated plans, where the type', r'| \\1 generated plans in which the type', s)
if new == s: raise SystemExit(1)
io.open('README.md', 'w', encoding='utf-8').write(new)"

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
  replace probe/expected.py '"a nullable literal in a column the schema declares required: nullability is part of a type, "
        "so the cast rule would forbid it, yet nullability is also stripped before binding under "
        "MIRROR and DECLARED_OUTPUT - the spec is in tension with itself and settles nothing here"' '"same"' &&
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
d['rules']['decimal-own-derivation']['check'] = {'nullable_only': True}
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

# The triage beside each divergence: what came of it, per participant. An entry may say 'open',
# and that is allowed on purpose - so what is left to check is that the record
# is complete, that it means one thing, and that its links go somewhere a reader is sent.
# results/DRIFT.txt is empty in the repository, so each of these appends a block that is right
# except for the one thing it breaks: a check with nothing to read passes without reading.
#
# Written with python3 and not printf, for the reason recorded further down this file: printf %s
# does not interpret \n, so the first version of these appended one long line with backslashes in
# it. Two of the five then fired on a neighbouring invariant and looked like they worked.
mutate "a drift block with no day" "is not a block header" \
  python3 -c "
import io
io.open('results/DRIFT.txt', 'a', encoding='utf-8').write('''##### DUCKDB  duckdb 1.6.0
corpus 5f9d391, inputs 4d7bb168ef648649
DUCKDB: 1 of 78 answers moved (1 answer), 0 gone, 0 new
''')"

mutate "a drift block naming nobody the replay retakes" "the replay does not accept" \
  python3 -c "
import io
io.open('results/DRIFT.txt', 'a', encoding='utf-8').write('''##### 2026-09-14  GLUTEN  velox f7f5f04
corpus 5f9d391, inputs 4d7bb168ef648649
GLUTEN: 1 of 78 answers moved (1 answer), 0 gone, 0 new
''')"

mutate "drift blocks running backwards in time" "after a block dated" \
  python3 -c "
import io
io.open('results/DRIFT.txt', 'a', encoding='utf-8').write('''##### 2026-09-14  DUCKDB  duckdb 1.6.0
corpus 5f9d391, inputs 4d7bb168ef648649
DUCKDB: 1 of 78 answers moved (1 answer), 0 gone, 0 new

##### 2026-01-01  GO  substrait-go/v9 v9.0.1
corpus 5f9d391, inputs 4d7bb168ef648649
GO: 1 of 78 answers moved (1 answer), 0 gone, 0 new
''')"

mutate "a drift block that does not say what it was measured against" "no corpus and fingerprint line" \
  python3 -c "
import io
io.open('results/DRIFT.txt', 'a', encoding='utf-8').write('''##### 2026-09-14  DUCKDB  duckdb 1.6.0
DUCKDB: 1 of 78 answers moved (1 answer), 0 gone, 0 new
''')"

mutate "a drift block with no count in it" "never says how many answers moved" \
  python3 -c "
import io
io.open('results/DRIFT.txt', 'a', encoding='utf-8').write('''##### 2026-09-14  DUCKDB  duckdb 1.6.0
corpus 5f9d391, inputs 4d7bb168ef648649
  emit_read                                      answer
''')"

# The list of participants CI retakes, which lives in five places and drifts silently.
mutate "a participant the drift workflow does not retake" "the script accepts" \
  python3 -c "
import io, re
p = '.github/workflows/drift.yml'
s = io.open(p, encoding='utf-8').read()
m = re.search(r'^(\s*column: \[)([^\]]*)(\])', s, re.M)
names = [n.strip() for n in m.group(2).split(',')]
io.open(p, 'w', encoding='utf-8').write(
    s[:m.start()] + m.group(1) + ', '.join(names[:-1]) + m.group(3) + s[m.end():])"

mutate "a participant missing from the usage line" "the script accepts" \
  python3 -c "
import io, re
p = 'probe/replay_column.sh'
s = io.open(p, encoding='utf-8').read()
m = re.search(r'replay_column\.sh ([A-Z|]+)', s)
names = m.group(1).split('|')
io.open(p, 'w', encoding='utf-8').write(
    s[:m.start(1)] + '|'.join(names[:-1]) + s[m.end(1):])"

# refused.json: the eleven cells where a participant died rather than refusing. The file and the
# columns have to name the same cells in both directions, or a crash quietly becomes an absence.
mutate "a crash the record does not mention" "refused.json does not say so" \
  python3 -c "
import io, json
d = json.load(open('refused.json', encoding='utf-8'))
del d['cells']['ACERO']['emit_aggregate']
io.open('refused.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a crash recorded where the column has none" "the column says otherwise" \
  python3 -c "
import io, json
d = json.load(open('refused.json', encoding='utf-8'))
d['cells']['ACERO']['emit_read'] = 'acero-dies-on-an-aggregate-emit'
io.open('refused.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a crash reason with nothing to test it" "carries no got_matches" \
  python3 -c "
import io, json
d = json.load(open('refused.json', encoding='utf-8'))
d['rules']['acero-dies-on-an-aggregate-emit']['check'] = {}
io.open('refused.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a crash reason whose predicate does not hold" "does not match" \
  python3 -c "
import io, json
d = json.load(open('refused.json', encoding='utf-8'))
d['rules']['acero-dies-on-an-aggregate-emit']['check']['got_matches']['ACERO'] = '^ERROR: nothing$'
io.open('refused.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a report named in a reason's prose instead of its record" "in its prose" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['grouping-key-nullability']['what'] += ' Filed as apache/datafusion#24968.'
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a divergence with nothing said about what came of it" "with no triage" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
del d['rules']['grouping-key-nullability']['triage']
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a triage missing one of the participants it covers" "its cells belong to" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
del d['rules']['decimal-own-derivation']['triage']['ACERO']
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "an outcome that is not one of the four" "is not one of" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['grouping-key-nullability']['triage']['DATAFUSION']['outcome'] = 'filed'
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a report named with nothing to follow" "names nothing to follow" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['grouping-key-nullability']['triage']['DATAFUSION']['at'] = []
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "an untriaged cell carrying a link anyway" "which names no report" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['acero-required-kept-only-on-a-bare-read']['triage']['ACERO']['at'] = ['https://github.com/apache/datafusion/issues/24968']
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a link the report map does not carry" "which FINDINGS.md does not" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['grouping-key-nullability']['triage']['DATAFUSION']['at'] = ['https://github.com/apache/datafusion/issues/24969']
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

mutate "a type-system boundary triaged as if it were a defect" "only a divergence carries a triage" \
  python3 -c "
import io, json
d = json.load(open('differed.json', encoding='utf-8'))
d['rules']['no-string-with-length']['triage'] = {'DUCKDB': {'outcome': 'open', 'note': 'x'}}
io.open('differed.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1))"

# The row half of the corpus can only carry one column of integers, because that is all the three
# executing probes print. A row expectation of another shape has no path through them, and the
# failure it produces is a divergence recorded against a participant. So the shape is asserted, and
# the assertion has to be able to fail.
mutate "a row expectation the probes cannot produce" "not a list of integers" \
  python3 -c "
import io, json, subprocess, sys
# Through expected.py and then regenerated, so that the mutation trips the shape assertion alone
# rather than also the check that expected.json is what expected.py prints.
p = 'probe/expected.py'
s = io.open(p, encoding='utf-8').read()
old = 'rows[case] = {\"rows\": sorted(out),'
assert old in s, 'anchor moved'
io.open(p, 'w', encoding='utf-8').write(s.replace(old, 'rows[case] = {\"rows\": [chr(120)] + sorted(out),', 1))
io.open('expected.json', 'w', encoding='utf-8').write(
    subprocess.run([sys.executable, p], capture_output=True, text=True, check=True).stdout)"

mutate "the count of entries still needing investigation" "still needs investigation" \
  python3 -c "
import io, re
p = 'METHOD.md'
s = io.open(p, encoding='utf-8').read()
m = re.search(r'([\w-]+) (of those [\w-]+ still needs? investigation)', s)
wrong = 'nine' if m.group(1) != 'nine' else 'seven'
io.open(p, 'w', encoding='utf-8').write(s[:m.start()] + wrong + ' ' + m.group(2) + s[m.end():])"

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

mutate "a link to a section that was renamed" "no heading with that anchor" \
  python3 -c "
import io
s = io.open('METHOD.md', encoding='utf-8').read()
old = '## The two expand cases'
if old not in s: raise SystemExit(1)
io.open('METHOD.md', 'w', encoding='utf-8').write(s.replace(old, '## The expand cases', 1))"

mutate "a link to a page that is not there" "which does not exist" \
  python3 -c "
import io
s = io.open('README.md', encoding='utf-8').read()
old = '(METHOD.md)'
if old not in s: raise SystemExit(1)
io.open('README.md', 'w', encoding='utf-8').write(s.replace(old, '(METHODS.md)', 1))"

# The comparison probe/replay_column.sh judges a replayed column by. A comparison that agrees with
# everything is the shape of guard this file exists for: the workflow stays green, the artifacts look
# right, and the four columns CI retakes stop being checked at all.
mutate "a comparison that reports no difference" "was not reported as a difference" \
  replace probe/column_diff.py "sys.exit(1 if (moved or gone or added) else 0)" "sys.exit(0)"

# Reporting a difference is not enough: a run that turns answers into refusals is a different
# finding from one that changes a schema, and both are different from an upstream fix, which arrives
# as a refusal becoming an answer.
mutate "a difference reported under the wrong kind" "but not as" \
  replace probe/column_diff.py 'kind = ("refusal" if was and now else "lost" if now else "gained" if was else "answer")' 'kind = "answer"'

# The picture and the page are drawn from the same verdicts as the counts beside them. Breaking the
# drawing alone is what tells the two checks apart: one says the committed file is the generator's
# output, the other says the generator drew a shape per cell.
mutate "a relations picture that is not what its generator draws" "differs from probe/relations/picture.py" \
  python3 -c "
p = 'docs/relations.svg'
t = open(p, encoding='utf-8').read()
open(p, 'w', encoding='utf-8').write(t.replace('The relation corpus', 'The relation corpora', 1))"

mutate "a relations cell drawn as agreement where the column differs" "draws" \
  python3 -c "
import re
for p in ('docs/relations.svg', 'docs/relations-dark.svg'):
    t = open(p, encoding='utf-8').read()
    for old, new in (('#d03b3b', '#d6d6d1'), ('#e05a58', '#363a40')):
        t = t.replace(old, new)
    open(p, 'w', encoding='utf-8').write(t)"

# The replacement is asserted rather than attempted. str.replace on a missing substring succeeds
# and writes the file back unchanged, so when the sentence this aimed at was reworded the mutation
# went on "applying" and the check went on "passing" - a guard that had quietly stopped guarding,
# which is the thing this whole file exists to catch. Caught here, on its own suite.
mutate "a stale count of the relation cases" "relation cases" \
  python3 -c "
p = 'README.md'
t = open(p, encoding='utf-8').read()
old, new = '| 71 hand-written cases', '| 73 hand-written cases'
assert old in t, 'the sentence this mutation edits is gone; re-aim it'
open(p, 'w', encoding='utf-8').write(t.replace(old, new))"

# The page's own table is drawn from its own JSON, which nothing else reads. Breaking one cell in
# it leaves the file byte-identical to its generator, which is why the data is checked separately.
mutate "a relation cell the page draws as agreement" "the column makes it" \
  python3 -c "
import json, re
p = 'docs/index.html'
t = open(p, encoding='utf-8').read()
m = re.search(r'(<script type=\"application/json\" id=\"relations-data\">)(.*?)(</script>)', t, re.S)
d = json.loads(m.group(2))
d['cells']['DuckDB']['read/mask/narrows-a-struct-from-inside'] = 0
open(p, 'w', encoding='utf-8').write(
    t[:m.start(2)] + json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + t[m.end(2):])"

# The reasons behind the differing cells: a judgement is worth what its test is worth, so the test
# is what gets broken here - the cell that no longer has one, the reason that no longer describes
# the answer, and the reason left behind after the cell stopped differing.
mutate "a differing relation cell with no reason" "no reason says why" \
  python3 -c "
import json
p = 'results/relations/differed.json'
d = json.load(open(p))
del d['cells']['GO']['write/no_output/returns-nothing']
json.dump(d, open(p, 'w'), indent=2)"

mutate "a reason that no longer describes its cell" "no longer matches its reason" \
  python3 -c "
import json
p = 'results/relations/differed.json'
d = json.load(open(p))
d['rules']['go-hash-join-ignores-the-join-type']['check']['got_matches']['GO'] = '^this-answer-never-appears$'
json.dump(d, open(p, 'w'), indent=2)"

mutate "a reason kept after its cell stopped differing" "no longer differs" \
  python3 -c "
import json
p = 'results/relations/differed.json'
d = json.load(open(p))
d['cells']['GO']['join/inner/output-nullability'] = 'go-hash-join-ignores-the-join-type'
json.dump(d, open(p, 'w'), indent=2)"

mutate "a relation participant CI does not retake" "probe/relations/replay.sh accepts" \
  python3 -c "
p = '.github/workflows/selfcheck.yml'
t = open(p, encoding='utf-8').read()
open(p, 'w', encoding='utf-8').write(t.replace('column: [DUCKDB, GO, JAVA]', 'column: [DUCKDB, GO]'))"

# The relations corpus is measured against an extract of its own bundles, and the tie between the
# two is a hash rather than a rerun of the generator, because the generator needs protobuf and this
# gate needs python3. So the hash is the thing to break.
mutate "a bundle edited after the expectations were extracted" "has changed since the extract" \
  python3 -c "
p = 'tests/relations/bundles/join/left.pb'
data = open(p, 'rb').read()
open(p, 'wb').write(data + b'\\x00')"

mutate "a case the extract does not name" "the extract does not name" \
  python3 -c "
import shutil
shutil.copy('tests/relations/bundles/join/left.pb', 'tests/relations/bundles/join/left_copy.pb')"

mutate "a relations column with a case missing" "is not a whole column" \
  python3 -c "
p = 'results/relations/DUCKDB.txt'
lines = [l for l in open(p, encoding='utf-8') if 'join/left_mark' not in l]
open(p, 'w', encoding='utf-8').writelines(lines)"

mutate "a column taken against another state of the corpus" "another state of the corpus" \
  python3 -c "
import json, re
p = 'results/relations/DUCKDB.txt'
t = open(p, encoding='utf-8').read()
fp = json.load(open('results/relations/expected.json', encoding='utf-8'))['fingerprint']
open(p, 'w', encoding='utf-8').write(t.replace(fp, 'f' * len(fp), 1))"

mutate "a never-scored case marked as scored" "the corpus says observe" \
  python3 -c "
p = 'results/relations/DUCKDB.txt'
t = open(p, encoding='utf-8').read()
open(p, 'w', encoding='utf-8').write(t.replace('observe read/projection', 'score   read/projection'))"

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
