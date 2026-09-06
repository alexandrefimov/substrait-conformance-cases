#!/bin/bash
# Builds the probe environment: the venvs and the compiled substrait-go probe. Everything it
# installs lives outside the repository; the corpus and the generators are in the repository.
#
#   bash probe/setup.sh [environment directory]
#
# Default directory is <repo>/.probe-env, which .gitignore already excludes. The runners find it
# through SUBSTRAIT_PROBE_ENV, so an environment built elsewhere works just as well.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SP="${1:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}"

for tool in python3 go; do
  command -v "$tool" >/dev/null || { echo "$tool is not on PATH; it is needed here" >&2; exit 1; }
done

# The go version is checked here rather than left to fail inside `go get`. GOTOOLCHAIN=local below
# stops a run fetching a different toolchain, so an older go is a hard stop, and the error it gives
# on its own ("go.mod requires go >= 1.24") names a number this script wrote, not a requirement the
# reader can act on.
GO_HAVE="$(go env GOVERSION 2>/dev/null | sed 's/^go//')"
if [ "$(printf '%s\n%s\n' "$GO_MINIMUM" "$GO_HAVE" | sort -V | head -1)" != "$GO_MINIMUM" ]; then
  echo "go $GO_MINIMUM or newer is needed; this is go ${GO_HAVE:-unknown}." >&2
  echo "It is not fetched automatically: setup.sh builds with GOTOOLCHAIN=local so that a run" >&2
  echo "cannot quietly measure a toolchain other than the one it reports." >&2
  exit 1
fi
mkdir -p "$SP"

# Versions come from one file rather than from "whatever is latest": otherwise a second run
# measures a different environment and the saved columns stop meaning anything.
. "$(dirname "$0")/versions.env"

echo "== python venv (DuckDB + Acero)"
python3 -m venv "$SP/venv"
"$SP/venv/bin/pip" install --quiet "duckdb==$DUCKDB_VERSION" "pyarrow==$PYARROW_VERSION"

echo "== substrait-go (main; the major version is part of the import path!)"
mkdir -p "$SP/gosub9"
cp "$(dirname "$0")/go/main.go" "$SP/gosub9/main.go"
cat > "$SP/gosub9/go.mod" <<G
module probe9

go $GO_MINIMUM
G
( cd "$SP/gosub9"
  export GOFLAGS=-mod=mod GOTOOLCHAIN=local PATH="$HOME/.cargo/bin:$PATH"
  go get "$SUBSTRAIT_GO_MODULE@$SUBSTRAIT_GO_COMMIT"
  go mod tidy
  go build -o probe_go9 . )

echo "== substrait-python (its own venv: it conflicts with ibis-substrait)"
python3 -m venv "$SP/pysub"
"$SP/pysub/bin/pip" install --quiet "substrait==$SUBSTRAIT_PYTHON_VERSION" \
  "substrait-antlr==$SUBSTRAIT_ANTLR_VERSION" "substrait-extensions==$SUBSTRAIT_EXTENSIONS_VERSION" \
  antlr4-python3-runtime pyyaml

echo "== substrait-validator (built from source; needs cargo and protoc)"
if command -v cargo >/dev/null && command -v protoc >/dev/null; then
  # Not a shallow clone of main: the saved column was taken at the commit versions.env names, and
  # main is not that commit any more.
  [ -d "$SP/substrait-validator/.git" ] || \
    git clone -q https://github.com/substrait-io/substrait-validator "$SP/substrait-validator"
  git -C "$SP/substrait-validator" fetch -q --all
  git -C "$SP/substrait-validator" checkout -q "$SUBSTRAIT_VALIDATOR_COMMIT"
  python3 -m venv "$SP/val"
  PATH="$HOME/.cargo/bin:$PATH" PROTOC="$(command -v protoc)" \
    "$SP/val/bin/pip" install --quiet "$SP/substrait-validator/py"
  # The generated code needs a 7.x runtime; the package pins protobuf<7.
  "$SP/val/bin/pip" install --quiet -U "protobuf==$PROTOBUF_RUNTIME_VERSION"
  echo "   built at $SUBSTRAIT_VALIDATOR_COMMIT"
else
  echo "   skipped: cargo or protoc is not on PATH. The validator column will be skipped;"
  echo "   probe/README.md has the recipe, and SUBSTRAIT_VALIDATOR_ENV points at an existing venv."
fi

echo "== classpath for the generators (needs a substrait-java checkout)"
if [ -n "${SUBSTRAIT_JAVA_DIR:-}" ]; then
  bash "$ROOT/gen/make_classpath.sh"
else
  echo "   skipped: SUBSTRAIT_JAVA_DIR is not set."
  echo "   SUBSTRAIT_JAVA_DIR=<checkout> bash gen/make_classpath.sh"
fi

echo
echo "done. The runners use this environment by default; override with SUBSTRAIT_PROBE_ENV=$SP"
echo "Versions are in probe/versions.env; the validator and Gluten are built separately, see probe/README.md"
