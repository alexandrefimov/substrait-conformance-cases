"""A corpus with the declared type swapped for a false one - the input to probe/lie_matrix.sh,
which measures who notices.

    python3 probe/make_lied_corpus.py <input dir> <output dir>

The swap is made only where the declaration would then contradict the function's formula:
arithmetic and aggregates. Boolean filter predicates are left alone - there anyone would catch the
disagreement structurally rather than by type.
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
