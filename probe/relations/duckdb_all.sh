#!/bin/bash
# The whole relations corpus through DuckDB, as a column.
#
#     bash probe/relations/duckdb_all.sh > results/relations/DUCKDB.txt
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
PY="${RELATIONS_DUCKDB_PYTHON:-$SP/relvenv/bin/python}"

if [ ! -x "$PY" ]; then
  echo "no relations probe environment at $PY - build it with probe/relations/setup.sh DUCKDB" >&2
  exit 1
fi

# The version this column is taken against, read back out of what is installed rather than out of
# versions.env: the pin says what was asked for, and only the environment says what arrived. The
# community extension is why that distinction matters - `INSTALL substrait FROM community` takes
# no version, so whatever that repository serves for this DuckDB release is what a run gets.
rev="$("$PY" - <<'PYEOF'
import duckdb
con = duckdb.connect()
con.execute("LOAD substrait")
row = con.execute(
    "SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'"
).fetchone()
print("duckdb %s, substrait extension %s" % (duckdb.__version__, row[0] if row else "unknown"))
PYEOF
)" || rev="revision unknown"

bash "$ROOT/probe/relations/drive.sh" DUCKDB "$rev" "$PY" "$ROOT/probe/relations/duckdb_one.py"
