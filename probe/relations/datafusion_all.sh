#!/bin/bash
# The whole relations corpus through DataFusion, as a column.
#
#     bash probe/relations/datafusion_all.sh > results/relations/DATAFUSION.txt
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
BIN="${RELATIONS_DATAFUSION_BINARY:-$SP/reldf/target/debug/relation_case}"
DF="${DF_DIR:-$SP/datafusion}"

if [ ! -x "$BIN" ]; then
  echo "no DataFusion runner at $BIN - build it with probe/relations/setup.sh DATAFUSION" >&2
  exit 1
fi

# Two things decide the answer: the commit of DataFusion that consumes and executes the plan, and
# the release of the substrait crate the plan is decoded with, which carries its own copy of the
# Substrait protos rather than the release the cases were authored against.
sha="$(git -C "$DF" rev-parse --short HEAD 2>/dev/null)"
crate="$(awk '$0 == "name = \"substrait\"" { getline; gsub(/^version = "|"$/, ""); print; exit }' \
  "$SP/reldf/Cargo.lock" 2>/dev/null)"
rev="datafusion ${sha:-revision unknown}, substrait crate ${crate:-unknown}"

bash "$ROOT/probe/relations/drive.sh" DATAFUSION "$rev" "$BIN"
