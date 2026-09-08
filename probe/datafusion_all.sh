#!/bin/bash
# Runs every case through DataFusion's Substrait consumer.
#
#   DF_DIR=<checkout> bash probe/datafusion_all.sh [corpus]
#
# The checkout defaults to the one probe/setup.sh clones under the probe environment, so a machine
# that has never seen DataFusion needs nothing but the setup.
#
# The probe is a standalone example, placed in the checkout and taken out again: plans used to be
# copied into someone else's testdata and the probe appended to a tracked test file, then reverted
# in a trap. Now nothing tracked is touched, and the cases are read from this repository.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
DF="${DF_DIR:-$SP/datafusion}"
CASES="${1:-$ROOT/derived-schema}"
D="$(cd "$(dirname "$0")" && pwd)"
[ -d "$DF/.git" ] || { echo "not a DataFusion checkout: $DF" >&2; exit 1; }

EX="$DF/datafusion/substrait/examples/corpus_probe.rs"
[ -e "$EX" ] && {
  echo "$EX already exists in the checkout - remove it yourself, not touching what is not mine" >&2
  exit 1; }
mkdir -p "$(dirname "$EX")"
cp "$D/datafusion_corpus_probe.rs" "$EX" || exit 1
# The directories this script created go too, and it stops at the first one that is not empty: the
# point of placing an example rather than editing a tracked file is that the checkout is left
# exactly as it was found.
cleanup() {
  rm -f "$EX"
  local d; d="$(dirname "$EX")"
  while [ "$d" != "$DF" ] && [ "$d" != "/" ] && rmdir "$d" 2>/dev/null; do d="$(dirname "$d")"; done
}
trap cleanup EXIT

( cd "$DF" && SUBSTRAIT_CORPUS_DIR="$CASES" cargo run -q -p datafusion-substrait \
    --example corpus_probe 2>&1 )
