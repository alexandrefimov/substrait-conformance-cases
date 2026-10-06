#!/bin/bash
# Hands every committed producer plan to the consumers, at the versions probe/versions.env pins, and
# compares their answers with results/producers/consume/<NAME>.txt.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> DF_DIR=<checkout> bash producers/consume.sh [NAME ...]
#   UPDATE_CONSUME=1 ... bash producers/consume.sh      # write the answers instead
#
# NAME is one of the nine consumer columns of the main corpus (PYTHON GO VALIDATOR JAVA ISTHMUS
# SPARK DUCKDB DATAFUSION ACERO); the default is all nine. Each goes through the runner that takes its
# column there, over a flat copy of producers/plans named <producer>__<query> with table names in
# the probes' catalog (producers/catalog_names.py), so a consumer here is the same build and the same
# probe as in results/<NAME>.txt. An environment that is not at the pin
# stops the run. It reports by default and exits 1 when an answer moved.
set -uo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
PROBE="$ROOT/probe"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
export SUBSTRAIT_PROBE_ENV="$SP"
# shellcheck disable=SC1091
. "$PROBE/versions.env"
export PATH="$HOME/.cargo/bin:$PATH"
SJ="${SUBSTRAIT_JAVA_DIR:-$SP/substrait-java}"; export SUBSTRAIT_JAVA_DIR="$SJ"
DF="${DF_DIR:-$SP/datafusion}"; export DF_DIR="$DF"
FAILED=0
HARNESS_FAILED=0
fail() { echo "FAILED: $*" >&2; FAILED=1; HARNESS_FAILED=1; }
# shellcheck disable=SC1091
. "$PROBE/columns.sh"

WANT_ALL=("$@"); [ ${#WANT_ALL[@]} -gt 0 ] || WANT_ALL=(PYTHON GO VALIDATOR JAVA ISTHMUS SPARK DUCKDB DATAFUSION ACERO)
OUT="$ROOT/results/producers/consume"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
CORPUS="$WORK/corpus"
PROTO="$ROOT/tests/relations/vendor/proto"
protoc -I "$PROTO" --include_imports --descriptor_set_out="$WORK/substrait.desc" \
  "$PROTO"/substrait/*.proto "$PROTO"/substrait/extensions/*.proto || exit 2
"$SP/relvenv/bin/python" "$D/catalog_names.py" "$WORK/substrait.desc" "$D/plans" "$CORPUS" || exit 2
CASES=$(ls "$CORPUS"/*.json | wc -l | tr -d ' ')
moved=0

for NAME in "${WANT_ALL[@]}"; do
  FAILED=0
  # The runner, what it globs, the normalization format and the one verdict a block must carry,
  # as probe/replay_column.sh has them.
  case "$NAME" in
    PYTHON)     RUNNER=python_all.sh;     FMT=line;  VERDICT=""; WANT="substrait $SUBSTRAIT_PYTHON_VERSION" ;;
    GO)         RUNNER=go_all.sh;         FMT=block; VERDICT="^SUBSTRAITGO (ACCEPTED|REJECTED|CRASH)"
                WANT="substrait-go/${SUBSTRAIT_GO_MODULE##*/} $SUBSTRAIT_GO_COMMIT" ;;
    VALIDATOR)  RUNNER=validator_all.sh;  FMT=block; VERDICT=""
                WANT="substrait-validator $SUBSTRAIT_VALIDATOR_VERSION at $SUBSTRAIT_VALIDATOR_COMMIT" ;;
    JAVA)       RUNNER=java_all.sh;       FMT=line;  VERDICT=""
                WANT="substrait-java $(git -C "$SJ" rev-parse --short "$SUBSTRAIT_JAVA_COMMIT" 2>/dev/null)" ;;
    ISTHMUS)    RUNNER=isthmus_all.sh;    FMT=block; VERDICT="^ISTHMUS (ACCEPTED|REJECTED)"
                WANT="substrait-java $(git -C "$SJ" rev-parse --short "$SUBSTRAIT_JAVA_COMMIT" 2>/dev/null)" ;;
    SPARK)      RUNNER=spark_all.sh;      FMT=line;  VERDICT=""; WANT="spark $SPARK_35" ;;
    DUCKDB)     RUNNER=duckdb_all.sh;     FMT=block; VERDICT="^DUCKDB (ACCEPTED|REJECTED|CRASH)"; WANT="duckdb $DUCKDB_VERSION" ;;
    DATAFUSION) RUNNER=datafusion_all.sh; FMT=block; VERDICT="^DATAFUSION (ACCEPTED|REJECTED)"
                WANT="datafusion $(git -C "$DF" rev-parse --short "$DATAFUSION_COMMIT" 2>/dev/null)" ;;
    ACERO)      RUNNER=acero_all.sh;      FMT=block; VERDICT="^ACERO (ACCEPTED|REJECTED|CRASH)"; WANT="pyarrow $PYARROW_VERSION" ;;
    *) echo "unknown consumer $NAME" >&2; exit 2 ;;
  esac
  [ "$NAME" = SPARK ] && bash "$PROBE/cp.sh" spark >/dev/null
  GOT="$(rev_of "$NAME")"
  [ "$GOT" = "$WANT" ] || { fail "$NAME is '$GOT', not the pin '$WANT'"; continue; }
  # Checkout pins compare full revisions; saved headers use the pin's spelling, independent
  # of Git's default abbreviation length in a fresh clone.
  case "$NAME" in
    JAVA|ISTHMUS)
      [ "$(git -C "$SJ" rev-parse HEAD)" = "$(git -C "$SJ" rev-parse "$SUBSTRAIT_JAVA_COMMIT^{commit}")" ] \
        || { fail "$NAME: the checkout is not at $SUBSTRAIT_JAVA_COMMIT"; continue; }
      GOT="substrait-java $SUBSTRAIT_JAVA_COMMIT" ;;
    DATAFUSION)
      [ "$(git -C "$DF" rev-parse HEAD)" = "$(git -C "$DF" rev-parse "$DATAFUSION_COMMIT^{commit}")" ] \
        || { fail "$NAME: the checkout is not at $DATAFUSION_COMMIT"; continue; }
      GOT="datafusion $DATAFUSION_COMMIT" ;;
  esac
  echo "== $NAME ($GOT): $CASES plans"
  bash "$PROBE/$RUNNER" "$CORPUS" > "$WORK/$NAME.raw" 2>"$WORK/$NAME.err" \
    || { fail "$NAME: the runner failed: $(tail -1 "$WORK/$NAME.err")"; continue; }
  if [ "$FMT" = block ]; then
    check_blocks "$WORK/$NAME.raw" "$CASES" "$NAME" "$VERDICT"
    [ "$FAILED" -eq 0 ] || continue
  fi
  python3 "$PROBE/normalize.py" "$WORK/$NAME.raw" "$FMT" \
    "$NAME: the committed producer plans, $GOT" > "$WORK/$NAME.txt" 2>"$WORK/$NAME.norm" \
    || { fail "$NAME: normalization did not yield a whole column: $(head -1 "$WORK/$NAME.norm")"; continue; }
  n=$(column_body "$WORK/$NAME.txt" | wc -l | tr -d ' ')
  [ "$n" -eq "$CASES" ] || { fail "$NAME: $n answers for $CASES plans"; continue; }
  if [ -n "${UPDATE_CONSUME:-}" ]; then
    mkdir -p "$OUT"; cp "$WORK/$NAME.txt" "$OUT/$NAME.txt"
    echo "   written"
  elif [ ! -f "$OUT/$NAME.txt" ] || ! diff -q <(column_body "$OUT/$NAME.txt") <(column_body "$WORK/$NAME.txt") >/dev/null; then
    moved=1
    echo "   moved:"; diff <(column_body "$OUT/$NAME.txt" 2>/dev/null) <(column_body "$WORK/$NAME.txt") | head -20
  else
    echo "   same"
  fi
done
[ "$HARNESS_FAILED" -eq 0 ] || exit 2
exit "$moved"
