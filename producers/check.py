"""Checks every committed producer plan against the specification, and writes or compares the columns.

    python3 producers/check.py              # compare results/producers/*.txt with a fresh check
    python3 producers/check.py --write      # rewrite them
    python3 producers/check.py --print P    # one producer's column on stdout

Needs python3 and nothing else: it reads the committed .json plans and the deriver's saved rules, so
probe/selfcheck.sh can run it without any producer installed.

Two things are checked, each against a sentence of the specification at v0.102.0:

P1  Every function call's declared `output_type` against the return type deriver/calls.py derives
    for it from the extension that declares the function. The deriver reads no declared type; the
    comparison is made here. A call the deriver finds no impl for is `unbound`; one it has no rule
    for is `declined` and not scored.
P2  "Field names in depth-first order. The number of names must match the number of named fields
    in the output type." (algebra.proto, RelRoot.names). The output type is the deriver's.

A producer that refused a query has the first line of its refusal as the answer. Fields a plan
carries that the release no longer defines are listed after the summary and not scored.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from deriver import calls, derive, type_model as types  # noqa: E402

PLANS = os.path.join(HERE, "plans")
RESULTS = os.path.join(ROOT, "results", "producers")
QUERIES = [l.split("\t")[0] for l in open(os.path.join(HERE, "queries.tsv"))
           if l.strip() and not l.startswith("#")]


def at(doc, path):
    """The message a deriver path such as `relations[0].root.input.project.expressions[1]` names."""
    node = doc
    for name, index in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", path):
        node = node[name] if name else node[int(index)]
    return node


def named_fields(fields):
    """How many names a schema takes, depth first; None when a list or map is in the way."""
    n = 0
    for f in fields:
        if f.name in ("list", "map"):
            return None
        n += 1
        if f.name == "struct":
            inner = named_fields(f.params)
            if inner is None:
                return None
            n += inner
    return n


def check_plan(doc):
    """(summary, [detail lines]) for one plan."""
    details = []
    records = calls.derive_calls(doc)
    differ = unbound = declined = 0
    for r in records:
        call = at(doc, r["path"])
        declared = call.get("outputType")
        try:
            shown = types.render_field(types.from_plan(declared)) if declared else "none"
        except types.Unsupported as why:
            shown = "unreadable (%s)" % why
        if r["status"] == "unbound":
            unbound += 1
            details.append("  %-24s unbound: %s" % (r["name"], r["reason"]))
        elif r["status"] == "declined":
            declined += 1
        elif shown != r["type"]:
            differ += 1
            details.append("  %-24s declared %-14s derived %s" % (r["name"], shown, r["type"]))
    summary = "calls %d, differ %d, unbound %d, declined %d" % (len(records), differ, unbound, declined)

    roots = [x["root"] for x in doc.get("relations", []) if "root" in x]
    try:
        n = named_fields(derive.schema_of(doc))
        names = len(roots[0].get("names", [])) if roots else 0
        if n is None:
            summary += "; names not checked (list or map)"
        elif n == names:
            summary += "; names ok"
        else:
            summary += "; names %d for %d named fields" % (names, n)
    except types.Unsupported as why:
        summary += "; schema declined (%s)" % why
    return summary, details


def column(producer):
    d = os.path.join(PLANS, producer)
    header = open(os.path.join(d, "PRODUCER.txt")).read().strip()
    # Fields the release the corpus targets no longer has, written by producers/sync_plans.py: an
    # observation about the producer, not scored, since a plan may declare an older release.
    removed = {}
    if os.path.exists(os.path.join(d, "UNKNOWN.txt")):
        for line in open(os.path.join(d, "UNKNOWN.txt")):
            q, field = line.strip().split(": ")
            removed.setdefault(q, []).append(field)
    out = ["%s: plans from %s, checked against the specification at v0.102.0" % (producer.upper(), header), ""]
    for q in QUERIES:
        err, plan = os.path.join(d, q + ".err"), os.path.join(d, q + ".json")
        if os.path.exists(err):
            out.append("%-22s REFUSED: %s" % (q, open(err).read().strip()))
        elif os.path.exists(plan):
            summary, details = check_plan(json.load(open(plan)))
            if q in removed:
                summary += "; removed fields: %s" % ", ".join(removed[q])
            out.append("%-22s %s" % (q, summary))
            out += details
        else:
            out.append("%-22s MISSING" % q)
    return "\n".join(out) + "\n"


def main(argv):
    producers = sorted(p for p in os.listdir(PLANS) if os.path.isdir(os.path.join(PLANS, p)))
    if argv[1:2] == ["--print"]:
        sys.stdout.write(column(argv[2]))
        return 0
    stale = []
    for p in producers:
        text, path = column(p), os.path.join(RESULTS, p.upper() + ".txt")
        if "--write" in argv:
            os.makedirs(RESULTS, exist_ok=True)
            open(path, "w").write(text)
        elif not os.path.exists(path) or open(path).read() != text:
            stale.append(os.path.relpath(path, ROOT))
    if stale:
        print("FAILED producer columns match their plans: %s differs from a fresh check; "
              "rerun python3 producers/check.py --write and read the diff" % ", ".join(stale))
        return 1
    print("ok      producer columns match their plans (%d producers)" % len(producers))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
