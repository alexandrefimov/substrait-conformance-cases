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
elif ! grep -q '^func FromProto(' "$module_dir/plan/plan.go"; then
  # The conversions now live in a separate codec module. Use the same source
  # revision for pseudo-versions; release tags are shared by core and codec.
  version="$(go list -m -f '{{.Version}}' "$1")"
  codec_ref="$version"
  if [[ "$version" =~ [0-9]{14}-([0-9a-f]{12})$ ]]; then
    codec_ref="${BASH_REMATCH[1]}"
  fi
  # The unreleased codec declares core v9.0.0 and replaces it locally. A
  # consumer does not inherit that replacement, so keep the core we resolved.
  go mod edit "-replace=$1=$1@$version"
  go get "github.com/substrait-io/substrait-go/codec/v9@$codec_ref"
  adapter=api_codec.go
fi
cp "$(dirname "${BASH_SOURCE[0]}")/$adapter" api.go
