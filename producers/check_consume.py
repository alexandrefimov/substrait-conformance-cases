"""What each consumer makes of each producer's plan, against the schema the deriver gives it.

    python3 producers/check_consume.py            # compare results/producers/CONSUME.txt
    python3 producers/check_consume.py --write    # rewrite it

Reads the consumer columns producers/consume.sh wrote into results/producers/consume/ and the root
schemas in producers/DERIVED.txt, with the answer parsers of probe/check_expected.py, so a consumer
is read here exactly as it is read in the main corpus. One row per committed plan, one letter per
consumer:

  =  the consumer derived the schema the deriver gives
  x  it derived another; the pair is listed under the matrix
  E  it refused the plan or ended on it (the consumer's column has the message)
  a  it accepted a plan whose schema the deriver declines, so there is nothing to compare with
  ?  its answer could not be parsed

DuckDB's answers are compared without nullability, as in the main corpus: its logical types carry
none.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from deriver.check import parse_schema  # noqa: E402

src = io.open(os.path.join(ROOT, "probe/check_expected.py"), encoding="utf-8").read()
P = {"__file__": os.path.join(ROOT, "probe/check_expected.py")}
exec(src[:src.index("# --- the command line starts here ---")], P)

CONSUMERS = [("PYTHON", "parse_py"), ("GO", "parse_go"), ("VALIDATOR", "parse_py"), ("JAVA", "parse_java"),
             ("ISTHMUS", "parse_calcite"), ("SPARK", "parse_spark"), ("DUCKDB", "parse_duckdb"),
             ("DATAFUSION", "parse_df"), ("ACERO", "parse_acero")]
TYPES_ONLY = {"DUCKDB"}
CONSUME = os.path.join(ROOT, "results", "producers", "consume")
OUT = os.path.join(ROOT, "results", "producers", "CONSUME.txt")


def roots():
    """{'<producer>__<query>': schema or None} from producers/DERIVED.txt."""
    out = {}
    for line in open(os.path.join(HERE, "DERIVED.txt")):
        f = line.rstrip("\n").split("\t")
        if line.startswith("#") or len(f) < 4 or f[1] != "root":
            continue
        out[f[0].replace("/", "__")] = None if f[2] == "declined" else parse_schema(f[3])
    return out


def column(name):
    """{case: answer} of one consumer column, without its header."""
    answers, body = {}, False
    for line in open(os.path.join(CONSUME, name + ".txt"), encoding="utf-8"):
        line = line.rstrip("\n")
        if not body:
            body = not line
            continue
        if line:
            case, _, answer = line.partition(" ")
            answers[case] = answer.strip()
    return answers


def render(schema):
    return "[%s]" % ", ".join(t + ("?" if n else "") if n is not None else t for t, n in schema)


def build():
    want = roots()
    cols = {n: column(n) for n, _ in CONSUMERS if os.path.exists(os.path.join(CONSUME, n + ".txt"))}
    names = [n for n, _ in CONSUMERS if n in cols]
    missing = sorted(set(want) - set.intersection(*(set(c) for c in cols.values()))) if cols else sorted(want)
    if missing:
        raise SystemExit("FAILED consumer columns cover the producer plans: no answer for %s" % ", ".join(missing[:4]))
    rows, details, totals = [], [], {n: {} for n in names}
    for case in sorted(want):
        cells = ""
        for n, parser in CONSUMERS:
            if n not in cols:
                continue
            answer = cols[n][case]
            if answer in ("", "—") or answer.startswith(("ERROR", "— ")):
                c = "E"
            elif want[case] is None:
                c = "a"
            else:
                got = P[parser](answer)
                exp = want[case]
                if got is not None and n in TYPES_ONLY:
                    got, exp = [[t, None] for t, _ in got], [[t, None] for t, _ in exp]
                if got is None:
                    c = "?"
                elif got == exp:
                    c = "="
                else:
                    c = "x"
                    details.append("  %-30s %-10s derived %s, got %s" % (case, n, render(exp), render(got)))
            totals[n][c] = totals[n].get(c, 0) + 1
            cells += c
        rows.append("%-34s %s" % (case, "  ".join(cells)))
    head = ["CONSUME: each committed producer plan through each consumer, against the deriver's schema",
            "", "%-34s %s" % ("plan", " ".join(n[:2] for n in names))]
    tally = ["", "per consumer: = derived schema, x another schema, E refused, a no schema to compare, ? unparsed"]
    for n in names:
        tally.append("  %-10s %s" % (n, "  ".join("%s %d" % (k, totals[n].get(k, 0)) for k in "=xEa?")))
    return "\n".join(head + rows + tally + ["", "where a consumer derived another schema:"] + details) + "\n"


def main(argv):
    text = build()
    if "--write" in argv:
        open(OUT, "w").write(text)
        print("wrote %s" % os.path.relpath(OUT, ROOT))
        return 0
    if not os.path.exists(OUT) or open(OUT).read() != text:
        print("FAILED the consumer matrix matches the consumer columns: results/producers/CONSUME.txt "
              "differs from them; rerun python3 producers/check_consume.py --write")
        return 1
    print("ok      the consumer matrix matches the consumer columns")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
