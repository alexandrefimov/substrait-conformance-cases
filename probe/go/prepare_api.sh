#!/bin/bash
# Selects the API of the resolved substrait-go module for either probe.
# Run in the probe's build module, after go get and before go mod tidy:
#   bash probe/go/prepare_api.sh <substrait-go module>
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "usage: prepare_api.sh <substrait-go module> (in the probe build directory)" >&2
  exit 2
fi
module_dir="$(go list -m -f '{{.Dir}}' "$1")"
adapter=api_legacy.go
if [ -f "$module_dir/wire/plan.go" ]; then
  adapter=api_wire.go
fi
cp "$(dirname "${BASH_SOURCE[0]}")/$adapter" api.go
