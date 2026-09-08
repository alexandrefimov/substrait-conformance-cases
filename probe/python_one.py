import sys, json
from google.protobuf import json_format
from substrait.plan_pb2 import Plan
from substrait.type_inference import infer_plan_schema
from substrait.extension_registry import ExtensionRegistry

REG = ExtensionRegistry()
SIMPLE = {"bool":"bool","i8":"i8","i16":"i16","i32":"i32","i64":"i64","fp32":"fp32","fp64":"fp64",
          "string":"str","binary":"bin","date":"date"}
def one(t):
    k = t.WhichOneof("kind"); f = getattr(t, k)
    n = "?" if f.nullability == 1 else ""   # NULLABILITY_NULLABLE = 1
    if k == "decimal": return "dec(%d,%d)%s" % (f.precision, f.scale, n)
    if k == "varchar": return "vchar(%d)%s" % (f.length, n)
    if k == "fixed_char": return "fchar(%d)%s" % (f.length, n)
    if k == "fixed_binary": return "fbin(%d)%s" % (f.length, n)
    if k == "precision_timestamp": return "precision_timestamp(%d)%s" % (f.precision, n)
    if k == "struct": return "[%s]%s" % (", ".join(one(x) for x in f.types), n)
    return SIMPLE.get(k, k) + n

for path in sys.argv[1:]:
    name = path.split("/")[-1].replace(".json", "")
    try:
        plan = json_format.Parse(open(path).read(), Plan())
    except Exception as e:
        print("%-46s ERROR: LOAD: %s" % (name, str(e).replace("\n"," ")[:80])); continue
    try:
        ns = infer_plan_schema(plan, registry=REG)
        names, types = list(ns.names), list(ns.struct.types)
        cols = ", ".join("%s:%s" % (names[i] if i < len(names) else "?", one(t))
                         for i, t in enumerate(types))
        flag = "" if len(names) == len(types) else "  !! names %d, types %d" % (len(names), len(types))
        print("%-46s [%s]%s" % (name, cols, flag))
    except Exception as e:
        print("%-46s ERROR: %s: %s" % (name, type(e).__name__, str(e).replace("\n"," ")[:90]))
