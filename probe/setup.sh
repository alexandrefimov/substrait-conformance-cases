#!/bin/bash
# Builds the probe environment: the venvs and the compiled substrait-go probe. Everything it
# installs lives outside the repository; the corpus and the generators are in the repository.
#
#   bash probe/setup.sh [environment directory]
#
# Default directory is <repo>/.probe-env, which .gitignore already excludes. The runners find it
# through SUBSTRAIT_PROBE_ENV, so an environment built elsewhere works just as well.
# No `set -e`. One participant that will not build used to abort the script, so a missing dependency
# for the validator meant the generator classpath - the last step, and unrelated - was never written
# either, and the next run failed on that instead of on the real cause. Each piece is run on its own,
# failures are collected, and the exit code says whether any of them failed.
set -u
FAILED_STEPS=""
step() { # <name> <command...>
  local name="$1"; shift
  echo "== $name"
  if "$@"; then return 0; fi
  echo "   FAILED: $name" >&2
  FAILED_STEPS="$FAILED_STEPS $name"
  return 0
}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SP="${1:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}"

# The pinned versions are read first, because the checks below are made against them. They used to be
# read after, so GO_MINIMUM was empty where it is compared, `sort -V` of an empty string against
# anything returned the empty string, and the comparison was true whatever go was installed: the
# version check could not fail. Only `set -u` on a machine without the file's values made it visible.
#
# Versions come from one file rather than from "whatever is latest": otherwise a second run measures
# a different environment and the saved columns stop meaning anything.
. "$(dirname "$0")/versions.env"

# rustup installs cargo into ~/.cargo/bin and leaves adding it to PATH to a shell profile, which a
# non-interactive run does not read. Without this the validator step decided cargo was absent and
# skipped itself, while reverify.sh - which does add the directory - then required the column it had
# not built. probe/reverify.sh has the same line for the same reason.
export PATH="$HOME/.cargo/bin:$PATH"

for tool in python3 go; do
  command -v "$tool" >/dev/null || { echo "$tool is not on PATH; it is needed here" >&2; exit 1; }
done

# The go version is checked here rather than left to fail inside `go get`. GOTOOLCHAIN=local below
# stops a run fetching a different toolchain, so an older go is a hard stop, and the error it gives
# on its own ("go.mod requires go >= 1.24") names a number this script wrote, not a requirement the
# reader can act on.
GO_HAVE="$(go env GOVERSION 2>/dev/null | sed 's/^go//')"
if [ -z "$GO_HAVE" ] || \
   [ "$(printf '%s\n%s\n' "$GO_MINIMUM" "$GO_HAVE" | sort -V | head -1)" != "$GO_MINIMUM" ]; then
  echo "go $GO_MINIMUM or newer is needed; this is go ${GO_HAVE:-unknown}." >&2
  echo "It is not fetched automatically: setup.sh builds with GOTOOLCHAIN=local so that a run" >&2
  echo "cannot quietly measure a toolchain other than the one it reports." >&2
  exit 1
fi
mkdir -p "$SP"

build_engines_venv() {
  python3 -m venv "$SP/venv" &&
  "$SP/venv/bin/pip" install --quiet "duckdb==$DUCKDB_VERSION" "pyarrow==$PYARROW_VERSION"
}
step "python venv (DuckDB + Acero)" build_engines_venv

build_go_probe() {
  mkdir -p "$SP/gosub9"
cp "$(dirname "$0")/go/main.go" "$SP/gosub9/main.go"
cat > "$SP/gosub9/go.mod" <<G
module probe9

go $GO_MINIMUM
G
  ( cd "$SP/gosub9"
    export GOFLAGS=-mod=mod GOTOOLCHAIN=local PATH="$HOME/.cargo/bin:$PATH"
    go get "$SUBSTRAIT_GO_MODULE@$SUBSTRAIT_GO_COMMIT" &&
    go mod tidy &&
    go build -o probe_go9 . )
}
step "substrait-go (the major version is part of the import path!)" build_go_probe

build_python_venv() {
  python3 -m venv "$SP/pysub" &&
  "$SP/pysub/bin/pip" install --quiet "substrait==$SUBSTRAIT_PYTHON_VERSION" \
    "substrait-antlr==$SUBSTRAIT_ANTLR_VERSION" "substrait-extensions==$SUBSTRAIT_EXTENSIONS_VERSION" \
    antlr4-python3-runtime pyyaml
}
step "substrait-python (its own venv: it conflicts with ibis-substrait)" build_python_venv

# protoc on its own is not enough: the validator's build compiles .proto files that import
# google/protobuf/any.proto, and those definitions ship separately. Homebrew's protobuf carries both,
# Debian and Ubuntu split them - protobuf-compiler gives the binary, libprotobuf-dev the imports -
# and without them the build fails deep inside maturin with "File not found", naming neither package.
protoc_has_well_known() {
  local d
  for d in $(protoc --version >/dev/null 2>&1 && echo "/usr/include /usr/local/include $(dirname "$(dirname "$(command -v protoc)")")/include"); do
    [ -f "$d/google/protobuf/any.proto" ] && return 0
  done
  return 1
}

build_validator() {
  [ -d "$SP/substrait-validator/.git" ] || \
    git clone -q https://github.com/substrait-io/substrait-validator "$SP/substrait-validator" || return 1
  git -C "$SP/substrait-validator" fetch -q --all &&
  git -C "$SP/substrait-validator" checkout -q "$SUBSTRAIT_VALIDATOR_COMMIT" &&
  python3 -m venv "$SP/val" &&
  PATH="$HOME/.cargo/bin:$PATH" PROTOC="$(command -v protoc)" \
    "$SP/val/bin/pip" install --quiet "$SP/substrait-validator/py" &&
  "$SP/val/bin/pip" install --quiet -U "protobuf==$PROTOBUF_RUNTIME_VERSION" &&
  echo "   built at $SUBSTRAIT_VALIDATOR_COMMIT"
}

echo "== substrait-validator (built from source; needs cargo and protoc)"
if command -v cargo >/dev/null && command -v protoc >/dev/null && protoc_has_well_known; then
  # Not a shallow clone of main: the saved column was taken at the commit versions.env names, and
  # main is not that commit any more. The 7.x protobuf runtime at the end is required too: the
  # generated code needs it while the package pins protobuf<7.
  build_validator || FAILED_STEPS="$FAILED_STEPS substrait-validator"
elif command -v cargo >/dev/null && command -v protoc >/dev/null; then
  echo "   skipped: protoc is here but google/protobuf/any.proto is not, so its build would fail"
  echo "   inside maturin. On Debian and Ubuntu that file comes from libprotobuf-dev."
  FAILED_STEPS="$FAILED_STEPS substrait-validator"
else
  echo "   skipped: cargo or protoc is not on PATH. The validator column will be skipped;"
  echo "   probe/README.md has the recipe, and SUBSTRAIT_VALIDATOR_ENV points at an existing venv."
  FAILED_STEPS="$FAILED_STEPS substrait-validator"
fi

echo "== classpath for the generators (needs a substrait-java checkout)"
if [ -n "${SUBSTRAIT_JAVA_DIR:-}" ]; then
  bash "$ROOT/gen/make_classpath.sh" || FAILED_STEPS="$FAILED_STEPS generator-classpath"
else
  echo "   skipped: SUBSTRAIT_JAVA_DIR is not set."
  echo "   SUBSTRAIT_JAVA_DIR=<checkout> bash gen/make_classpath.sh"
fi

echo
if [ -n "$FAILED_STEPS" ]; then
  echo "these did not come up:$FAILED_STEPS"
  echo "Everything else is built. reverify.sh will refuse to finish with a participant missing"
  echo "unless ALLOW_SKIPPED=1 says the partial run was meant."
  exit 1
fi
echo "done. The runners use this environment by default; override with SUBSTRAIT_PROBE_ENV=$SP"
echo "Versions are in probe/versions.env; the validator and Gluten are built separately, see probe/README.md"
