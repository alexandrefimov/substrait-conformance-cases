#!/bin/bash
# Builds one participant from nothing at its pinned version, puts the relations corpus through it,
# and requires the saved column back, answer for answer.
#
#     bash probe/relations/replay.sh DUCKDB
#
# The head of a column names the day it was taken and the version it was taken against, so two runs
# never agree on it; only the answers are compared, through the same column_body the 98-case columns
# are replayed with. A difference is the finding - the participant moved, or this harness did - and
# the run says which cases moved rather than only that something did.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="${1:-}"
SAVED="$ROOT/results/relations/$NAME.txt"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"

fail() { echo "FAILED: $*" >&2; exit 1; }
# shellcheck source=../columns.sh
. "$ROOT/probe/columns.sh"
# shellcheck source=../versions.env
. "$ROOT/probe/versions.env"

[ -f "$SAVED" ] || fail "no saved column at results/relations/$NAME.txt"

case "$NAME" in
  DUCKDB) runner="$ROOT/probe/relations/duckdb_all.sh" ;;
  GO)     runner="$ROOT/probe/relations/go_all.sh" ;;
  JAVA)   runner="$ROOT/probe/relations/java_all.sh" ;;
  *)      fail "unknown participant $NAME" ;;
esac

[ "${SKIP_SETUP:-0}" = 1 ] || bash "$ROOT/probe/relations/setup.sh" "$NAME" >&2 || fail "setup"

# The pin the environment cannot enforce. `INSTALL substrait FROM community` takes no version, so
# the extension is checked after the fact: a run that got another build is not a reproduction of
# this column whatever its answers turn out to be.
if [ "$NAME" = DUCKDB ]; then
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

fresh="$(mktemp)"; trap 'rm -f "$fresh"' EXIT
bash "$runner" > "$fresh" || fail "the run did not produce a whole column"
python3 "$ROOT/probe/relations/check_column.py" "$fresh" >/dev/null || fail "the fresh column does not read"

# The versions, before the answers. Every participant writes into the head of its column what it
# was actually built from - the module graph go mod tidy resolved, the extension the community
# repository served - and answers that agree while the versions do not are not a reproduction of
# this column; they are a second measurement that happens to land in the same place. Compared as a
# string because each participant decides what belongs in its own revision line.
rev_of_column() { head -1 "$1" | sed 's/^[^:]*: relations column from run [^,]*, //'; }
if [ "$(rev_of_column "$SAVED")" != "$(rev_of_column "$fresh")" ]; then
  echo "FAILED: this run measured a different build of $NAME" >&2
  echo "  saved: $(rev_of_column "$SAVED")" >&2
  echo "  ran:   $(rev_of_column "$fresh")" >&2
  exit 1
fi

if diff <(column_body "$SAVED") <(column_body "$fresh") > /dev/null; then
  echo "$NAME reproduces results/relations/$NAME.txt, all $(column_body "$SAVED" | wc -l | tr -d ' ') answers"
  exit 0
fi
echo "MOVED: the fresh run differs from the saved column" >&2
diff <(column_body "$SAVED") <(column_body "$fresh") >&2
exit 1
