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

mutate "the date on the results table" "dates the table" \
  replace README.md "taken 2026-09-06 against" "taken 2026-09-05 against"

mutate "a number in the results table" "README says" \
  replace README.md "| substrait-validator | 45 | 28 | 0 |" "| substrait-validator | 45 | 27 | 0 |"

mutate "the swap table against LIE.txt" "LIE.txt gives" \
  replace results/LIE.txt "decimal_add                       follows" "decimal_add                       held   "

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

mutate "the count of cases naming a source" "name a source issue" \
  replace README.md "Five cases have one so far" "Six cases have one so far"

mutate "broken python" "python syntax" \
  sh -c "printf 'def (\n' >> probe/matrix.py"

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
