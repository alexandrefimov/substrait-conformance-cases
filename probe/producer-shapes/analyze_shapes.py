"""Summarizes what each producer's plan for each query contains.

    <pysub>/bin/python analyze_shapes.py plans/          # one directory per producer

Per query and producer, one line of features:
  rels     relation kinds, a join as join:<TYPE>, a set operation as set:<OP>
  emit     relation kinds that carry RelCommon.emit
  mask     every ReadRel projection mask, as its field indices
  fetch    'expr' for offset_expr/count_expr, 'int' when only the removed integer fields are set
  vt       'expr' for VirtualTable.expressions, 'values' for the removed values field
  groups   the grouping sets of an AggregateRel, as indices into grouping_expressions
  phase    the phases of its measures; out = declared output types of aggregate functions
  ts       precisions of precision_timestamp literals
  opts     scalar-function options written
  subq     subquery expressions left in the plan
  ext      'urn' / 'uri' for how extensions are declared
Removed fields are seen as unknown fields in the 0.99 bindings; their field numbers are listed in
LEGACY.
"""
import os, sys
from google.protobuf.unknown_fields import UnknownFieldSet
from substrait import algebra_pb2 as A, plan_pb2 as P

LEGACY = {("FetchRel", 3): "offset:int", ("FetchRel", 4): "count:int",
          ("Grouping", 1): "grouping_expressions:legacy", ("VirtualTable", 1): "values:legacy",
          ("Plan", 1): "extension_uris"}

def tname(t):
    k = t.WhichOneof("kind")
    if k is None: return "unset"
    v = getattr(t, k)
    s = {"decimal": lambda: "dec(%d,%d)" % (v.precision, v.scale),
         "precision_timestamp": lambda: "pts(%d)" % v.precision}.get(k, lambda: k)()
    return s + ("?" if getattr(v, "nullability", 0) == 1 else "")

def analyze(plan):
    f = dict(rels=[], emit=[], mask=[], fetch=[], vt=[], groups=[], phase=[], out=[], ts=[],
             opts=[], subq=[], legacy=[])
    names = {}
    for e in plan.extensions:
        if e.HasField("extension_function"):
            names[e.extension_function.function_anchor] = e.extension_function.name
    def walk(m):
        tn = m.DESCRIPTOR.name
        for uf in UnknownFieldSet(m):
            if (tn, uf.field_number) in LEGACY:
                f["legacy"].append(LEGACY[(tn, uf.field_number)])
        if isinstance(m, A.Rel):
            k = m.WhichOneof("rel_type")
            r = getattr(m, k)
            if k in ("join", "hash_join", "merge_join", "nested_loop_join"):
                f["rels"].append("%s:%s" % (k, type(r).JoinType.Name(r.type).replace("JOIN_TYPE_", "")))
            elif k == "set":
                f["rels"].append("set:" + A.SetRel.SetOp.Name(r.op).replace("SET_OP_", ""))
            else:
                f["rels"].append(k)
            if r.HasField("common") and r.common.HasField("emit"):
                f["emit"].append(k)
            if k == "read":
                if r.HasField("projection"):
                    f["mask"].append([i.field for i in r.projection.select.struct_items])
                if r.HasField("virtual_table"):
                    f["vt"].append("expr" if len(r.virtual_table.expressions) else "values?")
            if k == "fetch":
                f["fetch"].append("expr" if (r.HasField("offset_expr") or r.HasField("count_expr")) else "int?")
            if k == "aggregate":
                f["groups"].append([list(g.expression_references) for g in r.groupings])
                for ms in r.measures:
                    af = ms.measure
                    f["phase"].append(A.AggregationPhase.Name(af.phase).replace("AGGREGATION_PHASE_", ""))
                    f["out"].append("%s->%s" % (names.get(af.function_reference, "?"), tname(af.output_type)))
        if isinstance(m, A.Expression):
            k = m.WhichOneof("rex_type")
            if k == "literal" and m.literal.WhichOneof("literal_type") in ("precision_timestamp", "precision_timestamp_tz"):
                f["ts"].append(getattr(m.literal, m.literal.WhichOneof("literal_type")).precision)
            if k == "subquery":
                f["subq"].append(m.subquery.WhichOneof("subquery_type"))
            if k == "scalar_function":
                for o in m.scalar_function.options:
                    f["opts"].append("%s=%s" % (o.name, ",".join(o.preference)))
        for fd, v in m.ListFields():
            if fd.type != fd.TYPE_MESSAGE: continue
            for x in (v if fd.label == fd.LABEL_REPEATED else [v]):
                if hasattr(x, "DESCRIPTOR"): walk(x)
    walk(plan)
    f["ext"] = ["urn"] if len(plan.extension_urns) else []
    return f

def fmt(f):
    out = ["rels=" + ",".join(f["rels"])]
    for k in ("emit", "mask", "fetch", "vt", "groups", "phase", "out", "ts", "opts", "subq", "legacy", "ext"):
        if f[k]:
            out.append("%s=%s" % (k, f[k] if k in ("mask", "groups") else ",".join(map(str, f[k]))))
    return " ".join(out)

root = sys.argv[1]
producers = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
queries = [l.split("\t")[0] for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries.tsv"))]
for q in queries:
    print(q)
    for p in producers:
        base = os.path.join(root, p, q)
        if os.path.exists(base + ".err"):
            print("  %-10s REFUSED %s" % (p, open(base + ".err").read().strip()[:110]))
        elif os.path.exists(base + ".pb"):
            plan = P.Plan(); plan.ParseFromString(open(base + ".pb", "rb").read())
            print("  %-10s %s" % (p, fmt(analyze(plan))))
