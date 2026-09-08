#!/bin/bash
# Retakes one participant's column in an environment built from nothing, and compares it with the
# saved one.
#
#   bash probe/replay_column.sh PYTHON|GO|DUCKDB|ACERO
#   LATEST=1 bash probe/replay_column.sh <NAME>
#
# Everything in results/ is measured on one workstation and saved, and selfcheck.sh only reads those
# files against each other. These four are the participants whose entire environment is a pip
# install or a go get, so they are the columns a machine that is not the author's can build from
# nothing and check. The other five want a substrait-java or a DataFusion checkout, a JDK 17, or a
# cluster, and stay saved measurements until someone automates those too.
#
# The two modes differ in what a difference means.
#
#   pinned (default)  the versions in versions.env. A difference from the saved column is a failure:
#                     same version, same corpus, same answers - or one of the three claims this
#                     repository makes about that column is wrong, and which one is worth knowing.
#   LATEST=1          today's release instead, through versions-latest.env. A difference is the
#                     finding rather than the failure: it says the participant moved since the
#                     column was taken, and names the cases it moved on. Only a broken harness -
#                     an environment that will not build, a run that comes back short - fails.
#
# OUT=<dir> keeps the run instead of throwing it away: the normalized column, the runner's raw
# output, the report, and a record naming the versions actually installed, the revision this
# repository was at, and a fingerprint of the three inputs a comparison depends on. Without those a
# difference between two runs cannot be attributed - a moved answer, a regenerated corpus and an
# edited expectation all look the same in a column.
set -uo pipefail
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$PROBE/.." && pwd)"
cd "$ROOT"

LATEST="${LATEST:-0}"
if [ "$LATEST" = 1 ]; then
  export SUBSTRAIT_VERSIONS="$PROBE/versions-latest.env"
fi
# shellcheck source=versions.env
. "${SUBSTRAIT_VERSIONS:-$PROBE/versions.env}"

FAILED=0
fail() { echo "FAILED: $*" >&2; FAILED=1; }
. "$PROBE/columns.sh"

NAME="${1:-}"
# One row per participant, because the four differ in every one of these and picking them up from
# four copies of this script is how replay_python.sh would have become replay_go.sh.
#   SETUP_KEY  the SETUP_ONLY key, spelled as setup.sh spells its step (DuckDB and Acero share one)
#   RUNNER     the script that puts the corpus through it
#   CORPUS     which corpus: substrait-python is measured on the virtual-table variant, as
#              reverify.sh measures it, because it cannot resolve the named tables the others read
#   EXT        the extension that runner globs, so "how many cases did it have to answer" is exact
#   FMT        normalize.py's format for that runner's output
#   VERDICT    the one verdict a block must carry, for the block-format runners
case "$NAME" in
  PYTHON) SETUP_KEY=substrait-python; RUNNER=python_all.sh; CORPUS=derived-schema-virtual-tables
          EXT=json; FMT=line;  VERDICT=""; GUARD=pysub/bin/python
          WANT="substrait $SUBSTRAIT_PYTHON_VERSION" ;;
  GO)     SETUP_KEY=substrait-go;     RUNNER=go_all.sh;     CORPUS=derived-schema
          EXT=bin;  FMT=block; VERDICT="^SUBSTRAITGO (ACCEPTED|REJECTED|CRASH)"; GUARD=gosub9/probe_go9
          WANT="substrait-go/${SUBSTRAIT_GO_MODULE##*/} $SUBSTRAIT_GO_COMMIT" ;;
  DUCKDB) SETUP_KEY=DuckDB;           RUNNER=duckdb_all.sh; CORPUS=derived-schema
          EXT=json; FMT=block; VERDICT="^DUCKDB (ACCEPTED|REJECTED|CRASH)"; GUARD=venv/bin/python
          WANT="duckdb $DUCKDB_VERSION" ;;
  ACERO)  SETUP_KEY=Acero;            RUNNER=acero_all.sh;  CORPUS=derived-schema
          EXT=bin;  FMT=block; VERDICT="^ACERO (ACCEPTED|REJECTED|CRASH)"; GUARD=venv/bin/python
          WANT="pyarrow $PYARROW_VERSION" ;;
  *) echo "usage: [LATEST=1] bash probe/replay_column.sh PYTHON|GO|DUCKDB|ACERO" >&2; exit 2 ;;
esac

SAVED="results/$NAME.txt"
[ -s "$SAVED" ] || { echo "FAILED: no $SAVED to compare against" >&2; exit 1; }
CASES=$(ls "$ROOT/$CORPUS"/*."$EXT" 2>/dev/null | grep -vc 'manifest\.json$')
[ "$CASES" -gt 0 ] || { echo "FAILED: no .$EXT cases in $CORPUS" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# The runners find every piece of the environment under this one directory, so pointing it at a
# fresh one is all it takes to measure an install that has no history on this machine.
export SUBSTRAIT_PROBE_ENV="$WORK"
SP="$WORK"
# The per-piece overrides are dropped rather than inherited. They exist so that a workstation can
# point at an environment it already has, which is the opposite of what this script is for: with
# SUBSTRAIT_PYTHON_ENV still set in the caller's shell, the run would build a fresh venv, measure
# the old one, and report the fresh one's version.
unset SUBSTRAIT_PYTHON_ENV SUBSTRAIT_VALIDATOR_ENV PROBE_CACHE SPARK_CP

if [ "$LATEST" = 1 ]; then
  echo "== $NAME from today's release (versions-latest.env), not the pin"
else
  echo "== $NAME at the pin: $WANT"
fi
# Built through setup.sh rather than by a pip line of its own: a second copy of a participant's
# dependencies here is one more thing to keep in step, and substrait-python already needs three
# packages beside itself.
SETUP_ONLY="$SETUP_KEY" bash "$PROBE/setup.sh" "$WORK" > "$WORK/setup.log" 2>&1
# The built artefact is what this needs, so that is what is checked. setup.sh reports on every piece
# of the environment, and treating its exit code as the answer made this fail wherever another piece
# - the validator, which wants cargo - was absent, even though nothing here asks for that piece.
[ -x "$WORK/$GUARD" ] || {
  echo "FAILED: setup.sh built no $GUARD under $WORK" >&2; tail -12 "$WORK/setup.log" >&2; exit 1; }

GOT="$(rev_of "$NAME")"
if [ "$LATEST" = 1 ]; then
  echo "   $GOT"
elif [ "$GOT" != "$WANT" ]; then
  # Not a difference in answers but in what was measured: the comparison below would be against
  # another version of the participant and would say nothing about either.
  echo "FAILED: asked for '$WANT', the environment came up as '$GOT'" >&2
  exit 1
else
  echo "   $GOT"
fi

# DuckDB's substrait support is a community extension, and INSTALL takes no version: whatever that
# repository serves is what arrives. It is therefore the one version in this run that is read back
# rather than requested, and a run that got a different one is not a reproduction of the saved
# column, whatever the answers turn out to be.
if [ "$NAME" = DUCKDB ]; then
  EXT_GOT="$("$WORK/venv/bin/python" - <<'PY' 2>/dev/null
import duckdb
con = duckdb.connect()
try:
    con.execute("INSTALL substrait"); con.execute("LOAD substrait")
except Exception:
    con.execute("INSTALL substrait FROM community"); con.execute("LOAD substrait")
row = con.execute("SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'").fetchone()
print(row[0] if row else "")
PY
)"
  echo "   substrait extension $EXT_GOT"
  if [ "$LATEST" != 1 ] && [ "$EXT_GOT" != "$DUCKDB_SUBSTRAIT_EXTENSION" ]; then
    echo "FAILED: the community extension is $EXT_GOT, versions.env records $DUCKDB_SUBSTRAIT_EXTENSION." >&2
    echo "  INSTALL cannot ask for a version, so the pin cannot be honoured - it can only be" >&2
    echo "  noticed. Retake the column against the new extension and update versions.env." >&2
    exit 1
  fi
fi

# Calling a moved answer a change in the participant means knowing that nothing on this side moved.
# One value over the corpus, the expectations and the normalization covers all three: two runs
# reporting the same fingerprint were comparing the same things.
INPUTS="$(python3 - "$ROOT/$CORPUS" "$ROOT/expected.json" "$PROBE/normalize.py" "$PROBE/column_diff.py" <<'FP'
import hashlib, os, sys
h = hashlib.sha256()
for arg in sys.argv[1:]:
    paths = [os.path.join(arg, f) for f in sorted(os.listdir(arg))] if os.path.isdir(arg) else [arg]
    for path in paths:
        if os.path.isdir(path):
            continue
        h.update(os.path.basename(path).encode())
        with open(path, "rb") as fh:
            h.update(fh.read())
print(h.hexdigest()[:16])
FP
)"
CORPUS_REV="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "not a checkout")"
[ -z "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ] || CORPUS_REV="$CORPUS_REV+dirty"
echo "   corpus $CORPUS_REV, inputs $INPUTS"

echo "== $CASES cases through $RUNNER over $CORPUS"
bash "$PROBE/$RUNNER" "$ROOT/$CORPUS" > "$WORK/raw" 2>"$WORK/raw.err"
RC=$?
[ "$RC" -eq 0 ] || { echo "FAILED: the runner returned $RC: $(head -1 "$WORK/raw.err")" >&2; exit 1; }
if [ "$FMT" = block ]; then
  check_blocks "$WORK/raw" "$CASES" "$NAME" "$VERDICT"
  # 127 = no such command: the environment fell away, the engine did not crash.
  ! grep -q 'signal/exit 127' "$WORK/raw" || fail "$NAME: exit 127 - the probe environment is missing"
fi
[ "$FAILED" -eq 0 ] || exit 1

python3 "$PROBE/normalize.py" "$WORK/raw" "$FMT" \
  "$NAME: replayed $(date +%Y-%m-%dT%H:%M), $GOT" > "$WORK/$NAME.txt" 2>"$WORK/norm.err" \
  || { echo "FAILED: normalization did not yield a whole column: $(head -1 "$WORK/norm.err")" >&2; exit 1; }

# An empty comparison would pass in silence, so the count is checked before the contents: as many
# answers as there were cases, and as many as the saved column carries.
NEW=$(column_body "$WORK/$NAME.txt" | wc -l | tr -d ' ')
OLD=$(column_body "$SAVED" | wc -l | tr -d ' ')
if [ "$NEW" != "$CASES" ] || [ "$NEW" != "$OLD" ]; then
  echo "FAILED: $NEW answers, against $CASES cases and $OLD in $SAVED" >&2
  exit 1
fi

REPORT="$WORK/report"
# The raw output goes in beside the column so the report can say REJECTED from CRASH: the column
# writes both as "ERROR: ...", which is right for the comparison against an expectation and wrong
# for reading what changed.
python3 "$PROBE/column_diff.py" "$SAVED" "$WORK/$NAME.txt" "$NAME" "$WORK/raw" > "$REPORT"
MOVED=$?
cat "$REPORT"

# Written before the outcome is decided: the run most worth keeping is the one whose comparison
# failed.
if [ -n "${OUT:-}" ]; then
  mkdir -p "$OUT"
  cp "$WORK/$NAME.txt" "$OUT/$NAME.txt"
  cp "$WORK/raw"       "$OUT/$NAME.raw"
  cp "$REPORT"         "$OUT/$NAME.moved"
  python3 - "$OUT/$NAME.json" <<REC
import json, sys
json.dump({
    "participant": "$NAME",
    "mode": "$([ "$LATEST" = 1 ] && echo latest || echo pinned)",
    "taken": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "revision": "$GOT",
    "duckdb_substrait_extension": "${EXT_GOT:-}",
    "corpus": "$CORPUS",
    "cases": $CASES,
    "corpus_revision": "$CORPUS_REV",
    "inputs_fingerprint": "$INPUTS",
    "compared_with": "$SAVED",
    "moved": $MOVED,
}, open(sys.argv[1], "w"), indent=1, sort_keys=True)
REC
  echo "   run kept in $OUT"
fi

# The drift run reports into the job summary when there is one, so a move is visible without opening
# the log. Nothing is written when the variable is unset, which is every run outside GitHub.
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### $NAME — $([ "$LATEST" = 1 ] && echo "today's release" || echo "the pin")"
    echo
    echo "\`$GOT\`, $CASES cases, corpus \`$CORPUS_REV\`, inputs \`$INPUTS\`."
    echo
    echo '```'
    cat "$REPORT"
    echo '```'
  } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$LATEST" = 1 ]; then
  # A move here is what the run went looking for. It is not a failure, and calling it one would mean
  # a red workflow every time a participant released, which is the thing being watched rather than a
  # thing going wrong.
  [ "$MOVED" -eq 0 ] && echo "ok      $NEW answers, unchanged from $SAVED" \
                     || echo "MOVED   $SAVED describes an older release; the cases are above"
  exit 0
fi
[ "$MOVED" -eq 0 ] || { echo "FAILED: the replayed column differs from $SAVED" >&2; exit 1; }
echo "ok      $NEW answers, identical to $SAVED ($GOT)"
