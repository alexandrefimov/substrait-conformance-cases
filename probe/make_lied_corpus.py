"""Replace declared output types for the output-schema sensitivity experiment.

    python3 probe/make_lied_corpus.py <input dir> <output dir>

Every supported `outputType` is replaced, including boolean predicate types. An unchanged final
schema does not show whether the consumer checked an expression type absent from that schema.
"""
import json, os, sys

def lie(t):
    (kind, spec), = t.items()
    if kind == "decimal":
        return {"decimal": {"precision": 20, "scale": 2, "nullability": spec.get("nullability", "NULLABILITY_REQUIRED")}}
    if kind == "i64":
        return {"i32": {"nullability": spec.get("nullability", "NULLABILITY_REQUIRED")}}
    if kind == "i32":
        return {"i64": {"nullability": spec.get("nullability", "NULLABILITY_REQUIRED")}}
    if kind == "bool":
        return {"i32": {"nullability": spec.get("nullability", "NULLABILITY_REQUIRED")}}
    if kind == "struct":
        # A struct is swapped for a struct of the same arity, not for a scalar. A scalar changed the
        # number of fields in depth, the plan stopped agreeing with Plan.Root.names, and the
        # participant refused over the count of names - which the measurement then recorded as
        # "noticed the swapped type". phase_intermediate landed among the copied or among the caught
        # depending on which swap happened to be in the directory.
        inner = spec.get("types") or []
        lied = [lie(t) or t for t in inner]
        if all(l is t for l, t in zip(lied, inner)):
            return None
        out = dict(spec)
        out["types"] = lied
        return {"struct": out}
    return None

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
changed = []
for name in sorted(os.listdir(src)):
    if not name.endswith(".json") or "manifest" in name: continue
    d = json.load(open(os.path.join(src, name)))
    n = [0]
    def walk(o):
        if isinstance(o, dict):
            t = o.get("outputType")
            if isinstance(t, dict):
                new = lie(t)
                if new is not None:
                    o["outputType"] = new; n[0] += 1
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(d)
    if n[0]:
        json.dump(d, open(os.path.join(dst, name), "w"), indent=1)
        changed.append(name[:-5])
print("cases swapped:", len(changed))
print("\n".join("  " + c for c in changed))
