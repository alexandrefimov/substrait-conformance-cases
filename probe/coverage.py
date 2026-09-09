"""What the corpus covers, by relation, read out of the plans themselves.

    python3 probe/coverage.py            # the block the README carries
    python3 probe/coverage.py --json     # the same counts as data

The matrix says how nine implementations answer these cases. It says nothing about which parts of
the format the cases reach, and that is the first thing anyone deciding where a corpus belongs asks:
substrait#1164 proposes a two-tier coverage catalog, breadth first - every relation in algebra.proto
with at least one case. So breadth is counted here rather than described, from the plans, and the
README carries what this prints.

A count of one is worth reading twice. Three relations are in the corpus only as the carrier of
another behaviour - an emit mapping needs something to sit on - and a case that reaches a relation
incidentally is not a case that pins its derivation. The block names those rather than letting a
table of ones imply coverage that is not there.
"""
import io, json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# The oneof in `message Rel`, transcribed from substrait/algebra.proto at spec 0.102.0 - the version
# these plans declare, and the one substrait-java pins through substrait-packaging. Transcribed, so
# it can go stale: a plan using a relation absent from this list fails the run rather than being
# counted as something else, which is how a stale list announces itself.
RELATIONS = ["read", "filter", "fetch", "aggregate", "sort", "join", "lateralJoin", "project",
             "set", "extensionSingle", "extensionMulti", "extensionLeaf", "cross", "reference",
             "write", "ddl", "update", "hashJoin", "mergeJoin", "nestedLoopJoin", "window",
             "exchange", "expand", "topN"]

SPEC = "0.102.0"

# PlanRel's own oneof: what holds a relation rather than being one.
WRAPPERS = {"root", "rel"}

# A relation the corpus reaches only because another behaviour needed an operator to sit on. Named
# here rather than inferred from a count of one: `cross` and `top_n` also have one case each and are
# its subject, so the count cannot tell the two apart and a reader should not have to guess.
CARRIER = ["filter", "sort", "fetch"]

WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight",
         9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve", 13: "Thirteen", 14: "Fourteen"}


# The fields algebra.proto declares as holding a relation. The walk follows these from PlanRel down,
# rather than recognising a relation by its shape: an Expression cast is also a one-field message
# with an `input`, and a shape test counts it as a relation nobody has heard of. Following the
# fields instead means a name this file does not know is caught wherever it stands, leaf relations
# included.
REL_FIELDS = ("input", "inputs", "left", "right")


def relations_in(plan, seen):
    """Every relation kind in one plan, walking from PlanRel through the fields that hold a Rel."""
    found = set()

    def rel(node):
        if not isinstance(node, dict) or len(node) != 1:
            found.add("?malformed")
            return
        (kind,) = node
        seen.add(id(node))
        found.add(kind if kind in RELATIONS else "?" + kind)
        for field in REL_FIELDS:
            value = node[kind].get(field) if isinstance(node[kind], dict) else None
            for child in (value if isinstance(value, list) else [value] if value else []):
                rel(child)

    for plan_rel in plan.get("relations", []):
        if "rel" in plan_rel:
            rel(plan_rel["rel"])
        if "root" in plan_rel:
            rel(plan_rel["root"]["input"])
    return found


def unreached(node, seen):
    """Relations standing where the walk above does not go, which would be counted as absent."""
    missed = []
    if isinstance(node, dict):
        if len(node) == 1 and next(iter(node)) in RELATIONS and id(node) not in seen:
            missed.append(next(iter(node)))
        for value in node.values():
            missed += unreached(value, seen)
    elif isinstance(node, list):
        for value in node:
            missed += unreached(value, seen)
    return missed


def counts():
    cases = sorted(f for f in os.listdir(os.path.join(ROOT, "derived-schema"))
                   if f.endswith(".json") and f != "manifest.json")
    per = {r: 0 for r in RELATIONS}
    unknown, stranded, versions = set(), set(), set()
    for name in cases:
        plan = json.load(io.open(os.path.join(ROOT, "derived-schema", name), encoding="utf-8"))
        versions.add(plan.get("version", {}).get("minorNumber"))
        seen = set()
        for rel in relations_in(plan, seen):
            if rel.startswith("?"):
                unknown.add(rel[1:])
            else:
                per[rel] += 1
        stranded.update(unreached(plan, seen))
    if unknown:
        raise SystemExit("FAILED: %s: relations no entry in probe/coverage.py names - algebra.proto "
                         "has moved past the transcribed list" % ", ".join(sorted(unknown)))
    if stranded:
        raise SystemExit("FAILED: %s stands where this walk does not follow - REL_FIELDS in "
                         "probe/coverage.py is missing a field that holds a relation"
                         % ", ".join(sorted(stranded)))
    # The denominator is the relation list of one spec release. A corpus that has moved to another
    # would be counted against the wrong one, quietly.
    declared = int(SPEC.split(".")[1])
    if versions != {declared}:
        raise SystemExit("FAILED: probe/coverage.py counts against spec %s, the plans declare %s"
                         % (SPEC, ", ".join(str(v) for v in sorted(versions, key=str))))
    return len(cases), per


def snake(name):
    return re.sub(r"([a-z])([A-Z])", lambda m: m.group(1) + "_" + m.group(2).lower(), name)


def block():
    total, per = counts()
    covered = [(r, n) for r, n in per.items() if n]
    absent = [r for r, n in per.items() if not n]
    rows = ["| relation | cases | | relation | cases |", "| --- | ---: | --- | --- | ---: |"]
    half = (len(covered) + 1) // 2
    right_side = covered[half:] + [None] * half
    for left, right in zip(covered[:half], right_side):
        rows.append("| `%s` | %d |" % (snake(left[0]), left[1])
                    + (" | `%s` | %d |" % (snake(right[0]), right[1]) if right else " | | |"))
    carried = [r for r, _ in covered if r in CARRIER]
    names = ", ".join("`%s`" % snake(r) for r in carried[:-1])
    return "\n".join(
        ["<!-- coverage: written by probe/coverage.py, checked by probe/selfcheck.sh -->"]
        + rows
        + ["",
           "%s of the %d relations `algebra.proto` defines at spec %s appear in these %d plans; "
           "%s and `%s` only under an emit mapping, which needs something to sit on. No case "
           "reaches %s."
           % (WORDS.get(len(covered), len(covered)), len(per), SPEC, total,
              names, snake(carried[-1]),
              ", ".join("`%s`" % snake(r) for r in absent)),
           "<!-- /coverage -->"])


if __name__ == "__main__":
    if "--json" in sys.argv:
        total, per = counts()
        print(json.dumps({"cases": total, "relations": per, "spec": SPEC}, indent=1))
    else:
        print(block())
