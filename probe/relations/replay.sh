#!/bin/bash
# Builds one participant from nothing, puts the relations corpus through it, and compares the
# answers with the saved column.
#
#     bash probe/relations/replay.sh DUCKDB
#     LATEST=1 OUT=<dir> bash probe/relations/replay.sh DUCKDB
#
# The head of a column names the day it was taken and the version it was taken against, so two runs
# never agree on it; only the answers are compared, by the same probe/column_diff.py the 98-case
# columns are replayed with. The two modes differ in what a difference means, as they do there.
#
#   pinned (default)  the versions in probe/versions.env. A difference is a failure: the
#                     participant moved, or this harness did, and the run names the cases.
#   LATEST=1          today's release, through probe/versions-latest.env and in an environment of
#                     its own. A difference is what the run went looking for; only a harness that
#                     will not build or comes back short fails. OUT=<dir> keeps the column and the
#                     report, and a run that found something leaves a block for results/DRIFT.txt.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="${1:-}"
SAVED="$ROOT/results/relations/$NAME.txt"
LATEST="${LATEST:-0}"

fail() { echo "FAILED: $*" >&2; exit 1; }
# shellcheck source=../columns.sh
. "$ROOT/probe/columns.sh"

if [ "$LATEST" = 1 ]; then
  export SUBSTRAIT_VERSIONS="$ROOT/probe/versions-latest.env"
  # An environment of its own. The pinned one on a workstation is .probe-env, and today's DuckDB
  # installed into it would leave every later pinned replay measuring a build nobody pinned. The
  # overrides go for the same reason: a SUBSTRAIT_JAVA_DIR left in the caller's shell would have
  # this run measure that checkout and report it as today's substrait-java.
  SP="$(mktemp -d)"
  export SUBSTRAIT_PROBE_ENV="$SP"
  unset SUBSTRAIT_JAVA_DIR RELATIONS_DUCKDB_PYTHON RELATIONS_GO_BINARY SKIP_SETUP
else
  SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
fi
# shellcheck source=../versions.env
. "${SUBSTRAIT_VERSIONS:-$ROOT/probe/versions.env}"

[ -f "$SAVED" ] || fail "no saved column at results/relations/$NAME.txt"

# The runner, and the file in it that turns one bundle into one answer: the second is what the
# fingerprint below needs, since an edit there moves answers without the participant moving.
case "$NAME" in
  DUCKDB) runner="$ROOT/probe/relations/duckdb_all.sh"; one_case="$ROOT/probe/relations/duckdb_one.py" ;;
  GO)     runner="$ROOT/probe/relations/go_all.sh";     one_case="$ROOT/probe/relations/go/main.go" ;;
  JAVA)   runner="$ROOT/probe/relations/java_all.sh";   one_case="$ROOT/probe/relations/java/RelationCase.java" ;;
  *)      fail "unknown participant $NAME" ;;
esac

fresh="$(mktemp)"; report="$(mktemp)"
trap 'rm -f "$fresh" "$report"; [ "$LATEST" != 1 ] || rm -rf "$SP"' EXIT

[ "${SKIP_SETUP:-0}" = 1 ] || bash "$ROOT/probe/relations/setup.sh" "$NAME" >&2 || fail "setup"

# The pin the environment cannot enforce. `INSTALL substrait FROM community` takes no version, so
# the extension is checked after the fact: a run that got another build is not a reproduction of
# this column whatever its answers turn out to be. Under LATEST=1 there is no pin to hold it to, and
# the head of the column records what arrived.
if [ "$NAME" = DUCKDB ] && [ "$LATEST" != 1 ]; then
  got="$("$SP/relvenv/bin/python" -c "
import duckdb
con = duckdb.connect(); con.execute('LOAD substrait')
row = con.execute(\"SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'\").fetchone()
print(row[0] if row else 'unknown')")"
  [ "$got" = "$DUCKDB_SUBSTRAIT_EXTENSION" ] || \
    fail "the community extension is $got, versions.env records $DUCKDB_SUBSTRAIT_EXTENSION"
fi

# The extract against the bundles, by re-rendering them rather than by hashing. probe/selfcheck.sh
# can only do the hash - it needs python3 and nothing else - so a spelling that drifted between
# corpus.py and the authoring side would pass the fast gate untouched. Here the protobuf bindings
# exist, so the check that catches it runs, for the participants whose environment has them.
if [ -x "$SP/relvenv/bin/python" ]; then
  "$SP/relvenv/bin/python" "$ROOT/probe/relations/expected.py" --check >/dev/null \
    || fail "results/relations/expected.json is not what the bundles render to today"
fi

bash "$runner" > "$fresh" || fail "the run did not produce a whole column"
python3 "$ROOT/probe/relations/check_column.py" "$fresh" >/dev/null || fail "the fresh column does not read"

# The versions, before the answers. Every participant writes into the head of its column what it
# was actually built from - the module graph go mod tidy resolved, the extension the community
# repository served - and answers that agree while the versions do not are not a reproduction of
# this column; they are a second measurement that happens to land in the same place. Compared as a
# string because each participant decides what belongs in its own revision line. Under LATEST=1 the
# two are expected to differ, and are printed rather than compared.
rev_of_column() { head -1 "$1" | sed 's/^[^:]*: relations column from run [^,]*, //'; }
saved_rev="$(rev_of_column "$SAVED")"
ran_rev="$(rev_of_column "$fresh")"
if [ "$LATEST" = 1 ]; then
  echo "saved: $saved_rev"
  echo "ran:   $ran_rev"
elif [ "$saved_rev" != "$ran_rev" ]; then
  echo "FAILED: this run measured a different build of $NAME" >&2
  echo "  saved: $saved_rev" >&2
  echo "  ran:   $ran_rev" >&2
  exit 1
fi

# Calling a moved answer a change in the participant means knowing that nothing on this side moved:
# the bundles, the extract the marks come from, and the code that turns an answer into a line of the
# column. Two runs reporting the same value put the same cases and wrote the answers the same way.
CORPUS_REV="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "not a checkout")"
[ -z "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ] || CORPUS_REV="$CORPUS_REV+dirty"
INPUTS="$(python3 - "$ROOT/tests/relations/bundles" "$ROOT/results/relations/expected.json" \
  "$ROOT/probe/relations/corpus.py" "$ROOT/probe/relations/column.py" \
  "$ROOT/probe/relations/drive.sh" "$runner" "$one_case" <<'FP'
import hashlib, os, sys
h = hashlib.sha256()
for arg in sys.argv[1:]:
    if os.path.isdir(arg):
        paths = sorted(os.path.join(d, f) for d, _, files in os.walk(arg) for f in files)
        base = arg
    else:
        paths, base = [arg], os.path.dirname(arg)
    for path in paths:
        h.update(os.path.relpath(path, base).encode())
        with open(path, "rb") as fh:
            h.update(fh.read())
print(h.hexdigest()[:16])
FP
)"
echo "corpus $CORPUS_REV, inputs $INPUTS"

python3 "$ROOT/probe/column_diff.py" "$SAVED" "$fresh" "relations/$NAME" > "$report"
moved=$?
# column_diff.py exits 1 for a move and also for a column it cannot read, so the summary line is
# what says the comparison ran at all.
grep -q "^relations/$NAME: [0-9]* of [0-9]* answers moved" "$report" || fail "the comparison did not run"
cat "$report"

# Written before the outcome is decided: the run most worth keeping is the one whose comparison
# failed. The block is left beside the rest rather than appended to results/DRIFT.txt, because the
# workflow runs one job per participant in separate checkouts and one later job writes the file.
# The participant is named by its column's path under results/, so it cannot be read as the DuckDB
# of the 98-plan corpus.
if [ -n "${OUT:-}" ]; then
  mkdir -p "$OUT"
  cp "$fresh" "$OUT/$NAME.txt"
  cp "$report" "$OUT/$NAME.moved"
  if [ "$LATEST" = 1 ] && [ "$moved" -ne 0 ]; then
    {
      echo "##### $(date -u +%Y-%m-%d)  relations/$NAME  $ran_rev"
      echo "corpus $CORPUS_REV, inputs $INPUTS"
      cat "$report"
    } > "$OUT/$NAME.drift"
    echo "a block for results/DRIFT.txt in $OUT/$NAME.drift"
  fi
  echo "run kept in $OUT"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### relations/$NAME — $([ "$LATEST" = 1 ] && echo "today's release" || echo "the pin")"
    echo
    echo "\`$ran_rev\`, corpus \`$CORPUS_REV\`, inputs \`$INPUTS\`."
    echo
    echo '```'
    cat "$report"
    echo '```'
  } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$LATEST" = 1 ]; then
  [ "$moved" -eq 0 ] && echo "ok      unchanged from results/relations/$NAME.txt" \
                     || echo "MOVED   results/relations/$NAME.txt describes an older release; the cases are above"
  exit 0
fi
[ "$moved" -eq 0 ] || fail "the fresh run differs from results/relations/$NAME.txt"
echo "$NAME reproduces results/relations/$NAME.txt, all $(column_body "$SAVED" | wc -l | tr -d ' ') answers"
