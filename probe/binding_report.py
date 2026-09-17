"""Read the corpora probe/binding_matrix.sh produced and say who binds what.

    python3 probe/binding_report.py <output directory>

Per participant and per rewrite: how many cases answer as they did on the original plan, and how
many are refused. The control column is read first - where it is not clean, the other two are not
reported, because a participant that objects to the rewrite itself has not been asked the question.
"""
import io, os, sys

NAMES = ["JAVA", "PYTHON", "VALIDATOR", "DUCKDB", "GO", "ACERO", "DATAFUSION", "ISTHMUS", "SPARK"]


def col(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in io.open(path, encoding="utf-8"):
        k, _, v = line.rstrip().partition(" ")
        if k and v.strip() and "/" not in k:
            d[k] = v.strip()
    return d


def refused(v):
    return v.startswith(("ERROR", "— ")) or v in ("", "—")


def main():
    out = sys.argv[1]
    modes = ("control", "mismatch", "signature", "unknown")
    print("%-12s" % "" + "".join("%-22s" % m for m in modes))
    print("%-12s" % "" + "".join("%-22s" % "same / refused / n" for _ in modes))
    for n in NAMES:
        orig = col("%s/%s.orig.txt" % (out, n))
        if not orig:
            print("%-12s no run" % n)
            continue
        row, clean = "%-12s" % n, True
        for mode in modes:
            c = col("%s/%s.%s.txt" % (out, n, mode))
            if not c:
                row += "%-22s" % "no run"
                continue
            shared = [k for k in c if k in orig]
            same = sum(1 for k in shared if c[k] == orig[k])
            ref = sum(1 for k in shared if refused(c[k]) and not refused(orig[k]))
            if mode == "control" and ref:
                clean = False
            cell = "%d / %d / %d" % (same, ref, len(shared))
            row += "%-22s" % (cell if (clean or mode == "control") else cell + " *")
        print(row + ("" if clean else "   * control not clean"))


if __name__ == "__main__":
    main()
