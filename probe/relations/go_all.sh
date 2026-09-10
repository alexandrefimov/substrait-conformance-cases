#!/bin/bash
# The whole relations corpus through substrait-go, as a column.
#
#     bash probe/relations/go_all.sh > results/relations/GO.txt
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
BIN="${RELATIONS_GO_BINARY:-$SP/relgo/relgo}"

if [ ! -x "$BIN" ]; then
  echo "no substrait-go runner at $BIN - build it with probe/relations/setup.sh GO" >&2
  exit 1
fi

# Three versions, because three different things decide the answer: the library that derives the
# schema, the protobuf bindings the bundle is read with, and the release of the specification the
# library itself pins - which is not the release the cases were authored against, and is part of
# what a disagreement has to be read against.
rev="$(awk '
  /substrait-io\/substrait-go\/v[0-9]+ v/ { go_ver = $1 " " $2 }
  /substrait-io\/substrait-protobuf\/go v/ { pb = $1 " " $2 }
  /substrait-io\/substrait v[0-9]/ { spec = $1 " " $2 }
  END { printf "%s, %s, pinning %s", go_ver, pb, spec }
' "$SP/relgo/go.mod")" || rev="revision unknown"
case "$rev" in *", , pinning "*|"") rev="revision unknown" ;; esac

bash "$ROOT/probe/relations/drive.sh" GO "$rev" "$BIN"
