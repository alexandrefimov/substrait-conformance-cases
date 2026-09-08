# Turning a probe's raw output into a column: the revision it was taken against, and the check that
# nothing fell out of it on the way. Sourced by probe/reverify.sh and probe/replay_column.sh.
#
# It is a file rather than two copies because both scripts need the same two answers about the same
# nine participants, and a second copy of "which command reports substrait-python's version" is how
# the two come to report different versions of the same thing.
#
# What the caller owes it: versions.env sourced, SP pointing at the probe environment, and a fail()
# of its own. rev_of also reads SJ and DF for the participants that live in a checkout, and says so
# rather than guessing when they are not set.

# The revision a column was taken against, written into the column itself. Without it a column taken
# elsewhere cannot be read: apt and pip give whatever is current there, so a difference from the
# saved column could be a defect, a platform, or simply another version of the participant, and the
# file would not say which. Anything that cannot be determined says so rather than guessing.
rev_of() { # <COLUMN NAME>
  local v=""
  case "$1" in
    JAVA|ISTHMUS)  v="substrait-java $(git -C "${SJ:-/nonexistent}" rev-parse --short HEAD 2>/dev/null)" ;;
    DATAFUSION)    v="datafusion $(git -C "${DF:-/nonexistent}" rev-parse --short HEAD 2>/dev/null)" ;;
    DUCKDB)        v="duckdb $("$SP/venv/bin/python" -c 'import duckdb;print(duckdb.__version__)' 2>/dev/null)" ;;
    ACERO)         v="pyarrow $("$SP/venv/bin/python" -c 'import pyarrow;print(pyarrow.__version__)' 2>/dev/null)" ;;
    # substrait-python and substrait-validator carry no __version__; the distribution metadata does.
    PYTHON)        v="substrait $("${SUBSTRAIT_PYTHON_ENV:-$SP/pysub}/bin/python" -c 'import importlib.metadata as m;print(m.version("substrait"))' 2>/dev/null)" ;;
    # The commit that was built, read out of the checkout, rather than the ref that was asked for:
    # the drift run asks for origin/main, and "at origin/main" is not a revision anyone can return
    # to. --short=7 rather than --short, so the length is the file's and not the repository's.
    VALIDATOR)     local at
                   at="$(git -C "$SP/substrait-validator" rev-parse --short=7 HEAD 2>/dev/null)"
                   v="substrait-validator $("${SUBSTRAIT_VALIDATOR_ENV:-$SP/val}/bin/python" -c 'import importlib.metadata as m;print(m.version("substrait-validator"))' 2>/dev/null) at ${at:-${SUBSTRAIT_VALIDATOR_COMMIT:-}}" ;;
    GO)            v="$(grep -m1 -o 'substrait-go/v[0-9]* v[0-9a-z.+-]*' "$SP/gosub9/go.mod" 2>/dev/null)" ;;
    # Spark's classpath is resolved when its probe runs, so before that there is nothing to read it
    # from and the pinned value is reported instead, said to be pinned. Reading the jar unconditionally
    # printed a version here only because a previous run had left the cache behind.
    SPARK)         local cp_file="${SPARK_CP:-$SP/spark_cp.txt}"
                   if [ -s "$cp_file" ]; then
                     v="spark $(basename "$(tr ':' '\n' < "$cp_file" | grep -m1 -E 'spark-core_[0-9.]+-[0-9.]+\.jar')" 2>/dev/null | sed 's/.*-\([0-9][0-9.]*\)\.jar/\1/')"
                   else
                     v="spark ${SPARK_35:-} as pinned, not yet resolved"
                   fi ;;
  esac
  case "$v" in ""|*" "|*"  "*) echo "revision unknown" ;; *) echo "$v" ;; esac
}

# Every ##### block must carry a verdict. Counting blocks is not enough: a block without a
# verdict is a case silently lost.
check_blocks() { # <file> <expected> <name> <verdict-regexp, empty for a participant that prints more than one>
  local got crashes bad
  got=$(grep -c '^#####' "$1")
  [ "$got" -eq "$2" ] || fail "$3: $got blocks instead of $2 - the run is incomplete"

  # The validator prints a schema AND diagnostics for one case, so "exactly one verdict" is
  # unreachable for it by design. Resolving those is normalize.py's job - it fails a column whose
  # case has no verdict or contradictory ones - and an empty regexp here says so out loud rather
  # than leaving the caller to skip this function and lose the two checks around it.
  if [ -z "$4" ]; then
    crashes=$(grep -cE "CRASH" "$1")
    [ "$crashes" -lt "$2" ] || fail "$3: failed on all $2 cases - that looks like a broken probe, not an engine"
    return 0
  fi

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

# A column's answers without its header. The header names the day the column was taken and the
# revision it was taken against, so two runs never agree on it, and comparing it would be comparing
# clocks. Sorted, because a runner's file order is the shell's, not the corpus's.
column_body() { sed '1,/^$/d' "$1" | grep -v '^$' | sort; }
