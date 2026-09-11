#!/bin/bash
# Builds the environment the relations columns are measured in, at the versions probe/versions.env
# pins - or at today's releases when SUBSTRAIT_VERSIONS names probe/versions-latest.env, which is
# how LATEST=1 probe/relations/replay.sh asks whether a participant has moved since its column was
# taken.
#
#     bash probe/relations/setup.sh [DUCKDB|GO|JAVA|DATAFUSION]
#
# Every participant reads a bundle with generated protobuf bindings and nothing else - no YAML, no
# authoring parser. That is a property of the corpus rather than a convenience, so the bindings are
# the first thing built for each of them, in that participant's own language: protoc writes the Go
# and Java ones, prost the Rust ones, tests/relations/bootstrap.sh the Python ones. A runner that
# had to compile a case first would be measuring this repository's tooling alongside the
# participant's library.
#
# After that each participant has its own dependency. substrait-go is a module at a pinned commit.
# DuckDB is a pip install plus the community substrait extension, which `INSTALL` takes no version
# for: what arrives is read back out of duckdb_extensions() by the run, and
# probe/relations/replay.sh refuses to call a run a reproduction when it is not what versions.env
# recorded.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
ENV_DIR="$SP/relvenv"
ONLY="${1:-}"
# Which Substrait protos relation_test.proto is compiled against, resolved the way
# tests/relations/lib/paths.py resolves it: the repository's own when it carries them, the vendored
# copy at the release the cases target otherwise.
PROTO_DIR="$ROOT/proto"
[ -f "$PROTO_DIR/substrait/algebra.proto" ] || PROTO_DIR="$ROOT/tests/relations/vendor/proto"
# shellcheck source=../versions.env
. "${SUBSTRAIT_VERSIONS:-$ROOT/probe/versions.env}"
# "latest" means install without a pin, as in probe/setup.sh, which the substrait-java clone below
# is delegated to and which reads the same variable.
pin() { case "${1:-}" in ""|latest) : ;; *) printf '==%s' "$1" ;; esac; }

command -v protoc >/dev/null || { echo "protoc is not on PATH; the bindings cannot be generated" >&2; exit 1; }
got="$(protoc --version | awk '{print $2}')"
[ "$got" = "$RELATIONS_PROTOC_VERSION" ] || \
  echo "note: protoc is $got, the columns were taken with $RELATIONS_PROTOC_VERSION" >&2

if [ -z "$ONLY" ] || [ "$ONLY" = "GO" ]; then
  command -v go >/dev/null || { echo "go is not on PATH; the substrait-go runner cannot be built" >&2; exit 1; }
  # GOTOOLCHAIN=local, so the go on PATH has to satisfy the module by itself rather than having a
  # different one fetched underneath the run - the same rule probe/setup.sh builds its Go probe by.
  export GOTOOLCHAIN=local GOFLAGS=-mod=mod
  export PATH="$(go env GOPATH)/bin:$PATH"
  command -v protoc-gen-go >/dev/null || \
    go install "google.golang.org/protobuf/cmd/protoc-gen-go@$RELATIONS_PROTOC_GEN_GO_VERSION"
  rm -rf "$SP/relgo"
  mkdir -p "$SP/relgo"
  cp "$ROOT/probe/relations/go/main.go" "$SP/relgo/main.go"
  cat > "$SP/relgo/go.mod" <<GOMOD
module relationtest

go $GO_MINIMUM
GOMOD
  # Only relation_test.proto is generated here. The Substrait protos it imports already declare the
  # go_package of the published substrait-protobuf module, so the bundle is read with that module's
  # bindings rather than with a second copy of them compiled beside it.
  protoc -I "$PROTO_DIR" -I "$ROOT/proto" \
    --go_out="$SP/relgo" --go_opt=module=relationtest \
    --go_opt=Msubstrait/test/relation_test.proto=relationtest/gen \
    substrait/test/relation_test.proto
  ( cd "$SP/relgo"
    go get "$SUBSTRAIT_GO_MODULE@$SUBSTRAIT_GO_COMMIT" &&
    go mod tidy &&
    go build -o relgo . ) || { echo "the substrait-go runner did not build" >&2; exit 1; }
  echo "substrait-go runner: $SP/relgo/relgo"
fi

if [ -z "$ONLY" ] || [ "$ONLY" = "JAVA" ]; then
  # The classpath is resolved by probe/cp.sh, which is where the reasoning about it lives, and is
  # written into the probe environment rather than into the repository: a run that writes into the
  # tree it is measuring is not measuring that tree. Every entry is an absolute path into one
  # machine's Gradle cache, which is why it is never committed.
  export SUBSTRAIT_CLASSPATH="$SP/relations_core_cp.txt"
  # A machine that has never seen substrait-java gets one at the pinned commit, the same way the
  # other corpus's columns are retaken somewhere new. probe/setup.sh owns that clone - a second
  # place that knows how to fetch this project is a second place to keep the pin in step - and
  # writes the classpath into the file probe/cp.sh then reads, so Gradle runs once and not twice.
  if [ -z "${SUBSTRAIT_JAVA_DIR:-}" ] && [ ! -d "$SP/substrait-java/.git" ]; then
    SETUP_ONLY=substrait-java bash "$ROOT/probe/setup.sh" "$SP" \
      || { echo "substrait-java did not clone or build" >&2; exit 1; }
  fi
  CP="$(bash "$ROOT/probe/cp.sh" core)" || { echo "the substrait-java classpath did not resolve" >&2; exit 1; }
  # protoc stamps its own version into the gencode it writes, and protobuf-java refuses to load
  # gencode newer than itself. substrait-java resolves 4.35.1 at the pinned commit and protoc here
  # is 36.1, so the runtime is resolved separately and put ahead of it - on this runner's classpath
  # and nowhere else. Resolved through Gradle rather than taken from whichever jar the cache happens
  # to hold, so the version is the one versions.env names on a machine that has none of them.
  pbjar="$SP/relations_protobuf_java.txt"
  if [ ! -s "$pbjar" ]; then
    init="$SP/relations_pb.gradle"
    cat > "$init" <<GRADLE
gradle.afterProject { pr ->
  if (pr.path == ':core') {
    pr.tasks.register('printRelationsPb') {
      doLast {
        def dep = pr.dependencies.create('com.google.protobuf:protobuf-java:$RELATIONS_PROTOBUF_JAVA_VERSION')
        println "CPSTART"
        println pr.configurations.detachedConfiguration(dep).resolve().join(':')
        println "CPEND"
      }
    }
  }
}
GRADLE
    ( cd "${SUBSTRAIT_JAVA_DIR:-$SP/substrait-java}" && ./gradlew -q --init-script "$init" :core:printRelationsPb ) \
      | awk '/CPSTART/{f=1;next}/CPEND/{f=0}f' > "$pbjar"
  fi
  [ -s "$pbjar" ] || { echo "protobuf-java $RELATIONS_PROTOBUF_JAVA_VERSION did not resolve" >&2; exit 1; }
  # Only when it is the newer of the two. A substrait-java past its pin - LATEST=1 follows main -
  # can resolve a newer runtime for gencode of its own, and this one ahead of it would then break
  # every case at once rather than none.
  theirs="$(tr ':' '\n' <<< "$CP" | sed -n 's#.*/protobuf-java-\([0-9][0-9.]*\)\.jar$#\1#p' | head -1)"
  newest="$(printf '%s\n%s\n' "${theirs:-0}" "$RELATIONS_PROTOBUF_JAVA_VERSION" | sort -V | tail -1)"
  [ "$newest" = "${theirs:-}" ] || CP="$(cat "$pbjar"):$CP"
  # JAVA17_HOME if the caller named one, then the JAVA_HOME it already has when that is the version
  # versions.env asks for, and only then the macOS locator. The middle step is the one that was
  # missing: /usr/libexec/java_home is a Mac, so this passed here and failed on the first Linux
  # runner it met, where the right JDK had been on JAVA_HOME the whole time.
  JAVA_HOME_17="${JAVA17_HOME:-}"
  if [ -z "$JAVA_HOME_17" ] && [ -x "${JAVA_HOME:-/nonexistent}/bin/javac" ]; then
    case "$("$JAVA_HOME/bin/javac" -version 2>&1)" in
      *" $JAVA_VERSION."*) JAVA_HOME_17="$JAVA_HOME" ;;
    esac
  fi
  [ -n "$JAVA_HOME_17" ] || \
    JAVA_HOME_17="$(/usr/libexec/java_home -v "$JAVA_VERSION" 2>/dev/null || true)"
  [ -n "$JAVA_HOME_17" ] || {
    echo "no JDK $JAVA_VERSION: not in JAVA17_HOME, not in JAVA_HOME, not known to java_home" >&2
    exit 1; }
  rm -rf "$SP/reljava"
  mkdir -p "$SP/reljava/gen" "$SP/reljava/out"
  # Only relation_test.proto is generated. Its imports resolve to io.substrait.proto.* out of the
  # protobuf artifact already on the classpath, so the bundle is read with substrait-java's own
  # bindings rather than with a second copy of the Substrait protos compiled beside them.
  protoc -I "$PROTO_DIR" -I "$ROOT/proto" --java_out="$SP/reljava/gen" \
    substrait/test/relation_test.proto
  "$JAVA_HOME_17/bin/javac" -nowarn -cp "$CP" -d "$SP/reljava/out" \
    $(find "$SP/reljava/gen" -name '*.java') "$ROOT/probe/relations/java/RelationCase.java" \
    || { echo "the substrait-java runner did not compile" >&2; exit 1; }
  printf '%s\n' "$CP" > "$SP/reljava/cp.txt"
  printf '%s\n' "$JAVA_HOME_17" > "$SP/reljava/java_home.txt"
  echo "substrait-java runner: $SP/reljava/out"
fi

if [ -z "$ONLY" ] || [ "$ONLY" = "DATAFUSION" ]; then
  # rustup puts cargo in ~/.cargo/bin and leaves PATH to a shell profile a script does not read.
  export PATH="$HOME/.cargo/bin:$PATH"
  command -v cargo >/dev/null || {
    echo "cargo is not on PATH; the DataFusion runner cannot be built" >&2; exit 1; }
  # The checkout comes from probe/setup.sh, as substrait-java's does above and for the same reason:
  # one place that knows how to fetch the project at its pin. It is cloned without blobs there.
  DF="${DF_DIR:-$SP/datafusion}"
  if [ -z "${DF_DIR:-}" ] && [ ! -e "$DF/.git" ]; then
    SETUP_ONLY=datafusion bash "$ROOT/probe/setup.sh" "$SP" >&2 \
      || { echo "DataFusion did not clone" >&2; exit 1; }
  fi
  [ -f "$DF/datafusion/substrait/Cargo.toml" ] || {
    echo "not a DataFusion checkout: $DF" >&2; exit 1; }
  # Absolute, because the crate below names it from another directory.
  DF="$(cd "$DF" && pwd)"
  # A checkout that was already there is used as it stands, and one at another commit is measured
  # at that commit. The column's head records which, and probe/relations/replay.sh refuses the run
  # as a reproduction; this says so before the build rather than after it.
  want="$(git -C "$DF" rev-parse -q --verify "$DATAFUSION_COMMIT^{commit}" 2>/dev/null || true)"
  [ "$(git -C "$DF" rev-parse HEAD 2>/dev/null)" = "$want" ] || \
    echo "note: $DF is not at $DATAFUSION_COMMIT, and the column will be taken at what it is" >&2
  # A crate of its own beside the checkout rather than an example inside it, as the 98-plan probe
  # is: the bindings need a build script, and an example only shares its package's, which would
  # mean editing the checkout. It depends on the checkout by path, and takes the checkout's
  # lockfile and toolchain so the libraries it resolves are the ones that commit builds with.
  # prost has to be the release the substrait crate derives its messages with, or the generated
  # RelationTestCase cannot hold them, so it is read from the checkout too.
  prost="$(sed -n 's/^prost = "\([^"]*\)".*/\1/p' "$DF/Cargo.toml")"
  [ -n "$prost" ] || { echo "no prost version in $DF/Cargo.toml" >&2; exit 1; }
  R="$SP/reldf"
  rm -rf "$R"
  mkdir -p "$R"
  cp "$ROOT/probe/relations/datafusion/main.rs" "$ROOT/probe/relations/datafusion/build.rs" "$R/"
  cp "$DF/Cargo.lock" "$R/Cargo.lock"
  [ ! -f "$DF/rust-toolchain.toml" ] || cp "$DF/rust-toolchain.toml" "$R/"
  cat > "$R/Cargo.toml" <<TOML
[package]
name = "relation-case"
version = "0.0.0"
edition = "2024"
publish = false

[[bin]]
name = "relation_case"
path = "main.rs"

[dependencies]
datafusion = { path = "$DF/datafusion/core" }
datafusion-substrait = { path = "$DF/datafusion/substrait" }
prost = "$prost"
tokio = { version = "1", features = ["rt-multi-thread", "macros"] }

[build-dependencies]
prost-build = "$prost"

[workspace]
TOML
  ( cd "$R" && RELATIONS_REPO="$ROOT" cargo build -q ) \
    || { echo "the DataFusion runner did not build" >&2; exit 1; }
  echo "DataFusion runner: $R/target/debug/relation_case"
fi

# Everything below is the Python side: the runners written in it, and probe/relations/expected.py.
case "$ONLY" in GO|JAVA|DATAFUSION) exit 0 ;; esac

python3 -m venv "$ENV_DIR"
# pyyaml is not the measurement's: it is what tests/relations compiles a case with. The environment
# this script builds is the one a person retaking a column has, and they will want to run the
# corpus's own gates in it too - `pytest tests/relations` collects nothing without it. It was in the
# environment the first columns were taken in only because it had been installed there by hand.
"$ENV_DIR/bin/pip" install --quiet --disable-pip-version-check \
  "protobuf==$RELATIONS_PROTOBUF_VERSION" pyyaml

if [ -z "$ONLY" ] || [ "$ONLY" = "DUCKDB" ]; then
  "$ENV_DIR/bin/pip" install --quiet --disable-pip-version-check "duckdb$(pin "$DUCKDB_VERSION")"
  "$ENV_DIR/bin/python" - <<'PYEOF'
import duckdb
con = duckdb.connect()
con.execute("INSTALL substrait FROM community")
con.execute("LOAD substrait")
row = con.execute(
    "SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'"
).fetchone()
print("duckdb %s, substrait extension %s" % (duckdb.__version__, row[0] if row else "unknown"))
PYEOF
fi

PATH="$ENV_DIR/bin:$PATH" bash "$ROOT/tests/relations/bootstrap.sh"
echo "relations probe environment: $ENV_DIR"
