"""Rewrite the name a plan's function calls are declared under, three ways.

    python3 probe/make_unbound_corpus.py <input dir> <output dir> control|mismatch|signature|unknown

The declaration swap asks whether a consumer repeats the output type the plan
states. This asks a different question: whether it resolves the call at all.
Only `Plan.extensions[].extensionFunction.name` changes; the arguments, the
schema and the declared output type stay exactly as they were, so nothing here
can be refused for a shape the plan no longer has.

  control     the name becomes another function with the same signature and the
              same return - add for subtract, equal for not_equal, is_null for
              is_not_null and back. A refusal here is not about binding: it says
              the rewrite itself is what the participant objects to, and the
              other two columns cannot be read. multiply and divide have no
              partner that returns the same type, so their cases get no control
              and are left out of that corpus rather than given a wrong one.
  mismatch    the compound name keeps its short part and takes argument types that are declared
              under the same URN but are not the ones the call passes: add:i32_i32 becomes
              add:i8_i8 over i32 arguments. The key exists, so a participant that only checks for
              its presence accepts; one that checks the key against the call refuses. The
              alternative has to live in the same extension file, or the key would simply be absent
              and this would be the `unknown` column again, which is why only add:i32_i32, avg:i64
              and sum:i64 can carry it. sum is the one where the alternative returns what the
              original returns, so a refusal there is about the arguments and nothing else.
  signature   the compound name keeps its short part and takes argument types no
              impl declares: add:dec_dec becomes add:str_str. A consumer that
              resolves the short name against the actual arguments binds this
              anyway, which is an answer about how it resolves, not a refusal.
  unknown     the short name becomes one no extension file declares. A consumer
              that resolves names at all has to fail here; one that accepts is
              carrying the call through unbound.
"""
import json, os, sys

# equal and not_equal are a pair, but only away from a join key. Acero accepts only `equal` or
# `is_not_distinct_from` for a join key and the substrait-java Spark path has no conversion for
# not_equal at all, so swapping one there refuses for a reason that has nothing to do with binding -
# which is what a control exists to rule out. The rewrite is per declaration and a declaration is
# shared by every call that references it, so the exclusion is per case: a case whose swapped anchor
# is referenced from a join stays out of the control corpus.
# short name -> (suffix in the corpus, a suffix declared under the same URN that the call does not
# match). Nothing here crosses an extension file.
MISMATCH = {"add:i32_i32": "add:i8_i8", "avg:i64": "avg:i8", "sum:i64": "sum:i8"}

PARTNER = {"add": "subtract", "subtract": "add",
           "equal": "not_equal", "not_equal": "equal",
           "is_null": "is_not_null", "is_not_null": "is_null"}

JOIN_RELS = ("join", "hashJoin", "mergeJoin", "nestedLoopJoin")


def rewrite(name, mode):
    short, _, sig = name.partition(":")
    if mode == "control":
        other = PARTNER.get(short)
        return None if other is None else "%s:%s" % (other, sig)
    if mode == "mismatch":
        return MISMATCH.get(name)
    if mode == "signature":
        return "%s:%s" % (short, "_".join(["str"] * max(1, len(sig.split("_")))))
    if mode == "unknown":
        return "no_such_function:%s" % sig
    raise SystemExit("unknown mode: %s" % mode)


def join_anchors(node, inside=False, found=None):
    """Function anchors referenced from inside a join relation."""
    if found is None:
        found = set()
    if isinstance(node, dict):
        for k, v in node.items():
            here = inside or k in JOIN_RELS
            if here and k == "functionReference":
                found.add(v)
            join_anchors(v, here, found)
    elif isinstance(node, list):
        for v in node:
            join_anchors(v, inside, found)
    return found


def main():
    src, dst, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(dst, exist_ok=True)
    written = skipped = 0
    for f in sorted(os.listdir(src)):
        if not f.endswith(".json") or f == "manifest.json":
            continue
        plan = json.load(open(os.path.join(src, f), encoding="utf-8"))
        decls = [e["extensionFunction"] for e in plan.get("extensions", [])
                 if "extensionFunction" in e]
        if not decls:
            continue
        new = [rewrite(d["name"], mode) for d in decls]
        if any(n is None for n in new):
            skipped += 1          # no partner: a control that changed meaning would not be one
            continue
        if mode == "control" and any(d.get("functionAnchor") in join_anchors(plan)
                                     for d in decls):
            skipped += 1
            continue
        for d, n in zip(decls, new):
            d["name"] = n
        json.dump(plan, open(os.path.join(dst, f), "w", encoding="utf-8"), indent=1)
        written += 1
    print("%s: %d cases written, %d left out for want of a partner" % (mode, written, skipped))


if __name__ == "__main__":
    main()
