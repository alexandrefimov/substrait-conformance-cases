#!/bin/bash
# Asks four producers for a plan per query in queries.tsv, and prints what each plan contains.
#
#   DF_VENV=<venv> bash probe/producer-shapes/run_all.sh [out] [queries.tsv]
#
# It needs the probe environment (probe/setup.sh) for DuckDB and the Substrait bindings,
# SUBSTRAIT_JAVA_DIR for Isthmus and Spark, and DF_VENV pointing at a virtualenv holding the
# DataFusion package, which the probe environment does not install:
#
#   python3 -m venv <venv> && <venv>/bin/pip install datafusion==54.0.0
#
# The plans land under <out> (default: the probe environment), one directory per producer, and are
# not part of any column: this asks what a producer writes, not what a consumer answers.
set -e -o pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$D/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
OUT="${1:-$SP/producer-shapes}"
Q="${2:-$D/queries.tsv}"

"$SP/venv/bin/python" "$D/duckdb_shapes.py" "$Q" "$OUT/duckdb"
if [ -n "${DF_VENV:-}" ]; then
  "$DF_VENV/bin/python" "$D/datafusion_shapes.py" "$Q" "$OUT/datafusion"
else
  echo "DF_VENV unset: skipping DataFusion" >&2
fi
# The two Java producers go through the runners that own their classpaths; ShapesIsthmus takes the
# tables as SQL because Isthmus resolves names against a catalog it parses, not against a database.
bash "$ROOT/probe/isthmus_run.sh" ShapesIsthmus \
  "CREATE TABLE t_rn (c0 BIGINT NOT NULL, c1 BIGINT); CREATE TABLE t_nr (c0 BIGINT, c1 BIGINT NOT NULL); CREATE TABLE t_mix (c0 BIGINT NOT NULL, c1 VARCHAR NOT NULL, c2 BOOLEAN NOT NULL); CREATE TABLE t_ts (ts TIMESTAMP(9) NOT NULL); CREATE TABLE t_dec (a DECIMAL(10,2) NOT NULL, b DECIMAL(5,1) NOT NULL)" \
  "$Q" "$OUT/isthmus"
bash "$ROOT/probe/spark_run.sh" ShapesSpark "$Q" "$OUT/spark"

"$SP/pysub/bin/python" "$D/to_json.py" "$OUT"
"$SP/pysub/bin/python" -W ignore "$D/analyze_shapes.py" "$OUT"
