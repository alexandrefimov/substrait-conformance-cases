"""One case through substrait-validator (built from main, spec 0.87): the root schema plus
diagnostics.

IMPORTANT, on boundaries. The validator does NOT derive the type a function call returns: it
repeats the output_type declared in the plan. Checked with a plan carrying a knowingly false
declaration - it accepts it and prints the lie. With URN_DEPTH>0 it does find the YAML, but then
runs into "not yet implemented: impls". So its answer is independent only for RELATION schemas
(joins, set operations, emit, projection, grouping), where the plan has nothing to declare.
"""
import sys
import substrait_validator as sv

SIMPLE = {1:"bool",2:"i8",3:"i16",5:"i32",7:"i64",10:"fp32",11:"fp64",12:"str",13:"bin",
          14:"ts",16:"date",17:"time",19:"iyear",20:"iday",29:"tstz",32:"uuid"}
COMPOUND = {21:"fchar",22:"vchar",23:"fbin",24:"dec",25:"struct",26:"nstruct",27:"list",28:"map"}

def render(dt):
    c = dt.__getattribute__("class")
    kind = c.WhichOneof("kind")
    if kind == "simple":
        base = SIMPLE.get(c.simple, "simple%d" % c.simple)
    elif kind == "compound":
        base = COMPOUND.get(c.compound, "compound%d" % c.compound)
    elif kind == "user_defined_type":
        base = "u!%s" % c.user_defined_type.name
    else:
        base = "unresolved"
    ps = []
    for p in dt.parameters:
        k = p.WhichOneof("kind")
        if k == "data_type":
            ps.append((p.name + ":" if p.name else "") + render(p.data_type))
        elif k == "integer":
            ps.append(str(p.integer))
        elif k == "unsigned":
            ps.append(str(p.unsigned))
        elif k == "named_type":
            ps.append((p.named_type.name + ":" if p.named_type.name else "") + render(p.named_type.data_type))
        elif k == "null":
            ps.append("_")
        else:
            ps.append(str(getattr(p, k, "?")))
    if base == "nstruct" or base == "struct":
        return "[%s]" % ", ".join(ps) + ("?" if dt.nullable else "")
    return base + ("(%s)" % ",".join(ps) if ps else "") + ("?" if dt.nullable else "")

def walk(node, depth=0):
    yield depth, node
    for d in node.data:
        if d.HasField("child"):
            yield from walk(d.child.node, depth + 1)

path = sys.argv[1]
try:
    plan = sv.load_plan_from_json(open(path).read())
except Exception as e:
    print("VALIDATOR LOADFAIL  %s" % str(e).replace("\n", " ")[:160]); sys.exit(0)
cfg = sv.Config()
depth = int(__import__("os").environ.get("URN_DEPTH", "0"))
if depth:
    cfg.set_max_urn_resolution_depth(depth)
res = sv.plan_to_parse_result(plan, cfg)
nodes = list(walk(res.root))
diags = [d.diagnostic for _, n in nodes for d in n.data if d.HasField("diagnostic")]
# level: 1=info 2=warning 3=error (adjusted_level)
errs = [d for d in diags if d.adjusted_level == 3]
warns = [d for d in diags if d.adjusted_level == 2 and "compatib" not in d.msg]
rels = [(dep, n) for dep, n in nodes if n.__getattribute__("class") == 3 and n.HasField("data_type")]
if rels:
    top = min(rels, key=lambda x: x[0])[1]
    print("VALIDATOR SCHEMA    %s" % render(top.data_type))
else:
    print("VALIDATOR SCHEMA    —")
if errs:
    print("VALIDATOR ERROR     %s" % errs[0].msg.replace("\n", " ")[:150])
if warns:
    print("VALIDATOR WARN      %s" % warns[0].msg.replace("\n", " ")[:150])
