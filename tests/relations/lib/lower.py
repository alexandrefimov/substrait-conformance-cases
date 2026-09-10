"""Descriptor-driven lowering of protobuf-shaped YAML into a substrait.Plan.

The rule that keeps this non-semantic: the shape of the document is the protobuf
message tree, and a string is expanded only where the *descriptor* says a
substrait.Type, NamedStruct, Expression or Expression.Literal is expected. There
is no relation-specific code, no overload resolution and no type derivation, so
adding a relation to the spec needs no compiler change. The author writes every
declaration: composite function name, output_type, root names.

Two structural sugars beyond that:
  read: NAME          -> ReadRel{base_schema: <inputs[NAME].schema>, named_table{NAME}}
  extensions: {alias: urn}  -> extension_urns/extensions, anchors allocated in first-use order

Refusals (each is a red-team finding turned into an error):
  - duplicate YAML keys
  - a bare YAML number or bool where a literal is expected (must be "<value>::<type>")
  - a decimal literal whose text does not fit the declared scale exactly
  - a fixture row whose cell count differs from its schema
  - anything read from `expect` while building the plan
"""

import base64
import re
from decimal import Decimal, localcontext

import yaml
from google.protobuf import descriptor as _d

from . import paths  # noqa: F401  (puts the bindings on sys.path)
from substrait.algebra_pb2 import Expression, Rel, RelRoot
from substrait.plan_pb2 import Plan, PlanRel, Version
from substrait.type_pb2 import NamedStruct, Type
from substrait.extensions.extensions_pb2 import (
    SimpleExtensionDeclaration,
    SimpleExtensionURN,
)


class CaseError(Exception):
    pass


# --------------------------------------------------------------------------- YAML
class StrictLoader(yaml.SafeLoader):
    pass


def _no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise CaseError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


def load_case(path):
    return yaml.load(open(path), Loader=StrictLoader)


# --------------------------------------------------------------------------- types
SCALAR = {
    "bool": "bool",
    "boolean": "bool",
    "i8": "i8",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "fp32": "fp32",
    "fp64": "fp64",
    "string": "string",
    "str": "string",
    "binary": "binary",
    "date": "date",
    "uuid": "uuid",
}
PARAM1 = {
    "varchar": "varchar",
    "vchar": "varchar",
    "fixedchar": "fixed_char",
    "fchar": "fixed_char",
    "fixedbinary": "fixed_binary",
    "fbin": "fixed_binary",
    "precision_timestamp": "precision_timestamp",
    "pts": "precision_timestamp",
    "precision_time": "precision_time",
    "interval_day": "interval_day",
}
TYPE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*(?:<([^>]*)>)?\s*(\?)?\s*$")


def parse_type(text):
    m = TYPE_RE.match(text)
    if not m:
        raise CaseError(f"cannot parse type {text!r}")
    name, params, q = m.group(1).lower(), m.group(2), m.group(3)
    nullability = Type.NULLABILITY_NULLABLE if q else Type.NULLABILITY_REQUIRED
    t = Type()
    if name in SCALAR and not params:
        getattr(t, SCALAR[name]).nullability = nullability
        return t
    if name in ("decimal", "dec"):
        p, s = [int(x) for x in params.split(",")]
        t.decimal.precision, t.decimal.scale, t.decimal.nullability = p, s, nullability
        return t
    if name in PARAM1:
        field = PARAM1[name]
        sub = getattr(t, field)
        n = int(params)
        if field in ("varchar", "fixed_char", "fixed_binary"):
            sub.length = n
        else:
            sub.precision = n
        sub.nullability = nullability
        return t
    raise CaseError(f"unsupported type {text!r} (raw proto-JSON is the escape hatch)")


def render_type(t):
    """Reverse direction, used by the round-trip check."""
    kind = t.WhichOneof("kind")
    sub = getattr(t, kind)
    q = "?" if sub.nullability == Type.NULLABILITY_NULLABLE else ""
    short = {"fixed_char": "fixedchar", "fixed_binary": "fixedbinary"}.get(kind, kind)
    if kind == "decimal":
        return f"{short}<{sub.precision},{sub.scale}>{q}"
    if kind in ("varchar", "fixed_char", "fixed_binary"):
        return f"{short}<{sub.length}>{q}"
    if kind in ("precision_timestamp", "precision_time", "interval_day"):
        return f"{short}<{sub.precision}>{q}"
    return f"{short}{q}"


def parse_named_struct(text):
    ns = NamedStruct()
    ns.struct.nullability = Type.NULLABILITY_REQUIRED
    for col in split_top(text, ","):
        if ":" not in col:
            raise CaseError(f"column {col!r} must be name:type")
        name, ty = col.split(":", 1)
        ns.names.append(name.strip())
        ns.struct.types.append(parse_type(ty))
    return ns


def render_named_struct(ns):
    # Names run depth first, so a nested struct has more names than the top level has
    # types; pairing stops at the top-level types on purpose.
    return ", ".join(
        f"{n}:{render_type(t)}" for n, t in zip(ns.names, ns.struct.types, strict=False)
    )


def split_top(text, sep):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "(<":
            depth += 1
        elif ch in ")>":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x for x in out if x.strip()]


# ------------------------------------------------------------------------ literals
LIT_RE = re.compile(r"^\s*(.*?)\s*::\s*(.+?)\s*$", re.S)


def parse_literal(text):
    if not isinstance(text, str):
        raise CaseError(
            f"literal {text!r} must be a quoted string with an explicit "
            f"::type; bare YAML scalars are rejected"
        )
    m = LIT_RE.match(text)
    if not m:
        raise CaseError(f"literal {text!r} must be written <value>::<type>")
    value, tyname = m.group(1), m.group(2)
    t = parse_type(tyname)
    kind = t.WhichOneof("kind")
    sub = getattr(t, kind)
    nullable = sub.nullability == Type.NULLABILITY_NULLABLE
    lit = Expression.Literal()
    if value == "null":
        if not nullable:
            raise CaseError(f"null literal needs a nullable type: {text!r}")
        lit.null.CopyFrom(t)
        return lit
    if kind in ("i8", "i16", "i32", "i64"):
        setattr(lit, kind, int(value))
    elif kind == "bool":
        if value not in ("true", "false"):
            raise CaseError(f"bool literal {value!r}")
        lit.boolean = value == "true"
    elif kind == "string":
        if not (len(value) >= 2 and value[0] == value[-1] == "'"):
            raise CaseError(f"string literal must be single-quoted: {text!r}")
        lit.string = value[1:-1]
    elif kind in ("fp32", "fp64"):
        setattr(lit, kind, float(value))
    elif kind == "decimal":
        with localcontext() as ctx:
            ctx.prec = 60
            d = Decimal(value)
            scaled = d.scaleb(sub.scale)
            if scaled != scaled.to_integral_value():
                raise CaseError(
                    f"decimal literal {value!r} does not fit scale {sub.scale} exactly"
                )
            unscaled = int(scaled)
        if len(str(abs(unscaled))) > sub.precision:
            raise CaseError(
                f"decimal literal {value!r} exceeds precision {sub.precision}"
            )
        lit.decimal.value = unscaled.to_bytes(16, "little", signed=True)
        lit.decimal.precision, lit.decimal.scale = sub.precision, sub.scale
    else:
        raise CaseError(
            f"literal of type {kind} not supported by the sugar; use raw proto-JSON"
        )
    if nullable:
        lit.nullable = True
    return lit


# --------------------------------------------------------------------- expressions
REF_RE = re.compile(r"^\$(\d+)$")
CALL_RE = re.compile(
    r"^\s*(?:([A-Za-z_][\w]*)\.)?([A-Za-z_][\w]*:[\w_]+)\s*\((.*)\)"
    r"\s*:\s*([^:()]+)\s*$",
    re.S,
)


class Registry:
    """Extension bookkeeping: aliases the author declared, anchors in first-use order."""

    def __init__(self, aliases):
        self.aliases = dict(aliases or {})
        self.urn_anchor, self.fn_anchor = {}, {}

    def function(self, alias, compound):
        if alias is None:
            if len(self.aliases) != 1:
                raise CaseError(f"{compound}: qualify the call with an extension alias")
            alias = next(iter(self.aliases))
        if alias not in self.aliases:
            raise CaseError(f"unknown extension alias {alias!r}")
        urn = self.aliases[alias]
        if urn not in self.urn_anchor:
            self.urn_anchor[urn] = len(self.urn_anchor) + 1
        key = (urn, compound)
        if key not in self.fn_anchor:
            self.fn_anchor[key] = len(self.fn_anchor) + 1
        return self.fn_anchor[key]

    def emit_into(self, plan):
        for urn, anchor in self.urn_anchor.items():
            plan.extension_urns.append(
                SimpleExtensionURN(extension_urn_anchor=anchor, urn=urn)
            )
        for (urn, compound), anchor in self.fn_anchor.items():
            plan.extensions.append(
                SimpleExtensionDeclaration(
                    extension_function=SimpleExtensionDeclaration.ExtensionFunction(
                        extension_urn_reference=self.urn_anchor[urn],
                        function_anchor=anchor,
                        name=compound,
                    )
                )
            )


def parse_expression(text, reg):
    if not isinstance(text, str):
        raise CaseError(f"expression {text!r} must be a string or a raw proto-JSON map")
    text = text.strip()
    m = REF_RE.match(text)
    if m:
        e = Expression()
        e.selection.root_reference.SetInParent()
        e.selection.direct_reference.struct_field.field = int(m.group(1))
        return e
    m = CALL_RE.match(text)
    if m:
        alias, compound, argsrc, ret = m.groups()
        e = Expression()
        f = e.scalar_function
        f.function_reference = reg.function(alias, compound)
        f.output_type.CopyFrom(parse_type(ret))  # the author's declaration, verbatim
        for a in split_top(argsrc, ","):
            f.arguments.add().value.CopyFrom(parse_expression(a, reg))
        return e
    e = Expression()
    e.literal.CopyFrom(parse_literal(text))
    return e


# ------------------------------------------------------------- descriptor-driven walk
SUGAR = {
    "substrait.Type": lambda s, reg: parse_type(s),
    "substrait.NamedStruct": lambda s, reg: parse_named_struct(s),
    "substrait.Expression": lambda s, reg: parse_expression(s, reg),
    "substrait.Expression.Literal": lambda s, reg: parse_literal(s),
}


def field_of(msg, key):
    d = msg.DESCRIPTOR
    for f in d.fields:
        if key in (f.name, f.json_name):
            return f
    raise CaseError(f"{d.full_name} has no field {key!r}")


def fill(msg, value, reg, inputs, path=""):
    """Fill protobuf message `msg` from a proto-shaped YAML value."""
    if not isinstance(value, dict):
        raise CaseError(
            f"{path}: expected a mapping for {msg.DESCRIPTOR.full_name}, "
            f"got {type(value).__name__}"
        )
    for key, val in value.items():
        f = field_of(msg, key)
        p = f"{path}/{key}"
        if f.is_repeated:
            if not isinstance(val, list):
                raise CaseError(f"{p}: expected a list")
            for i, item in enumerate(val):
                if f.type == _d.FieldDescriptor.TYPE_MESSAGE:
                    sub = getattr(msg, f.name).add()
                    set_one(sub, item, reg, inputs, f"{p}[{i}]", parent=msg, field=f)
                elif f.type == _d.FieldDescriptor.TYPE_ENUM and not isinstance(
                    item, int
                ):
                    getattr(msg, f.name).append(f.enum_type.values_by_name[item].number)
                else:
                    getattr(msg, f.name).append(item)
        elif f.type == _d.FieldDescriptor.TYPE_MESSAGE:
            set_one(getattr(msg, f.name), val, reg, inputs, p, parent=msg, field=f)
        elif f.type == _d.FieldDescriptor.TYPE_ENUM:
            setattr(
                msg,
                f.name,
                val if isinstance(val, int) else f.enum_type.values_by_name[val].number,
            )
        elif f.type == _d.FieldDescriptor.TYPE_BYTES:
            setattr(msg, f.name, base64.b64decode(val))
        else:
            setattr(msg, f.name, val)
    return msg


def bind_table(sub, name, inputs, path):
    """$table: NAME -> base_schema + named_table, copied verbatim from `inputs`."""
    if name not in inputs:
        raise CaseError(f"{path}: no input table {name!r}")
    sub.base_schema.CopyFrom(parse_named_struct(inputs[name]["schema"]))
    sub.named_table.names.append(name)
    return sub


def set_one(sub, val, reg, inputs, path, parent=None, field=None):
    full = sub.DESCRIPTOR.full_name
    sub.SetInParent()  # written by the author, so present even if empty
    # structural sugar: a ReadRel given as a table name, or carrying $table beside
    # its own proto fields
    if full == "substrait.ReadRel" and isinstance(val, str):
        return bind_table(sub, val, inputs, path)
    if full == "substrait.ReadRel" and isinstance(val, dict) and "$table" in val:
        val = dict(val)
        bind_table(sub, val.pop("$table"), inputs, path)
        return fill(sub, val, reg, inputs, path)
    if isinstance(val, str):
        if full not in SUGAR:
            raise CaseError(f"{path}: a string is not allowed where {full} is expected")
        sub.CopyFrom(SUGAR[full](val, reg))
        return sub
    if isinstance(val, dict) and full in SUGAR and set(val) & {"$raw"}:
        raise CaseError(f"{path}: use the field's proto shape directly, not $raw")
    return fill(sub, val, reg, inputs, path)


# --------------------------------------------------------------------------- driver
def build_plan(case):
    reg = Registry(case.get("extensions"))
    inputs = case.get("inputs") or {}
    for name, spec in inputs.items():
        ns = parse_named_struct(spec["schema"])
        for r, row in enumerate(spec.get("rows") or []):
            if len(row) != len(ns.names):
                raise CaseError(
                    f"input {name} row {r}: {len(row)} cells for "
                    f"{len(ns.names)} columns"
                )
    plan = Plan()
    fill(
        plan, case["plan"], reg, inputs, "/plan"
    )  # the whole block is a substrait.Plan
    reg.emit_into(plan)  # after the walk: anchors follow first use
    return plan


def build_tables(case, table_cls):
    out = []
    for name, spec in (case.get("inputs") or {}).items():
        ns = parse_named_struct(spec["schema"])
        t = table_cls()
        t.name.append(name)
        t.schema.CopyFrom(ns)
        for row in spec.get("rows") or []:
            s = t.rows.add()
            for cell in row:
                s.fields.append(parse_literal(cell))
        out.append(t)
    return out
