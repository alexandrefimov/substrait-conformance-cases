#!/bin/bash
# Writes gen/classpath.txt: the classpath the case generators and the substrait-java probes
# compile and run against. It is generated rather than checked in, because every entry is an
# absolute path into a particular machine's checkout and Gradle cache.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> bash gen/make_classpath.sh [output file]
#
# :core's own runtime classpath is not enough; gen/cp.init.gradle explains which extras are
# added and why they are resolved the way they are.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP="${SUBSTRAIT_PROBE_ENV:-$ROOT/.probe-env}"
# The checkout probe/setup.sh clones when the caller has none of its own, as for the validator.
SJ="${SUBSTRAIT_JAVA_DIR:-$SP/substrait-java}"
[ -x "$SJ/gradlew" ] || { echo "not a substrait-java checkout: $SJ" >&2; exit 1; }
OUT="${1:-${SUBSTRAIT_CLASSPATH:-$ROOT/gen/classpath.txt}}"

CP_RAW="$( cd "$SJ" && ./gradlew -I "$ROOT/gen/cp.init.gradle" -q \
             :core:classes :core:printCoreCp )" \
CP_OUT="$OUT" python3 - <<'PY'
import os, sys

raw = os.environ["CP_RAW"].splitlines()
def section(begin, end):
    return raw[raw.index(begin) + 1:raw.index(end)][0].split(":")
main, extra = section("MAINCP", "EXTRACP"), section("EXTRACP", "CPEND")

cp, seen = list(main), set(main)
for entry in extra:
    if entry and entry not in seen:
        cp.append(entry)
        seen.add(entry)

missing = [e for e in cp if not os.path.exists(e)]
if missing:
    sys.exit("classpath entry does not exist: %s" % missing[0])

out = os.environ["CP_OUT"]
with open(out, "w", encoding="utf-8") as f:
    f.write(":".join(cp) + "\n")
print("%s: %d entries" % (out, len(cp)))
PY
