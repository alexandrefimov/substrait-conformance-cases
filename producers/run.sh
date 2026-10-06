#!/bin/bash
# Asks every producer for a plan per query in producers/queries.tsv, at the versions
# probe/versions.env pins, and compares what they wrote with the committed plans.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> DF_DIR=<checkout> bash producers/run.sh [PRODUCER ...]
#   UPDATE_PLANS=1 ... bash producers/run.sh            # write what moved into producers/plans
#
# PRODUCER is duckdb, isthmus, spark35, spark40 or datafusion; the default is all five. It needs the
# probe environment (probe/setup.sh) for DuckDB, the relations one (probe/relations/setup.sh) for
# protobuf, protoc on PATH, a substrait-java checkout at SUBSTRAIT_JAVA_COMMIT for Isthmus and Spark,
# JDK 17 for Spark, and a DataFusion checkout at DATAFUSION_COMMIT with cargo for DataFusion. A
# checkout at another commit stops the run: the plans are a measurement against the pins.
#
# It reports by default and exits 1 when a plan moved; UPDATE_PLANS=1 writes instead.
set -e -o pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$D/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
export SUBSTRAIT_PROBE_ENV="$SP"
# shellcheck disable=SC1091
. "$ROOT/probe/versions.env"
export PATH="$HOME/.cargo/bin:$PATH"
die() { echo "producers/run.sh: $*" >&2; exit 2; }

WANT=("$@"); [ ${#WANT[@]} -gt 0 ] || WANT=(duckdb isthmus spark35 spark40 datafusion)
RUN="$(mktemp -d)"; trap 'rm -rf "$RUN"' EXIT
Q="$D/queries.tsv"

for p in "${WANT[@]}"; do
  out="$RUN/$p"; mkdir -p "$out"
  case "$p" in
    duckdb)
      python3 "$D/tables.py" duckdb > "$RUN/duckdb.sql"
      v="$("$SP/venv/bin/python" "$D/duckdb_producer.py" "$RUN/duckdb.sql" "$Q" "$out" | tail -1)"
      [ "$v" = "duckdb $DUCKDB_VERSION $DUCKDB_SUBSTRAIT_EXTENSION" ] || die "DuckDB is '$v', not the pin"
      echo "$v" > "$out/PRODUCER.txt" ;;
    isthmus|spark35|spark40)
      SJ="${SUBSTRAIT_JAVA_DIR:-}"; [ -n "$SJ" ] || die "set SUBSTRAIT_JAVA_DIR"
      head="$(git -C "$SJ" rev-parse HEAD)"
      want="$(git -C "$SJ" rev-parse "$SUBSTRAIT_JAVA_COMMIT^{commit}")"
      [ "$head" = "$want" ] || die "substrait-java is at $head, not $SUBSTRAIT_JAVA_COMMIT"
      if [ "$p" = isthmus ]; then
        python3 "$D/tables.py" isthmus > "$RUN/isthmus.sql"
        bash "$ROOT/probe/isthmus_run.sh" "$D/IsthmusProducer.java" "$RUN/isthmus.sql" "$Q" "$out"
        echo "isthmus, substrait-java $SUBSTRAIT_JAVA_COMMIT" > "$out/PRODUCER.txt"
      else
        python3 "$D/tables.py" spark > "$RUN/spark.sql"
        variant=spark-3.5_2.12; pin="$SPARK_35"
        [ "$p" = spark40 ] && { variant=spark-4.0_2.13; pin="$SPARK_40"; }
        v="$(SPARK_VARIANT=$variant bash "$ROOT/probe/spark_run.sh" "$D/SparkProducer.java" \
          "$RUN/spark.sql" "$Q" "$out" | tail -1)"
        [ "$v" = "spark $pin" ] || die "Spark is '$v', not $pin"
        echo "$v, substrait-java $SUBSTRAIT_JAVA_COMMIT" > "$out/PRODUCER.txt"
      fi ;;
    datafusion)
      DF="${DF_DIR:-}"; [ -n "$DF" ] || die "set DF_DIR"
      head="$(git -C "$DF" rev-parse HEAD)"
      want="$(git -C "$DF" rev-parse "$DATAFUSION_COMMIT^{commit}")"
      [ "$head" = "$want" ] || die "DataFusion is at $head, not $DATAFUSION_COMMIT"
      command -v cargo >/dev/null || die "no cargo"
      python3 "$D/tables.py" datafusion > "$RUN/datafusion.sql"
      # The example is dropped into the checkout untracked, as probe/reverify.sh does with its own.
      mkdir -p "$DF/datafusion/substrait/examples"
      cp "$D/datafusion_producer.rs" "$DF/datafusion/substrait/examples/"
      v="$(cd "$DF" && cargo run -q --locked -p datafusion-substrait --example datafusion_producer -- \
        "$RUN/datafusion.sql" "$Q" "$out" 2>"$RUN/datafusion.err" | tail -1)" \
        || die "DataFusion producer failed: $(tail -3 "$RUN/datafusion.err")"
      echo "$v $DATAFUSION_COMMIT" > "$out/PRODUCER.txt" ;;
    *) die "unknown producer $p" ;;
  esac
  echo "$p: $(ls "$out" | grep -c '\.pb$') plans, $(ls "$out" | grep -c '\.err$') refused ($(cat "$out/PRODUCER.txt"))"
done

# The protos the corpus targets, as a descriptor set: read at run time, so the protobuf runtime
# does not have to match a protoc that generated code.
PROTO="$ROOT/tests/relations/vendor/proto"
protoc -I "$PROTO" --include_imports --descriptor_set_out="$RUN/substrait.desc" \
  "$PROTO"/substrait/*.proto "$PROTO"/substrait/extensions/*.proto
PY="$SP/relvenv/bin/python"; [ -x "$PY" ] || die "no relations environment: bash probe/relations/setup.sh"
"$PY" "$D/sync_plans.py" "$RUN/substrait.desc" "$RUN" "$D/plans" ${UPDATE_PLANS:+--write}
