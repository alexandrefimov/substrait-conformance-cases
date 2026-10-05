"""Checks every committed producer plan against the specification, and writes or compares the columns.

    python3 producers/check.py              # compare results/producers/*.txt with a fresh check
    python3 producers/check.py --write      # rewrite them
    python3 producers/check.py --print P    # one producer's column on stdout
    SUBSTRAIT_DIR=<checkout> python3 producers/check.py --derive   # rewrite producers/DERIVED.txt

The deriver reads the extension files out of a Substrait checkout, so what it derives for these
plans is saved in producers/DERIVED.txt, as deriver/DERIVED.txt is for the corpus, and --derive is
the one mode that needs the checkout. The others need python3 alone and read the saved derivations,
so probe/selfcheck.sh runs them without any producer or checkout; a plan whose calls the saved file
does not cover, or covers under another name, fails the check rather than being compared stale.

Two things are checked, each against a sentence of the specification at v0.102.0:

P1  Every function call's declared `output_type` against the return type deriver/calls.py derives
    for it from the extension that declares the function. The deriver reads no declared type; the
    comparison is made here. A call with no `output_type` is `missing`, whatever it binds to. A call
    the deriver finds no impl for is `unbound`; one it has no rule for is `declined` and not scored.
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

from deriver import type_model as types  # noqa: E402

PLANS = os.path.join(HERE, "plans")
DERIVED = os.path.join(HERE, "DERIVED.txt")
RESULTS = os.path.join(ROOT, "results", "producers")
QUERIES = [l.split("\t")[0] for l in open(os.path.join(HERE, "queries.tsv"))
           if l.strip() and not l.startswith("#")]


def pins():
    """The literal version assignments used by the probe scripts."""
    values = {}
    for line in open(os.path.join(ROOT, "probe", "versions.env")):
        line = line.split("#", 1)[0].strip()
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value.strip()
    return values


def check_pins():
    v = pins()
    expected = {
        "duckdb": "duckdb %s %s" % (v["DUCKDB_VERSION"], v["DUCKDB_SUBSTRAIT_EXTENSION"]),
        "datafusion": "datafusion <version> %s" % v["DATAFUSION_COMMIT"],
        "isthmus": "isthmus, substrait-java %s" % v["SUBSTRAIT_JAVA_COMMIT"],
        "spark35": "spark %s, substrait-java %s" % (v["SPARK_35"], v["SUBSTRAIT_JAVA_COMMIT"]),
        "spark40": "spark %s, substrait-java %s" % (v["SPARK_40"], v["SUBSTRAIT_JAVA_COMMIT"]),
    }
    for producer, want in expected.items():
        path = os.path.join(PLANS, producer, "PRODUCER.txt")
        got = open(path).read().strip() if os.path.exists(path) else "missing"
        # DataFusion's package version is descriptive; its revision is the pin.
        matches = (re.fullmatch(r"datafusion \S+ " + re.escape(v["DATAFUSION_COMMIT"]), got)
                   if producer == "datafusion" else got == want)
        if not matches:
            raise SystemExit("FAILED producer plans match their pins: %s was taken at %r, "
                             "expected %r; retake its plans" % (producer, got, want))


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


def plans():
    """(producer, query, path of the .json or .err) for every committed answer, in column order."""
    out = []
    for p in sorted(x for x in os.listdir(PLANS) if os.path.isdir(os.path.join(PLANS, x))):
        for q in QUERIES:
            for ext in (".json", ".err"):
                f = os.path.join(PLANS, p, q + ext)
                if os.path.exists(f):
                    out.append((p, q, f))
    return out


def derive_all():
    """What the deriver makes of every committed plan, as the lines of producers/DERIVED.txt."""
    from deriver import calls, derive
    lines = ["# What deriver/ derives for each committed producer plan: the root schema, then one line",
             "# per function call. Written by `SUBSTRAIT_DIR=<checkout> python3 producers/check.py --derive`;",
             "# read by producers/check.py. Tab-separated: plan, root or call path, then the answer.",
             "#"]
    for pin in open(os.path.join(ROOT, "deriver", "spec.pins")):
        if not pin.startswith("#") and pin.strip():
            lines.append("#  " + pin.strip())
    for p, q, f in plans():
        if not f.endswith(".json"):
            continue
        doc, key = json.load(open(f)), "%s/%s" % (p, q)
        try:
            fields = derive.schema_of(doc)
            n = named_fields(fields)
            lines.append("\t".join([key, "root", "-" if n is None else str(n), types.render_schema(fields)]))
        except types.Unsupported as why:
            lines.append("\t".join([key, "root", "declined", str(why)]))
        for r in calls.derive_calls(doc):
            lines.append("\t".join([key, r["path"], r["name"], r["status"],
                                    r["type"] if r["status"] == "derived" else r["reason"]]))
    return "\n".join(lines) + "\n"


def saved():
    """producers/DERIVED.txt read back: {plan: {"root": [...], "calls": [(path, name, status, answer)]}}."""
    out = {}
    for line in open(DERIVED):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("\t")
        entry = out.setdefault(f[0], {"root": None, "calls": []})
        if f[1] == "root":
            entry["root"] = f[2:]
        else:
            entry["calls"].append(tuple(f[1:5]))
    return out


def covers(doc, entry):
    """Why the saved derivations do not describe this plan, or None when they do."""
    if entry is None:
        return "no saved derivation"
    for path, name, _, _ in entry["calls"]:
        try:
            call = at(doc, path)
        except (KeyError, IndexError, TypeError):
            return "a saved call path the plan does not have: %s" % path
        ref = call.get("functionReference", 0)
        declared = [e["extensionFunction"]["name"] for e in doc.get("extensions", [])
                    if "extensionFunction" in e and e["extensionFunction"].get("functionAnchor", 0) == ref]
        if declared != [name]:
            return "the call at %s is %s in the plan, %s in the saved derivation" % (path, declared, name)
    return None


def check_plan(doc, entry):
    """(summary, [detail lines]) for one plan and its saved derivation."""
    details = []
    differ = unbound = declined = missing = 0
    for path, name, status, answer in entry["calls"]:
        declared = at(doc, path).get("outputType")
        if not declared:
            # A call without an output_type fails on its own, whatever it binds to: algebra.proto
            # makes the field the call's statement of its type, and there is nothing to compare.
            missing += 1
            details.append("  %-24s no output_type" % name)
        try:
            shown = types.render_field(types.from_plan(declared)) if declared else "none"
        except types.Unsupported as why:
            shown = "unreadable (%s)" % why
        if status == "unbound":
            unbound += 1
            details.append("  %-24s unbound: %s" % (name, answer))
        elif status == "declined":
            declined += 1
        elif declared and shown != answer:
            differ += 1
            details.append("  %-24s declared %-14s derived %s" % (name, shown, answer))
    summary = "calls %d, differ %d, missing %d, unbound %d, declined %d" % (
        len(entry["calls"]), differ, missing, unbound, declined)

    roots = [x["root"] for x in doc.get("relations", []) if "root" in x]
    names = len(roots[0].get("names", [])) if roots else 0
    count = entry["root"][0]
    if count == "declined":
        summary += "; schema declined (%s)" % entry["root"][1]
    elif count == "-":
        summary += "; names not checked (list or map)"
    elif int(count) == names:
        summary += "; names ok"
    else:
        summary += "; names %d for %s named fields" % (names, count)
    return summary, details


class Stale(Exception):
    """producers/DERIVED.txt no longer describes the committed plans."""


def column(producer, derivations):
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
            doc = json.load(open(plan))
            entry = derivations.get("%s/%s" % (producer, q))
            why = covers(doc, entry)
            if why:
                raise Stale("%s/%s: %s" % (producer, q, why))
            summary, details = check_plan(doc, entry)
            if q in removed:
                summary += "; removed fields: %s" % ", ".join(removed[q])
            out.append("%-22s %s" % (q, summary))
            out += details
        else:
            out.append("%-22s MISSING" % q)
    return "\n".join(out) + "\n"


def main(argv):
    check_pins()
    if "--derive" in argv:
        open(DERIVED, "w").write(derive_all())
        print("wrote %s" % os.path.relpath(DERIVED, ROOT))
        return 0
    producers = sorted(p for p in os.listdir(PLANS) if os.path.isdir(os.path.join(PLANS, p)))
    derivations = saved()
    plans_now = {"%s/%s" % (p, q) for p, q, f in plans() if f.endswith(".json")}
    extra = sorted(set(derivations) - plans_now)
    try:
        if extra:
            raise Stale("saved derivations for plans that are not committed: %s" % ", ".join(extra[:3]))
        if argv[1:2] == ["--print"]:
            sys.stdout.write(column(argv[2], derivations))
            return 0
        stale = []
        for p in producers:
            text, path = column(p, derivations), os.path.join(RESULTS, p.upper() + ".txt")
            if "--write" in argv:
                os.makedirs(RESULTS, exist_ok=True)
                open(path, "w").write(text)
            elif not os.path.exists(path) or open(path).read() != text:
                stale.append(os.path.relpath(path, ROOT))
    except Stale as why:
        print("FAILED producer derivations cover their plans: %s; rerun "
              "SUBSTRAIT_DIR=<checkout> python3 producers/check.py --derive" % why)
        return 1
    if stale:
        print("FAILED producer columns match their plans: %s differs from a fresh check; "
              "rerun python3 producers/check.py --write and read the diff" % ", ".join(stale))
        return 1
    print("ok      producer columns match their plans and derivations (%d producers)" % len(producers))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
