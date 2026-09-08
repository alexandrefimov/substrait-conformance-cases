#!/bin/bash
# Runs every case through Isthmus: the schema Calcite derives once the plan has been converted.
#
#   SUBSTRAIT_JAVA_DIR=<checkout> bash probe/isthmus_all.sh [corpus]
#
# CalciteSchemaOf prints two lines per case - what the plan declares, then what Calcite derives -
# and the column is the second. Turning that into blocks lives here rather than in the caller, so
# the run that takes this column and the run that replays it read the output the same way.
set -o pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASES="${1:-$ROOT/derived-schema}"
D="$(cd "$(dirname "$0")" && pwd)"
bash "$D/isthmus_run.sh" CalciteSchemaOf $(ls "$CASES"/*.json | grep -v manifest) | python3 -c '
import re, sys

# A case whose plan Isthmus will not parse never reaches Calcite, so it has no second line: its
# verdict is printed from the first one and the name is cleared, or the next case would be given
# this one`s answer.
name = None
for line in sys.stdin:
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
'
