"""Prototype: a schema deriver for substrait.Plan protobuf-JSON, written from the spec text alone.

Purpose: measure how much code an in-spec-repo deriver needs, and whether it reproduces the
hand-written expectations of alexandrefimov/substrait-conformance-cases (expected.json).
It reads the extension YAMLs at the spec release the plans declare (v0.102.0) and evaluates the
return-type derivation language (site/docs/expressions/scalar_functions.md, Return Type
Expressions) with a hand-written parser; relation rules follow site/docs/relations/*.md.

"""

import json
import os
import re
import sys
import yaml

# ----------------------------------------------------------------------------------------------
# Types: (name, params tuple, nullable). Rendered the way expected.json spells them.
SHORT = {
    "i8": "i8",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "fp32": "fp32",
    "fp64": "fp64",
    "bool": "bool",
    "boolean": "bool",
    "string": "str",
    "str": "str",
    "binary": "bin",
    "date": "date",
    "uuid": "uuid",
    "decimal": "dec",
    "dec": "dec",
    "varchar": "vchar",
    "vchar": "vchar",
    "fixedchar": "fchar",
    "fchar": "fchar",
    "fixedbinary": "fbin",
    "fbin": "fbin",
    "precision_timestamp": "precision_timestamp",
    "pts": "precision_timestamp",
    "struct": "struct",
    "list": "list",
    "map": "map",
    "precisiontimestamp": "precision_timestamp",
}


def T(name, params=(), nullable=False):
    return (SHORT[name.lower()], tuple(params), bool(nullable))


def render(t):
    name, params, nullable = t
    if name == "struct":
        s = "struct(%s)" % ",".join(
            render(p)[0] + ("?" if p[2] else "") if isinstance(p, tuple) else str(p)
            for p in params
        )
    elif params:
        s = "%s(%s)" % (name, ",".join(str(p) for p in params))
    else:
        s = name
    return [s, nullable]


# --- from protobuf-JSON Type messages ----------------------------------------------------------
def type_from_proto(tp):
    ((kind, spec),) = tp.items()
    n = spec.get("nullability") == "NULLABILITY_NULLABLE"
    k = kind.lower()
    if k in ("varchar", "fixedchar", "fixedbinary"):
        return T(k, (spec["length"],), n)
    if k == "decimal":
        return T("decimal", (spec.get("precision", 0), spec.get("scale", 0)), n)
    if k == "precisiontimestamp":
        return T("precision_timestamp", (spec.get("precision", 0),), n)
    if k == "struct":
        return T("struct", tuple(type_from_proto(x) for x in spec.get("types", [])), n)
    return T(k, (), n)


def schema_from_named_struct(ns):
    return [type_from_proto(x) for x in ns["struct"]["types"]]


# ----------------------------------------------------------------------------------------------
# The return-type derivation language.
TOK = re.compile(
    r"\s*(?:(\d+)|([A-Za-z_][A-Za-z_0-9]*)|(\?|<=|>=|==|!=|&&|\|\||[<>+\-*/(),:=?!]))"
)


def tokenize(s):
    out, i = [], 0
    s = s.strip()
    while i < len(s):
        m = TOK.match(s, i)
        if not m or m.end() == i:
            raise ValueError("cannot tokenize %r at %d" % (s, i))
        out.append(m.group(1) or m.group(2) or m.group(3))
        i = m.end()
    return out


class Parser:
    """Precedence climbing over: ternary > || > && > == != > < > <= >= > + - > * / > unary > atom."""

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def eat(self, x=None):
        v = self.peek()
        if x is not None and v != x:
            raise ValueError("expected %r got %r in %r" % (x, v, self.t))
        self.i += 1
        return v

    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.binop(0)
        if self.peek() == "?":
            self.eat("?")
            a = self.ternary()
            self.eat(":")
            b = self.ternary()
            return ("if", c, a, b)
        return c

    LEVELS = [
        ("||",),
        ("&&",),
        ("==", "!="),
        ("<", ">", "<=", ">="),
        ("+", "-"),
        ("*", "/"),
    ]

    def binop(self, lvl):
        if lvl == len(self.LEVELS):
            return self.unary()
        left = self.binop(lvl + 1)
        while self.peek() in self.LEVELS[lvl]:
            op = self.eat()
            right = self.binop(lvl + 1)
            left = (op, left, right)
        return left

    def unary(self):
        if self.peek() == "!":
            self.eat()
            return ("!", self.unary())
        if self.peek() == "-":
            self.eat()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        v = self.eat()
        if v == "(":
            e = self.expr()
            self.eat(")")
            return e
        if v.isdigit():
            return ("int", int(v))
        if v in ("true", "false"):
            return ("bool", v == "true")
        # identifier: function call, type with params, or parameter name
        if self.peek() == "(":
            self.eat("(")
            args = []
            while self.peek() != ")":
                args.append(self.expr())
                if self.peek() == ",":
                    self.eat(",")
            self.eat(")")
            return ("call", v.lower(), args)
        nullable = False
        if self.peek() == "?":
            self.eat("?")
            nullable = True
        if self.peek() == "<":
            self.eat("<")
            params = []
            while self.peek() != ">":
                params.append(
                    self.binop(4)
                )  # type parameters: arithmetic, never comparisons
                if self.peek() == ",":
                    self.eat(",")
            self.eat(">")
            return ("type", v, params, nullable)
        if v.lower() in SHORT or v.lower().startswith("any"):
            return ("type", v, [], nullable)
        return ("param", v)


def parse_return(text):
    """A return expression: zero or more `name = expr` lines, then the final expression."""
    assigns, final = [], None
    lines = [line for line in text.strip().splitlines() if line.strip()]
    for ln in lines[:-1]:
        name, rhs = ln.split("=", 1)
        assigns.append((name.strip(), Parser(tokenize(rhs)).expr()))
    final = Parser(tokenize(lines[-1])).expr()
    return assigns, final


def evaluate(node, env):
    k = node[0]
    if k == "int":
        return node[1]
    if k == "bool":
        return node[1]
    if k == "param":
        if node[1] not in env:
            raise KeyError("unbound parameter %s" % node[1])
        return env[node[1]]
    if k == "neg":
        return -evaluate(node[1], env)
    if k == "!":
        return not evaluate(node[1], env)
    if k == "if":
        return (
            evaluate(node[2], env) if evaluate(node[1], env) else evaluate(node[3], env)
        )
    if k == "call":
        args = [evaluate(a, env) for a in node[2]]
        return {"min": min, "max": max}[node[1]](*args)
    if k == "type":
        name, params, nullable = node[1], node[2], node[3]
        if name.lower().startswith("any"):
            bound = env.get(name.lower()) or env.get("any")
            return (bound[0], bound[1], nullable or bound[2])
        vals = []
        for p in params:
            v = evaluate(p, env)
            vals.append(v)
        return T(name, tuple(vals), nullable)
    a, b = evaluate(node[1], env), evaluate(node[2], env)
    return {
        "+": lambda: a + b,
        "-": lambda: a - b,
        "*": lambda: a * b,
        "/": lambda: a // b,
        "<": lambda: a < b,
        ">": lambda: a > b,
        "<=": lambda: a <= b,
        ">=": lambda: a >= b,
        "==": lambda: a == b,
        "!=": lambda: a != b,
        "&&": lambda: a and b,
        "||": lambda: a or b,
    }[k]()


def eval_return(text, env):
    assigns, final = parse_return(text)
    env = dict(env)
    for name, e in assigns:
        env[name] = evaluate(e, env)
    return evaluate(final, env)


# --- binding declared argument patterns to actual types ----------------------------------------
def bind_arg(pattern, actual, env):
    """pattern is a parsed ('type', name, params, nullable) node; binds P/S/any vars into env."""
    _, name, params, _ = pattern
    n = name.lower()
    if n.startswith("any"):
        key = n if n != "any" else "any"
        if key in env and env[key][:2] != actual[:2] and key != "any":
            return False
        env[key] = actual
        return True
    if SHORT.get(n) != actual[0]:
        return False
    if len(params) != len(actual[1]):
        return False
    for p, v in zip(params, actual[1], strict=True):
        if p[0] == "param":
            env[p[1]] = v
        elif p[0] == "int" and p[1] != v:
            return False
    return True


# ----------------------------------------------------------------------------------------------
class Extensions:
    def __init__(self, plan, ext_dir):
        self.by_anchor = {}
        urns = {
            u["extensionUrnAnchor"]: u["urn"] for u in plan.get("extensionUrns", [])
        }
        for e in plan.get("extensions", []):
            f = e.get("extensionFunction")
            if not f:
                continue
            urn = urns[f["extensionUrnReference"]]
            fname = os.path.join(ext_dir, urn.split(":")[-1] + ".yaml")
            self.by_anchor[f["functionAnchor"]] = (
                yaml.safe_load(open(fname)),
                f["name"],
            )

    def resolve(self, anchor, arg_types, phase=None, window=False):
        doc, compound = self.by_anchor[anchor]
        name = compound.split(":")[0]
        pools = (
            ["window_functions", "aggregate_functions", "scalar_functions"]
            if window
            else ["scalar_functions", "aggregate_functions", "window_functions"]
        )
        for pool in pools:
            for fn in doc.get(pool) or []:
                if fn["name"] != name:
                    continue
                for impl in fn["impls"]:
                    env = {}
                    decl_args = [a for a in impl.get("args", []) if "value" in a]
                    if len(decl_args) != len(arg_types):
                        continue
                    ok = True
                    for a, actual in zip(decl_args, arg_types, strict=True):
                        pat = Parser(tokenize(a["value"])).expr()
                        if pat[0] != "type" or not bind_arg(pat, actual, env):
                            ok = False
                            break
                    if not ok:
                        continue
                    return self.output(impl, arg_types, env, phase)
        raise KeyError(
            "no impl of %s for %s" % (compound, [render(a) for a in arg_types])
        )

    @staticmethod
    def output(impl, arg_types, env, phase):
        text = impl["return"]
        if (
            phase
            in (
                "AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE",
                "AGGREGATION_PHASE_INTERMEDIATE_TO_INTERMEDIATE",
            )
            and "intermediate" in impl
        ):
            text = impl["intermediate"]
        # STRUCT<i64,i64> and the like: the type grammar, but written in the YAML's spelling
        t = eval_return(text, env)
        mode = impl.get("nullability", "MIRROR")
        if mode == "MIRROR":
            nullable = any(a[2] for a in arg_types)
            return (t[0], t[1], nullable)
        return t  # DECLARED_OUTPUT / DISCRETE: the expression's own nullability


# ----------------------------------------------------------------------------------------------
class Deriver:
    def __init__(self, plan, ext_dir):
        self.ext = Extensions(plan, ext_dir)
        # ReferenceRel names a position in Plan.relations, so the whole plan has to be
        # reachable from the relation walk rather than only the subtree being walked.
        self.plan = plan

    # --- expressions ---
    def expr_type(self, e, inp):
        if "selection" in e:
            ref = e["selection"]["directReference"]
            idx = ref.get("structField", {}).get("field", 0)
            return inp[idx]
        if "literal" in e:
            return self.literal_type(e["literal"])
        if "scalarFunction" in e:
            f = e["scalarFunction"]
            args = [
                self.expr_type(a["value"], inp)
                for a in f.get("arguments", [])
                if "value" in a
            ]
            return self.ext.resolve(f["functionReference"], args)
        if "cast" in e:
            return type_from_proto(e["cast"]["type"])
        raise NotImplementedError("expression kind %s" % list(e))

    @staticmethod
    def literal_type(lit):
        nullable = bool(lit.get("nullable", False))
        ((kind, v),) = [
            (k, v)
            for k, v in lit.items()
            if k not in ("nullable", "typeVariationReference")
        ]
        if kind == "null":
            return type_from_proto(v)
        if kind == "decimal":
            return T("decimal", (v["precision"], v["scale"]), nullable)
        if kind == "varChar":
            return T("varchar", (v["length"],), nullable)
        if kind == "fixedChar":
            return T("fixedchar", (len(v),), nullable)
        if kind == "fixedBinary":
            return T("fixedbinary", (len(__import__("base64").b64decode(v)),), nullable)
        if kind == "precisionTimestamp":
            return T("precision_timestamp", (v.get("precision", 0),), nullable)
        return T(kind, (), nullable)

    # --- relations ---
    def rel(self, r):
        ((kind, node),) = [(k, v) for k, v in r.items()]
        direct = getattr(self, "rel_" + kind)(node)
        emit = node.get("common", {}).get("emit")
        if emit:
            direct = [direct[i] for i in emit.get("outputMapping", [])]
        return direct

    @staticmethod
    def apply_select(t, sel):
        """Narrow a type by a MaskExpression Select, keeping only what it names.

        Only struct selects are handled. A list or map select would also have to say
        what happens to the elements around the ones it keeps, and no case here reaches
        one, so an unhandled kind is an error rather than a silent pass-through.
        """
        if "struct" not in sel:
            raise NotImplementedError(f"mask select kind {list(sel)}")
        if t[0] != "struct":
            raise ValueError(f"a struct select applied to {t[0]}")
        kept = []
        for item in sel["struct"]["structItems"]:
            sub = t[1][item.get("field", 0)]
            kept.append(
                Deriver.apply_select(sub, item["child"]) if "child" in item else sub
            )
        return ("struct", tuple(kept), t[2])

    def rel_read(self, n):
        schema = schema_from_named_struct(n["baseSchema"])
        proj = n.get("projection")
        if proj:
            # "Defaults to the schema of the data read after the optional projection
            # (masked complex expression) is applied", and a struct item's child narrows
            # that column further rather than replacing it.
            out = []
            for it in proj["select"]["structItems"]:
                col = schema[it.get("field", 0)]
                out.append(
                    self.apply_select(col, it["child"]) if "child" in it else col
                )
            schema = out
        return schema

    def rel_filter(self, n):
        return self.rel(n["input"])

    def rel_sort(self, n):
        return self.rel(n["input"])

    def rel_fetch(self, n):
        return self.rel(n["input"])

    def rel_topN(self, n):
        return self.rel(n["input"])

    def rel_write(self, n):
        return self.rel(n["input"])  # "Unchanged from input"

    def rel_exchange(self, n):
        return self.rel(n["input"])  # "Order of the input"

    def rel_project(self, n):
        inp = self.rel(n["input"])
        return inp + [self.expr_type(e, inp) for e in n.get("expressions", [])]

    def rel_reference(self, n):
        """ReferenceRel maintains all properties of what it refers to, output included."""
        i = n.get("subtreeOrdinal", 0)
        rels = self.plan.get("relations", [])
        if not 0 <= i < len(rels):
            raise ValueError(f"subtree_ordinal {i} is outside Plan.relations")
        target = rels[i]
        if "rel" not in target:
            raise ValueError(f"subtree_ordinal {i} names a root, not a bare relation")
        return self.rel(target["rel"])

    def rel_cross(self, n):
        return self.rel(n["left"]) + self.rel(n["right"])

    def join_like(self, n):
        L, R = self.rel(n["left"]), self.rel(n["right"])
        t = n.get("type", "JOIN_TYPE_UNSPECIFIED").replace("JOIN_TYPE_", "")

        def nul(xs):
            """The same columns, widened to nullable, as a padded side becomes."""
            return [(a, b, True) for (a, b, _) in xs]

        mark = [T("bool", (), True)]
        return {
            "INNER": L + R,
            "OUTER": nul(L) + nul(R),
            "LEFT": L + nul(R),
            "RIGHT": nul(L) + R,
            "LEFT_SEMI": L,
            "LEFT_ANTI": L,
            "RIGHT_SEMI": R,
            "RIGHT_ANTI": R,
            "LEFT_SINGLE": L + nul(R),
            "RIGHT_SINGLE": nul(L) + R,
            "LEFT_MARK": L + mark,
            "RIGHT_MARK": R + mark,
        }[t]

    rel_join = rel_hashJoin = rel_mergeJoin = rel_nestedLoopJoin = join_like

    def rel_set(self, n):
        ins = [self.rel(i) for i in n["inputs"]]
        op = n["op"].replace("SET_OP_", "")
        widths = {len(i) for i in ins}
        if len(widths) != 1:
            raise ValueError(f"set inputs disagree on width: {sorted(widths)}")
        out = []
        for col in zip(*ins, strict=True):
            p, rest = col[0], col[1:]
            if op.startswith("MINUS"):
                nullable = p[2]
            elif op == "INTERSECTION_PRIMARY":
                nullable = p[2] and any(s[2] for s in rest)
            elif op.startswith("INTERSECTION_MULTISET"):
                nullable = all(c[2] for c in col)
            elif op.startswith("UNION"):
                nullable = any(c[2] for c in col)
            else:
                raise NotImplementedError(op)
            out.append((p[0], p[1], nullable))
        return out

    def rel_aggregate(self, n):
        inp = self.rel(n["input"])
        gexprs = [self.expr_type(e, inp) for e in n.get("groupingExpressions", [])]
        sets = [g.get("expressionReferences", []) for g in n.get("groupings", [])]
        keys = []
        for i, t in enumerate(gexprs):
            in_all = all(i in s for s in sets)
            keys.append((t[0], t[1], t[2] or not in_all))
        measures = []
        for m in n.get("measures", []):
            f = m["measure"]
            args = [
                self.expr_type(a["value"], inp)
                for a in f.get("arguments", [])
                if "value" in a
            ]
            measures.append(
                self.ext.resolve(f["functionReference"], args, phase=f.get("phase"))
            )
        index = [T("i32", (), False)] if len(sets) > 1 else []
        return keys + measures + index

    def rel_expand(self, n):
        inp = self.rel(n["input"])
        out = []
        fields = n.get("fields", [])
        for f in fields:
            if "consistentField" in f:
                out.append(self.expr_type(f["consistentField"], inp))
            else:
                dups = [
                    self.expr_type(d, inp) for d in f["switchingField"]["duplicates"]
                ]
                # SwitchingField in algebra.proto: all duplicates return the same type
                # class, and the output field is nullable if any duplicate is.
                out.append((dups[0][0], dups[0][1], any(d[2] for d in dups)))
        # ExpandRel in algebra.proto: fields beyond the provided definitions are emitted
        # as is, as if a consistent field with an identity expression had been given.
        out += inp[len(fields) :]
        return out + [T("i32", (), False)]

    def rel_window(self, n):
        inp = self.rel(n["input"])
        out = list(inp)
        for w in n.get("windowFunctions", []):
            args = [
                self.expr_type(a["value"], inp)
                for a in w.get("arguments", [])
                if "value" in a
            ]
            out.append(
                self.ext.resolve(
                    w["functionReference"], args, phase=w.get("phase"), window=True
                )
            )
        return out


def derive(plan, ext_dir):
    """The schema of the plan's single root.

    A Plan may hold several relations, of which the bare ones exist to be referenced;
    only a root is an output. The corpus carries one expectation per case, so a case
    with more than one root would not say which one it is about.
    """
    d = Deriver(plan, ext_dir)
    roots = [r["root"] for r in plan.get("relations", []) if "root" in r]
    if len(roots) != 1:
        raise ValueError(
            f"a case must have exactly one root relation, found {len(roots)}"
        )
    return [render(t) for t in d.rel(roots[0]["input"])]
