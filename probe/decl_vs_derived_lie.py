"""Establishes one of the validator's boundaries: does it derive the type, or repeat the declared one?

    <venv>/bin/python probe/decl_vs_derived_lie.py <case.json>

Takes a case, swaps every output_type for a knowingly false dec(20,2) and prints the answers to both
plans. If the answer follows the swap, there is no derivation, only an echo of the declaration. This
is how the first (mistaken) reading, "the validator agrees with us on dec(38,9)", was withdrawn.
"""
import copy, json, subprocess, sys, os

LIE = {"decimal": {"precision": 20, "scale": 2, "nullability": "NULLABILITY_REQUIRED"}}
src = sys.argv[1]
plan = json.load(open(src))

def walk(o, fn):
    if isinstance(o, dict):
        fn(o)
        for v in o.values(): walk(v, fn)
    elif isinstance(o, list):
        for v in o: walk(v, fn)

lied = copy.deepcopy(plan)
n = [0]
def swap(o):
    if "outputType" in o:
        o["outputType"] = LIE; n[0] += 1
walk(lied, swap)
if not n[0]:
    print("this case has no output_type - nothing to check"); sys.exit(0)
out = os.path.join(os.path.dirname(src) or ".", ".lied.json")
json.dump(lied, open(out, "w"))
probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validator_one.py")
for label, path in (("as it is", src), ("swapped to dec(20,2)", out)):
    r = subprocess.run([sys.executable, probe, path], capture_output=True, text=True)
    print("%-24s %s" % (label, r.stdout.strip().splitlines()[0] if r.stdout.strip() else "—"))
os.remove(out)
