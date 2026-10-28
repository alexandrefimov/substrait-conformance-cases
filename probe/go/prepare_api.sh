#!/bin/bash
# Selects the API of the resolved substrait-go module for either probe.
# Run in the probe's build module, after go get and before go mod tidy:
#   bash probe/go/prepare_api.sh <substrait-go module> [codec module]
set -euo pipefail
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "usage: prepare_api.sh <substrait-go module> [codec module] (in the probe build directory)" >&2
  exit 2
fi
module_dir="$(go list -m -f '{{.Dir}}' "$1")"
adapter=api_legacy.go
if [ -f "$module_dir/wire/plan.go" ]; then
  adapter=api_wire.go
elif ! grep -q '^func FromProto(' "$module_dir/plan/plan.go"; then
  # The conversions now live in a separate codec module. Use the same source
  # revision as core: codec has its own release tags, so a core tag is not a codec version.
  version="$(go list -m -f '{{.Version}}' "$1")"
  codec_ref="$version"
  if [[ "$version" =~ [0-9]{14}-([0-9a-f]{12})$ ]]; then
    codec_ref="${BASH_REMATCH[1]}"
  else
    codec_ref="$(go list -m -f '{{.Origin.Hash}}' "$1@$version")"
    [ -n "$codec_ref" ] || { echo "no source revision for $1@$version" >&2; exit 1; }
  fi
  # Keep the resolved core even if codec requires another core version.
  go mod edit "-replace=$1=$1@$version"
  codec_module="${2:-github.com/substrait-io/substrait-go/codec/v9}"
  case "$codec_module" in
    github.com/substrait-io/substrait-go/codec/v9) adapter=api_codec.go ;;
    github.com/substrait-io/substrait-go/encoding/substraitproto) adapter=api_substraitproto.go ;;
    *) echo "unsupported Go codec module: $codec_module" >&2; exit 1 ;;
  esac
  go get "$codec_module@$codec_ref"
fi
cp "$(dirname "${BASH_SOURCE[0]}")/$adapter" api.go
