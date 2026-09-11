#!/bin/bash
# Runs one participant over every committed bundle and pipes the answers into a column.
#
#     bash probe/relations/drive.sh <NAME> <revision> <command...>
#
# The command is invoked once per bundle with the bundle path appended, and prints
# "<case id><TAB><answer>" for it.
#
# One process per case, because a participant may take the process down rather than return an
# error: DuckDB's substrait extension segfaults on four of the eight set operations at 1.5.5, and
# substrait-go panics on some plans. A dead process prints nothing that says which case it was, so
# the bundle-to-id map is read from the extract before the loop starts - an absent case is the one
# thing a column must never contain, and a driver that iterated over whatever answers came back
# would lose exactly the cases worth reporting.
#
# A file of its own rather than a copy in each participant's script: every one of them needs the
# same handling of the same cases, and a second copy of "what to write when the process dies" is how
# two columns come to record the same event differently.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="$1"
REV="$2"
shift 2

ids="$(mktemp)"
trap 'rm -f "$ids"' EXIT
python3 - "$ROOT" > "$ids" <<'PYEOF'
import json, os, sys
root = sys.argv[1]
base = os.path.join(root, "tests", "relations", "bundles")
with open(os.path.join(root, "results", "relations", "expected.json"), encoding="utf-8") as fh:
    for case in json.load(fh)["cases"]:
        print("%s\t%s" % (os.path.join(base, case["bundle"]), case["id"]))
PYEOF

# Sorted by path so two runs' raw output is diffable; column.py puts the cases into the corpus's
# order afterwards.
while IFS=$'\t' read -r bundle id; do
  out="$("$@" "$bundle" 2>/dev/null)"
  rc=$?
  if [ $rc -ne 0 ] || [ -z "$out" ]; then
    printf '%s\tCRASH: the probe process died, exit %d\n' "$id" "$rc"
  else
    printf '%s\n' "$out"
  fi
done < <(sort "$ids") | python3 "$ROOT/probe/relations/column.py" "$NAME" "$REV"
