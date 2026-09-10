#!/bin/bash
# Retakes the relation measurement after the corpus has changed, in one command.
#
#     bash probe/relations/retake.sh [NAME...]        # default: every participant
#
# The corpus grows. When it does, every saved column is answering a set of cases that no longer
# exists, and `check_column.py` refuses to score it rather than comparing one set against another -
# which is the right refusal and leaves six steps to do by hand: regenerate the extract, run each
# runner, redraw two pictures, rebuild the page, and find the numbers the README states about all
# of it. Doing that by hand once was enough to learn that the order matters and that the last step
# is the one that gets forgotten.
#
# It writes only generated files: the extract, the columns, the two SVGs and the page. What it
# cannot write is the prose, so it ends by naming every sentence whose number has moved.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
PY="$SP/relvenv/bin/python"
ALL="DUCKDB GO JAVA"
WANT="${*:-$ALL}"
FAILED=0

say() { printf '== %s\n' "$*"; }
fail() { echo "FAILED: $*" >&2; FAILED=1; }

[ -x "$PY" ] || { echo "no relations probe environment; run probe/relations/setup.sh first" >&2; exit 1; }

# The extract first, and the columns after it. The other order writes columns whose head carries a
# fingerprint over the corpus the extract has not caught up with yet, and every one of them then
# fails its own check.
say "the expectations, from the bundles"
"$PY" "$ROOT/probe/relations/expected.py" --write || { fail "the extract"; exit 1; }

for name in $WANT; do
  case "$name" in
    DUCKDB) runner=duckdb_all.sh ;;
    GO)     runner=go_all.sh ;;
    JAVA)   runner=java_all.sh ;;
    *)      fail "unknown participant $name"; continue ;;
  esac
  say "$name"
  out="$ROOT/results/relations/$name.txt"
  before="$(mktemp)"; cp "$out" "$before" 2>/dev/null || : > "$before"
  if ! bash "$ROOT/probe/relations/$runner" > "$out.new"; then
    fail "$name did not produce a whole column; $out is untouched"
    rm -f "$out.new" "$before"
    continue
  fi
  mv "$out.new" "$out"
  # What moved, by answer rather than by count: a case swapped for another keeps every count.
  # shellcheck source=../columns.sh
  ( . "$ROOT/probe/columns.sh"
    diff <(column_body "$before") <(column_body "$out") | sed -n 's/^[<>] /   /p' | head -12 )
  rm -f "$before"
done

say "the picture and the page"
"$PY" "$ROOT/probe/relations/picture.py" svg-light > "$ROOT/docs/relations.svg" || fail "svg-light"
"$PY" "$ROOT/probe/relations/picture.py" svg-dark > "$ROOT/docs/relations-dark.svg" || fail "svg-dark"
python3 "$ROOT/probe/heatmap.py" page > "$ROOT/docs/index.html" || fail "the page"

say "what the columns now say"
for name in $WANT; do
  python3 "$ROOT/probe/relations/check_column.py" "$ROOT/results/relations/$name.txt" || FAILED=1
done

# The prose is the part no script can write, and the part that goes stale silently. check_pages.py
# holds every number the pages state about this corpus; a sentence it names here is a sentence to
# edit by hand before committing.
# A retake that moves a verdict must not leave a reason behind describing an answer that is gone.
# This is the check the whole script exists around: the columns can be regenerated in one command,
# and the judgements written against them cannot.
say "the reasons behind the differing cells"
python3 "$ROOT/probe/relations/check_differed.py" || fail "a reason no longer describes its cell"

say "the sentences that no longer match"
python3 "$ROOT/probe/check_pages.py" || fail "the pages state numbers the files no longer hold"

[ "$FAILED" -eq 0 ] || exit 1
echo
echo "retaken. Nothing above is committed; inspect the diff before you do."
