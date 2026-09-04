"""Collects the setdata_* results out of a saved reverify.sh log and compares them with the spec."""
import re, sys

SPEC = {
    "minus_primary": [4],
    "minus_primary_all": [2, 3, 3],
    "minus_multiset": [3, 4],
    "intersection_primary": [1, 2, 3],
    "intersection_multiset": [3],
    "intersection_multiset_all": [2, 3, 3],
    "union_distinct": [1, 2, 3, 4, 5, 6],
    "union_all": [1, 1, 2, 2, 2, 3, 3, 3, 3, 4, 5, 6],
}

sect, case, res = None, None, {}
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.rstrip("\n")
    m = re.match(r"^### \d+\. the (\S+) side", line)
    if m:
        sect = m.group(1); continue
    m = re.match(r"^##### (\S+)", line)
    if m:
        case = m.group(1); continue
    m = re.match(r"^(\w+) (ROWS|REJECTED|CRASH)\s*(.*)$", line)
    if m and case and case.startswith("setdata_"):
        eng, kind, val = m.groups()
        res.setdefault(case[8:], {}).setdefault(eng, (kind, val.strip()))

print("%-26s %-30s %-30s %s" % ("operation", "spec", "DataFusion", "DuckDB"))
print("-" * 120)
for op, want in SPEC.items():
    r = res.get(op, {})
    def cell(e):
        k, v = r.get(e, ("none", ""))
        if k == "ROWS":
            got = [int(x) for x in re.findall(r"-?\d+", v)]
            return ("%s %s" % (got, "OK" if got == sorted(want) else "<<< WRONG"))
        return "- " + (v.split(":")[0][:24] if v else k)
    print("%-26s %-30s %-30s %s" % (op, sorted(want), cell("DATAFUSION"), cell("DUCKDB")))
