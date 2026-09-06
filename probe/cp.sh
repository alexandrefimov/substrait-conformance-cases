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
SJ="${SUBSTRAIT_JAVA_DIR:?set SUBSTRAIT_JAVA_DIR to a substrait-java checkout}"
CACHE="${PROBE_CACHE:-${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}}"
mkdir -p "$CACHE"
case "$1" in
  core)
    [ -s "$ROOT/gen/classpath.txt" ] || bash "$ROOT/gen/make_classpath.sh" >&2
    cat "$ROOT/gen/classpath.txt"; exit 0 ;;
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
