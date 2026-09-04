#!/bin/bash
# Re-runs the whole corpus: regenerates the cases, puts them through every participant whose
# environment is up, and prints all the sides next to each other. It publishes nothing.
#
# FAIL-CLOSED: any harness failure (missing environment, a generator that will not build, cargo
# dying, fewer blocks coming back than there are cases) gives a non-zero exit and a FAILED line.
# A single case failing inside an engine is not a harness failure: that is the finding.
#
#   SUBSTRAIT_JAVA_DIR=<path>   substrait-java checkout (required)
#   DF_DIR=<path>               DataFusion checkout or worktree (required)
#   SUBSTRAIT_PROBE_ENV=<path>  probe environment (venvs, probe_go9); default <repo>/.probe-env,
#                               built by probe/setup.sh
#   SJ_EXPECT=<ref>             if set, require this HEAD in substrait-java
#   DF_EXPECT=<ref>             if set, require this HEAD in DataFusion
#   REBUILD_CORE=1              rebuild :core before the run instead of trusting the classpath
#   EXPECT_CASES=<n>            require exactly n generated cases
#   UPDATE_CORPUS=1             replace the saved corpus with this run's generation
#   UPDATE_COLUMNS=1            replace the saved columns with this run's
#   ALLOW_SKIPPED=1             accept a run in which some participant's environment was absent
set -uo pipefail

# Paths come from where the script sits, not from anything hard-coded: an absolute path to one
# machine's home directory used to stand here, and the preflight check failed for anyone else.
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$PROBE/.." && pwd)"
CASES=$ROOT/derived-schema
GEN=$ROOT/gen
SJ="${SUBSTRAIT_JAVA_DIR:-}"
DF="${DF_DIR:-}"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
export PATH="$HOME/.cargo/bin:$PATH"

FAILED=0
fail() { echo "FAILED: $*" >&2; FAILED=1; }
die()  { echo "FAILED: $*" >&2; exit 1; }

echo "### 0. preflight"
[ -n "$SJ" ] || die "set SUBSTRAIT_JAVA_DIR to a substrait-java checkout"
[ -n "$DF" ] || die "set DF_DIR to a DataFusion checkout"
[ -x "$SP/venv/bin/python" ] || die "no probe venv: $SP/venv (see probe/setup.sh)"
[ -x "$SP/gosub9/probe_go9" ] || die "no substrait-go probe: $SP/gosub9/probe_go9"
[ -d "$SJ/.git" ] || [ -f "$SJ/.git" ] || die "not a substrait-java checkout: $SJ"
[ -d "$DF/.git" ] || [ -f "$DF/.git" ] || die "not a DataFusion checkout: $DF"
command -v javac >/dev/null || die "no javac"
command -v cargo >/dev/null || die "no cargo"
[ -s "$GEN/classpath.txt" ] || die "no $GEN/classpath.txt (run gen/make_classpath.sh)"
for jar in $(tr ':' '\n' < "$GEN/classpath.txt"); do
  [ -e "$jar" ] || die "classpath points at something that does not exist: $jar"
done

git -C "$SJ" fetch origin --quiet || fail "git fetch substrait-java"
SJ_HEAD=$(git -C "$SJ" rev-parse --short HEAD)
DF_HEAD=$(git -C "$DF" rev-parse --short HEAD)
echo "substrait-java HEAD=$SJ_HEAD origin/main=$(git -C "$SJ" rev-parse --short origin/main)"
echo "datafusion     HEAD=$DF_HEAD branch=$(git -C "$DF" rev-parse --abbrev-ref HEAD) (checkout: $DF)"
if [ -n "${SJ_EXPECT:-}" ] && [ "$SJ_HEAD" != "$(git -C "$SJ" rev-parse --short "$SJ_EXPECT" 2>/dev/null)" ]; then
  die "substrait-java is not at $SJ_EXPECT (currently $SJ_HEAD)"
fi
# :core is taken prebuilt from classpath.txt, so where those classes came from has to be either
# guaranteed by a rebuild or stated plainly. Guessing from mtimes is pointless: after a checkout
# the timestamps say nothing about which commit the classes were built from.
if [ "${REBUILD_CORE:-0}" = "1" ]; then
  echo "rebuilding :core at $SJ_HEAD"
  ( cd "$SJ" && ./gradlew --quiet :core:compileJava ) || die ":core did not build"
  echo ":core rebuilt at $SJ_HEAD"
else
  echo ":core is PREBUILT - this script does not vouch for where those classes came from."
  echo "  For a run anything public points at: REBUILD_CORE=1 SJ_EXPECT=<sha>."
fi
if [ -n "${DF_EXPECT:-}" ] && [ "$DF_HEAD" != "$(git -C "$DF" rev-parse --short "$DF_EXPECT" 2>/dev/null)" ]; then
  die "DataFusion is not at $DF_EXPECT (currently $DF_HEAD)"
fi
# Tracked files must be clean: the probe does not touch them, so anything dirty here is someone
# else's work. Untracked files no longer block: the probe drops its own example in and takes it
# out again, and a name collision is caught by its own check below.
DF_TRACKED_DIRTY="$(git -C "$DF" status --porcelain --untracked-files=no)"
[ -z "$DF_TRACKED_DIRTY" ] || die "the DataFusion checkout has modified tracked files, leaving them alone:
$DF_TRACKED_DIRTY"

echo "harness versions:"
"$SP/venv/bin/python" - <<'PY' || fail "probe python environment"
import duckdb, pyarrow
print("  duckdb   %s" % duckdb.__version__)
print("  pyarrow  %s" % pyarrow.__version__)
con = duckdb.connect()
try:
    con.execute("INSTALL substrait"); con.execute("LOAD substrait")
except Exception:
    con.execute("INSTALL substrait FROM community"); con.execute("LOAD substrait")
v = con.execute("SELECT extension_version FROM duckdb_extensions() WHERE extension_name='substrait'").fetchone()
print("  duckdb substrait extension %s" % (v[0] if v else "?"))
PY
grep -m1 -o 'substrait-go/v[0-9]* v[0-9a-z.\-]*' "$SP/gosub9/go.mod" 2>/dev/null | sed 's/^/  substrait-go /' || true

echo
echo "### 1. generating the cases, and the substrait-java side"
CP="$(cat "$GEN/classpath.txt")"
rm -rf "$GEN/out"; mkdir -p "$GEN/out"
GENS="GenCases GenDisputed GenSetOps GenJoins GenNarrowing GenEmit GenProjection GenSetData GenStringLen GenPhase GenDecimal GenControl JsonToBin"
SRCS=""; for g in $GENS Tables; do SRCS="$SRCS $GEN/$g.java"; done
javac -nowarn -cp "$CP" -d "$GEN/out" $SRCS || die "javac of the generators"

# Generation goes into a temporary directory, not over the saved corpus. There used to be an
# rm -f "$CASES"/*.json here, so the documented run with a stale EXPECT_CASES erased the golden
# corpus first and failed afterwards - the check destroyed the thing it was checking.
STAGE="$(mktemp -d)"
# One trap for the whole script. There used to be two, and the second (cleaning up after the
# DataFusion probe) silently replaced the first, so STAGE was never removed.
cleanup_df() { :; }
cleanup_all() { rm -rf "$STAGE" "${RUN:-}"; cleanup_df; }
trap cleanup_all EXIT
for g in $GENS; do
  java -cp "$GEN/out:$CP" "$g" "$STAGE" 2>&1 | grep -vE "SLF4J|WARNING"
  [ "${PIPESTATUS[0]}" -eq 0 ] || die "generator $g"
done

N_JSON=$(ls "$STAGE"/*.json 2>/dev/null | grep -vc 'manifest\.json$')
N_BIN=$(ls "$STAGE"/*.bin 2>/dev/null | wc -l | tr -d ' ')
echo "cases: json=$N_JSON bin=$N_BIN"
[ "$N_JSON" -gt 0 ] || die "no cases were generated"
[ "$N_JSON" -eq "$N_BIN" ] || die "json ($N_JSON) != bin ($N_BIN)"
if [ -n "${EXPECT_CASES:-}" ] && [ "$N_JSON" -ne "$EXPECT_CASES" ]; then
  die "expected $EXPECT_CASES cases, got $N_JSON (the saved corpus is untouched)"
fi

# The saved corpus is replaced only when explicitly asked for. By default the fresh generation is
# compared against it, and a difference is a report rather than a silent overwrite of the inputs.
if [ "${UPDATE_CORPUS:-0}" = "1" ]; then
  rm -f "$CASES"/*.json "$CASES"/*.bin
  cp "$STAGE"/*.json "$STAGE"/*.bin "$CASES"/ 2>/dev/null
  echo "corpus updated from the fresh generation (UPDATE_CORPUS=1)"
else
  DRIFT=0
  for f in "$STAGE"/*.json; do
    n="$(basename "$f")"
    if [ ! -f "$CASES/$n" ]; then echo "  new case, absent from the corpus: $n"; DRIFT=1; continue; fi
    cmp -s "$f" "$CASES/$n" || { echo "  differs from the corpus: $n"; DRIFT=1; }
  done
  for f in "$CASES"/*.json; do
    n="$(basename "$f")"; [ "$n" = manifest.json ] && continue
    [ -f "$STAGE/$n" ] || { echo "  in the corpus, not produced by the generator: $n"; DRIFT=1; }
  done
  if [ "$DRIFT" -eq 0 ]; then
    echo "the fresh generation matches the saved corpus"
  else
    # The participants are run against the saved corpus. If the generator produces something else,
    # the run measures one set of cases while the repository describes another, and nobody sees the
    # difference: this used to be a warning, and a run with a drifted corpus still ended in RESULT.
    fail "generation drifted from the saved corpus; check it, and if the difference is expected, UPDATE_CORPUS=1"
  fi
fi

# The manifest says, per case, which generator writes it and what that generator calls it. It is
# built from the generators rather than kept by hand, so it is checked the way the corpus is: rebuilt
# into a temporary file and compared, replaced only under UPDATE_CORPUS=1.
MAN="$(mktemp)"
if bash "$GEN/make_manifest.sh" "$MAN" >/dev/null 2>&1; then
  if [ "${UPDATE_CORPUS:-0}" = "1" ]; then
    cp "$MAN" "$CASES/manifest.json"
    echo "manifest updated from the fresh generation (UPDATE_CORPUS=1)"
  elif cmp -s "$MAN" "$CASES/manifest.json"; then
    echo "the manifest matches the saved one"
  else
    fail "the manifest drifted from the saved one; sync it with UPDATE_CORPUS=1"
  fi
else
  fail "could not rebuild the manifest"
fi
rm -f "$MAN"

# Every ##### block must carry a verdict. Counting blocks is not enough: a block without a
# verdict is a case silently lost.
check_blocks() { # <file> <expected> <name> <verdict-regexp>
  local got crashes bad
  got=$(grep -c '^#####' "$1")
  [ "$got" -eq "$2" ] || fail "$3: $got blocks instead of $2 - the run is incomplete"

  # Per block, not in total. Two independent counters used to be compared here, so a case with two
  # verdicts covered for a case with none, and a run with a hole passed as complete.
  # `started` tells "we are inside a block" from "before the first block": without it a blank line
  # at the top of the output counted as a block without a verdict, and the check failed with an
  # empty list of names.
  bad=$(awk -v re="$4" '
    /^#####/ { if (started && seen != 1) { printf "%s ", name } ; name = $2; seen = 0; started = 1; next }
    $0 ~ re { seen++ }
    END { if (started && seen != 1) printf "%s ", name }
  ' "$1")
  [ -z "$bad" ] || fail "$3: cases without exactly one verdict: $bad"

  # An engine that failed on EVERY case is a broken environment, not a finding.
  crashes=$(grep -cE "CRASH" "$1")
  [ "$crashes" -lt "$2" ] || fail "$3: failed on all $2 cases - that looks like a broken probe, not an engine"
}

# This run's columns. The comparison against the expectations reads these, not the saved ones: a
# column not tied to the run that produced it is not evidence.
RUN="$(mktemp -d)"
echo "columns from this run: $RUN"

column() { # <COLUMN NAME> <raw output> <block|line>
  python3 "$PROBE/normalize.py" "$2" "$3" "$1: column from run $(date +%Y-%m-%dT%H:%M)" \
    > "$RUN/$1.txt" 2>"$RUN/$1.err" || fail "$1: normalization did not yield a whole column: $(head -1 "$RUN/$1.err")"
}

echo
echo "### 2. the DataFusion side"
# Plans used to be copied into someone else's testdata and the probe appended to a tracked test
# file, then reverted in a trap. It is a standalone example now: the checkout is not modified at
# all, and the cases are read from this repository.
DF_EX="$DF/datafusion/substrait/examples/corpus_probe.rs"
[ -e "$DF_EX" ] && die "$DF_EX already exists in the DataFusion checkout - remove it yourself, not touching what is not mine"
mkdir -p "$(dirname "$DF_EX")"
cp "$PROBE/datafusion_corpus_probe.rs" "$DF_EX" || die "could not place the probe at $DF_EX"
# Cleanup removes the directories this script created too, and stops at the first one that is
# not empty: the whole point of placing an example instead of editing a tracked file is that
# the checkout is left exactly as it was found.
cleanup_df() {
  rm -f "$DF_EX"
  local d; d="$(dirname "$DF_EX")"
  while [ "$d" != "$DF" ] && [ "$d" != "/" ] && rmdir "$d" 2>/dev/null; do d="$(dirname "$d")"; done
}
DF_OUT=$(mktemp)
( cd "$DF" && SUBSTRAIT_CORPUS_DIR="$CASES" cargo run -q -p datafusion-substrait \
    --example corpus_probe 2>&1 ) > "$DF_OUT"
DF_RC=$?
grep -E "^#####|^DATAFUSION|^error" "$DF_OUT"
[ "$DF_RC" -eq 0 ] || fail "cargo run returned $DF_RC"
check_blocks "$DF_OUT" "$N_JSON" "DataFusion" "^DATAFUSION (ACCEPTED|REJECTED)"
column DATAFUSION "$DF_OUT" block
cp "$DF_OUT" "$RUN/DATAFUSION.raw"
cleanup_df

run_probe() { # <name> <script> <verdict-regexp> <COLUMN NAME>
  local out; out=$(mktemp)
  bash "$2" "$CASES" > "$out" 2>&1
  local rc=$?
  cat "$out"
  [ "$rc" -eq 0 ] || fail "$1: the runner returned $rc"
  check_blocks "$out" "$N_JSON" "$1" "$3"
  # 127 = no such command: the environment fell away, the engine did not crash.
  ! grep -q 'signal/exit 127' "$out" || fail "$1: exit 127 - the probe environment is missing"
  [ -n "${4:-}" ] && column "$4" "$out" block
  [ -n "${4:-}" ] && cp "$out" "$RUN/$4.raw"
  rm -f "$out"
}

echo; echo "### 3. the DuckDB side";       run_probe DuckDB       "$PROBE/duckdb_all.sh" "^DUCKDB (ACCEPTED|REJECTED|CRASH)" DUCKDB
echo; echo "### 4. the substrait-go side"; run_probe substrait-go "$PROBE/go_all.sh" "^SUBSTRAITGO (ACCEPTED|REJECTED|CRASH)" GO
echo; echo "### 5. the Acero side";        run_probe Acero        "$PROBE/acero_all.sh" "^ACERO (ACCEPTED|REJECTED|CRASH)" ACERO

# The participants below each run only if their environment is up: a missing environment is a
# skip with a line saying so, not a silent hole and not a failure of the whole run.
SKIPPED_PROBES=""
optional_probe() { # <name> <guard file> <command...>
  local name="$1" guard="$2"; shift 2
  if [ ! -e "$guard" ]; then
    echo "SKIPPED $name: no $guard (see probe/README.md)"
    SKIPPED_PROBES="$SKIPPED_PROBES $name"
    return 0
  fi
  "$@" || fail "$name: the probe returned a non-zero code"
}

# The same, with a column and a completeness check: the column name and format come first.
optional_column() { # <COLUMN NAME> <block|line> <name> <guard file> <command...>
  local col="$1" fmt="$2" name="$3" guard="$4"; shift 4
  if [ ! -e "$guard" ]; then
    echo "SKIPPED $name: no $guard (see probe/README.md)"
    SKIPPED_PROBES="$SKIPPED_PROBES $name"
    return 0
  fi
  local out; out=$(mktemp)
  "$@" > "$out" 2>&1
  local rc=$?
  cat "$out"
  [ "$rc" -eq 0 ] || fail "$name: the probe returned $rc"
  column "$col" "$out" "$fmt"
  rm -f "$out"
}

# The substrait-java column is taken by this run too, rather than read from the saved file: the
# comparison against the expectations has to check what this run got on this corpus.
JAVA_OUT=$(mktemp)
javac -nowarn -cp "$CP" -d "$GEN/out" "$PROBE/SchemaOf.java" || fail "javac SchemaOf"
java -cp "$GEN/out:$CP" SchemaOf $(ls "$CASES"/*.json | grep -v manifest) > "$JAVA_OUT" 2>/dev/null \
  || fail "SchemaOf returned a non-zero code"
column JAVA "$JAVA_OUT" line
rm -f "$JAVA_OUT"

echo; echo "### 6. the substrait-python side"
optional_column PYTHON line substrait-python "${SUBSTRAIT_PYTHON_ENV:-$SP/pysub}/bin/python" \
  bash "$PROBE/python_all.sh" "$ROOT/derived-schema-vt"

echo; echo "### 7. the substrait-validator side"
optional_column VALIDATOR block substrait-validator "${SUBSTRAIT_VALIDATOR_ENV:-$SP/val314}/bin/python" \
  bash "$PROBE/validator_all.sh" "$CASES"

echo; echo "### 8. the Isthmus/Calcite side (declared against derived, through the observer)"
optional_probe Isthmus "$SJ/isthmus/build/classes/java/main" \
  bash "$PROBE/isthmus_run.sh" ObserveOf "$CASES"/decimal_add_overflow.json
# The schema Calcite derives is a full column over the whole corpus, not three examples:
# relation-level divergences (the read mask, set-operation nullability) show up only there.
if [ -e "$SJ/isthmus/build/classes/java/main" ]; then
  ISTH_OUT=$(mktemp)
  bash "$PROBE/isthmus_run.sh" CalciteSchemaOf $(ls "$CASES"/*.json | grep -v manifest) \
    > "$ISTH_OUT" 2>&1 || fail "Isthmus: the probe returned a non-zero code"
  # The probe prints two lines per case (declared, then Calcite); the column is the second.
  python3 - "$ISTH_OUT" > "$RUN/ISTHMUS.raw" <<'PYEOF'
import re, sys
name = None
for line in open(sys.argv[1], encoding="utf-8"):
    m = re.match(r"^(\S+)\s+declared/POJO: (.*)$", line.rstrip())
    if m:
        name = m.group(1)
        print("##### %s" % name)
        if "PARSE FAILED" in m.group(2):
            print("ISTHMUS REJECTED %s" % m.group(2))
            name = None
    elif name and "Calcite:" in line:
        v = line.split("Calcite:", 1)[1].strip()
        print("ISTHMUS %s %s" % ("ACCEPTED" if v.startswith("[") else "REJECTED", v))
        name = None
PYEOF
  column ISTHMUS "$RUN/ISTHMUS.raw" block
  rm -f "$ISTH_OUT"
else
  echo "SKIPPED Isthmus schema: no $SJ/isthmus/build/classes/java/main"
  SKIPPED_PROBES="$SKIPPED_PROBES Isthmus-schema"
fi

echo; echo "### 9. the Spark side (needs JDK 17)"
optional_column SPARK line Spark "${JAVA17_HOME:-$(/usr/libexec/java_home -v 17 2>/dev/null || true)}/bin/java" \
  bash "$PROBE/spark_all.sh" "$CASES"

# expected.json is built here, before both checks. It used to be regenerated below, after the row
# check, so a change to the expectations was only caught by the next run.
python3 "$PROBE/expected.py" > "$ROOT/expected.json" || fail "could not build expected.json"

echo; echo "### 10. rows against the examples in the spec"
# The rows section of expected.json was not read at all before: eight expectations sat in the file
# and nothing checked them. Rows are the one part of the corpus that does not depend on the
# participant's type system.
for pair in "DUCKDB:DUCKDB" "DATAFUSION:DATAFUSION" "ACERO:ACERO"; do
  col="${pair%%:*}"; tag="${pair##*:}"
  if [ -f "$RUN/$col.raw" ]; then
    printf "%-12s " "$col"
    ROWS_OUT=$(mktemp)
    python3 "$PROBE/check_rows.py" "$RUN/$col.raw" "$tag" > "$ROWS_OUT" 2>&1
    ROWS_RC=$?
    tail -1 "$ROWS_OUT"
    # As with schemas: differing rows are a finding, a missing summary line is a broken check.
    if ! grep -q "^rows:" "$ROWS_OUT"; then
      fail "$col: the row check did not reach its summary (exit $ROWS_RC): $(tail -1 "$ROWS_OUT")"
    fi
    rm -f "$ROWS_OUT"
  else
    echo "SKIPPED rows for $col: this run produced no raw output"
  fi
done

echo; echo "### 10b. schemas against the independent expectations"
# THIS run's columns ($RUN) are compared, not the saved ones. Otherwise the outcome did not depend
# on what the sections above produced: a probe that died left the day-before-yesterday's
# measurement in the comparison.
for pair in "JAVA:java" "PYTHON:py" "VALIDATOR:py" "DATAFUSION:df" "DUCKDB:duckdb" "GO:go" \
            "ACERO:acero" "SPARK:spark" "ISTHMUS:calcite"; do
  col="${pair%%:*}"; f="${pair##*:}"
  if [ -f "$RUN/$col.txt" ]; then
    printf "%-12s " "$col"
    # The exit code is taken from the check itself, not from the tail at the end of a pipe: it used
    # to be lost there, and an incomplete column did not change the outcome of the run.
    CHK=$(mktemp)
    python3 "$PROBE/check_expected.py" "$RUN/$col.txt" "$f" > "$CHK" 2>&1
    CHK_RC=$?
    tail -1 "$CHK"
    # Differing from an expectation is a finding, not a harness failure, so a non-zero code is not
    # itself a failure. What tells them apart is the SUMMARY LINE: with no summary the check died
    # on an exception, and passing that over in silence is not allowed - any failure without the
    # words INCOMPLETE or "unparsed answer" used to slip through.
    if ! grep -q "^matched:" "$CHK"; then
      fail "$col: the check did not reach its summary (exit $CHK_RC): $(tail -1 "$CHK")"
    fi
    # Refusing every case but one is a broken environment, not a property of the participant: a
    # validator with a broken import used to give 78 "unsupported" and leave the outcome untouched.
    UNSUP=$(sed -n 's/.*unsupported by the participant: \([0-9]*\).*/\1/p' "$CHK" | tail -1)
    [ -z "$UNSUP" ] || [ "$UNSUP" -lt "$N_JSON" ] || fail "$col: refused all $N_JSON cases - that looks like a broken probe"
    grep -q "^INCOMPLETE" "$CHK" && fail "$col: the check reported an incomplete column"
    grep -q "unparsed answer" "$CHK" && fail "$col: the check could not parse some answers"
    rm -f "$CHK"
  else
    echo "SKIPPED $col: this run produced no column"
  fi
done

# The saved columns are replaced only when explicitly asked for - like the corpus.
if [ "${UPDATE_COLUMNS:-0}" = "1" ]; then
  for c in "$RUN"/*.txt; do cp "$c" "$ROOT/$(basename "$c")"; done
  echo "saved columns updated from this run (UPDATE_COLUMNS=1)"
fi

echo
DIRTY=$(git -C "$DF" status --porcelain --untracked-files=no | wc -l | tr -d " ")
echo "### 11. the DataFusion checkout after cleanup: $DIRTY changes"
[ "$DIRTY" -eq 0 ] || fail "the DataFusion checkout was left dirty"

echo
RAN=$(ls "$RUN"/*.txt 2>/dev/null | wc -l | tr -d " ")
echo "columns produced by this run: $RAN"
# A skipped participant is a hole in the measurement, not a detail: a run where half the probes never
# came up used to end in RESULT all the same. Allowed only under an explicit ALLOW_SKIPPED=1.
if [ -n "$SKIPPED_PROBES" ]; then
  echo "skipped (no environment):$SKIPPED_PROBES"
  [ "${ALLOW_SKIPPED:-0}" = "1" ] || fail "participants were skipped; for a knowingly partial run set ALLOW_SKIPPED=1"
fi
# Gluten lives in a cluster and this script does not run it. Saying so out loud is mandatory:
# otherwise "one command re-checks everything" reads as a claim about it too.
echo "outside this script: Gluten/Velox (run in a cluster; the GLUTEN.txt column is taken separately)"
if [ "$FAILED" -ne 0 ]; then echo "RESULT: HARNESS FAILED - do not trust the conclusions"; exit 1; fi
echo "RESULT: the harness ran to completion, $N_JSON cases, $RAN columns"
