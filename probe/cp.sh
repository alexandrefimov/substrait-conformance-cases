#!/bin/bash
# Prints the classpath of one substrait-java module, fetching it from Gradle when it is not
# cached yet.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> bash probe/cp.sh core|isthmus|spark
#
# core comes from gen/classpath.txt (written by gen/make_classpath.sh, which is where the
# reasoning about that classpath lives); isthmus and spark are resolved here and cached under
# the probe environment, because only these two probes need them.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}"
mkdir -p "$CACHE"
# A workstation points SUBSTRAIT_JAVA_DIR at a checkout it already has; a machine that has none gets
# the one probe/setup.sh clones at the pinned commit, the way the validator's is found. Without the
# fallback a column could only be retaken where substrait-java had been cloned by hand.
SJ="${SUBSTRAIT_JAVA_DIR:-$CACHE/substrait-java}"
[ -x "$SJ/gradlew" ] || {
  echo "not a substrait-java checkout: $SJ" >&2
  echo "set SUBSTRAIT_JAVA_DIR, or let probe/setup.sh clone one into the probe environment" >&2
  exit 1; }
export SUBSTRAIT_JAVA_DIR="$SJ"
case "$1" in
  core)
    # The generators write it into the repository by default; a replay puts it in the environment it
    # built, because a run that writes into the tree it is measuring is not measuring that tree.
    CP_FILE="${SUBSTRAIT_CLASSPATH:-$ROOT/gen/classpath.txt}"
    [ -s "$CP_FILE" ] || bash "$ROOT/gen/make_classpath.sh" "$CP_FILE" >&2
    cat "$CP_FILE"; exit 0 ;;
  isthmus) f="$CACHE/isthmus_cp.txt"; p=":isthmus"; t=printIsthmusCp ;;
  spark)   f="$CACHE/spark_cp.txt";  p=":spark:spark-3.5_2.12"; t=printSparkCp ;;
  *) echo "expected an argument: core|isthmus|spark" >&2; exit 2 ;;
esac
if [ ! -s "$f" ]; then
  init="$CACHE/cp_$1.gradle"
  # dependsOn the classpath itself, not just `classes`: :isthmus and :spark take :core through its
  # shaded jar, and asking for classes alone printed a classpath naming a jar that had never been
  # built. On a warm tree it was already there and everything worked; on a fresh checkout Isthmus
  # failed with "package io.substrait.plan does not exist" and Spark with an ANTLR 4.13 against 4.9
  # mismatch, because the relocation that shaded jar carries was missing too.
  cat > "$init" <<G
gradle.afterProject { pr ->
  if (pr.path == '$p') {
    pr.tasks.register('$t') {
      dependsOn(pr.sourceSets.main.runtimeClasspath)
      doLast { println "CPSTART"; println pr.sourceSets.main.runtimeClasspath.files.join(':'); println "CPEND" }
    }
  }
}
G
  (cd "$SJ" && ./gradlew -q --init-script "$init" "$p:$t") | awk '/CPSTART/{f=1;next}/CPEND/{f=0}f' > "$f"
fi
cat "$f"
