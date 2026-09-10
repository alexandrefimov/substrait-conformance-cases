"""The reverse direction: substrait.Plan -> protobuf-shaped source with leaf sugar.

This is the half the earlier experiment did not implement, and the half the ADR needs:
without it there is no CI round-trip check, and no way to import an existing plan into
a reviewable case. It is descriptor-driven like the lowering, and it falls back to the
raw protobuf shape for anything the sugar cannot express exactly.

Correctness criterion: lower(render(p)) must be byte-identical to p after anchor
canonicalisation. Anything else is a defect, not a formatting choice.
"""

import base64
from decimal import Decimal, localcontext

import yaml

from google.protobuf import descriptor as _d

from . import lower

SUGARED = {
    "substrait.Type",
    "substrait.NamedStruct",
    "substrait.Expression",
    "substrait.Expression.Literal",
}


def dump(doc):
    """The one YAML serialisation the corpus uses, so `idempotent` means one thing."""
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=None, width=100)


def verified(text, parse, original):
    """Return `text` only if parsing it gives back exactly what was rendered.

    Property-based testing showed the whole round-trip rests on this one line: every
    silent loss found was in a branch that printed text without reading it back --
    a typed null that dropped `nullable` or a type variation, an interval_day that
    gained `precision: 0`, a call rewritten to a different function. A branch that
    cannot verify must return None so the raw protobuf shape is used instead.
    """
    if text is None:
        return None
    try:
        return text if parse(text) == original else None
    except Exception:
        return None


# --------------------------------------------------------------------------- leaves
def try_type(t):
    try:
        text = lower.render_type(t)
        return text if lower.parse_type(text) == t else None
    except Exception:
        return None


def try_named_struct(ns):
    try:
        text = lower.render_named_struct(ns)
        return text if lower.parse_named_struct(text) == ns else None
    except Exception:
        return None


def try_literal(lit):
    kind = lit.WhichOneof("literal_type")
    q = "?" if lit.nullable else ""
    try:
        if kind == "null":
            text = f"null::{lower.render_type(lit.null)}"
        if kind in ("i8", "i16", "i32", "i64"):
            text = f"{getattr(lit, kind)}::{kind}{q}"
        elif kind == "boolean":
            text = f"{'true' if lit.boolean else 'false'}::bool{q}"
        elif kind == "string":
            if "'" in lit.string or "\\" in lit.string:
                return None
            text = f"'{lit.string}'::string{q}"
        elif kind in ("fp32", "fp64"):
            text = f"{getattr(lit, kind)!r}::{kind}{q}"
        elif kind == "decimal":
            unscaled = int.from_bytes(lit.decimal.value, "little", signed=True)
            with localcontext() as c:
                c.prec = 60  # lower.parse_literal uses the same
                value = Decimal(unscaled).scaleb(-lit.decimal.scale)
            text = (
                f"{value:.{lit.decimal.scale}f}::"
                f"decimal<{lit.decimal.precision},{lit.decimal.scale}>{q}"
            )
        else:
            return None
    except Exception:
        return None
    return verified(text, lower.parse_literal, lit)


def try_expression(e, ctx):
    kind = e.WhichOneof("rex_type")
    try:
        if kind == "literal":
            inner = try_literal(e.literal)
            return inner
        if kind == "selection":
            s = e.selection
            if (
                s.WhichOneof("root_type") == "root_reference"
                and s.WhichOneof("reference_type") == "direct_reference"
                and s.direct_reference.WhichOneof("reference_type") == "struct_field"
                and not s.direct_reference.struct_field.HasField("child")
            ):
                text = f"${s.direct_reference.struct_field.field}"
                return text if lower.parse_expression(text, None) == e else None
            return None
        if kind == "scalar_function":
            f = e.scalar_function
            entry = ctx.reg_view.get(f.function_reference)
            if entry is None or not f.HasField("output_type"):
                return None
            alias, compound = entry
            args = []
            for a in f.arguments:
                if a.WhichOneof("arg_type") != "value":
                    return None
                rendered = try_expression(a.value, ctx)
                if rendered is None:
                    return None
                args.append(rendered)
            if list(f.options):
                return None
            ret = try_type(f.output_type)
            if ret is None:
                return None
            text = f"{alias}.{compound}({', '.join(args)}):{ret}"
            if (
                verified(
                    text, lambda t: lower.parse_expression(t, _ReplayRegistry(ctx)), e
                )
                is None
            ):
                return None
            ctx.rendered_calls.add(f.function_reference)
            return text
    except Exception:
        return None
    return None


class _ReplayRegistry:
    """Resolves aliases the way lower.Registry will, so a rendered call can be checked
    against the message it came from before the text is accepted."""

    def __init__(self, ctx):
        self.ctx = ctx

    def function(self, alias, compound):
        for anchor, (a, c) in self.ctx.reg_view.items():
            if a == alias and c == compound:
                return anchor
        raise lower.CaseError(f"unknown alias {alias}")


# ----------------------------------------------------------------------- structure
class Ctx:
    def __init__(self, plan):
        self.tables = {}  # name -> schema string
        self.fallbacks = []  # paths that kept the raw protobuf shape
        self.reg_view = {}  # function_anchor -> (alias, compound)
        self.rendered_calls = set()  # anchors the sugar actually reproduced
        self.explicit_extensions = False
        self.allow_sugar = True  # leaf sugar (types, literals, expressions)
        self.allow_table = True  # the $table shorthand

        urn_of = {u.extension_urn_anchor: u.urn for u in plan.extension_urns}
        referenced = set()

        def collect(msg):
            for f, v in msg.ListFields():
                if f.name == "function_reference":
                    referenced.add(v)
                if f.type == _d.FieldDescriptor.TYPE_MESSAGE:
                    for item in v if f.is_repeated else [v]:
                        collect(item)

        for rel in plan.relations:
            collect(rel)
        self.referenced = referenced

        self.aliases = {}
        for d in plan.extensions:
            which = d.WhichOneof("mapping_type")
            inner = getattr(d, which)
            anchor = getattr(inner, "function_anchor", 0)
            if which != "extension_function" or anchor not in referenced:
                # an unreferenced or non-function declaration cannot be reconstructed
                # from a call, so the whole extension section is written out verbatim
                self.explicit_extensions = True
                continue
            urn = urn_of.get(inner.extension_urn_reference)
            if urn is None:  # a dangling reference cannot be sugared
                self.explicit_extensions = True
                continue
            alias = urn.split(":")[-1] or f"ext{inner.extension_urn_reference}"
            while self.aliases.get(alias, urn) != urn:
                alias += "_"  # two URNs, same last segment
            self.aliases[alias] = urn
            self.reg_view[anchor] = (alias, inner.name)
        if self.explicit_extensions:
            self.reg_view, self.aliases = {}, {}


def to_doc(msg, ctx, path=""):
    out = {}
    for f, v in msg.ListFields():
        p = f"{path}/{f.name}"
        out[f.name] = to_value(f, v, ctx, p)
    return out


def to_value(f, v, ctx, path):
    if f.is_repeated:
        if f.type == _d.FieldDescriptor.TYPE_MESSAGE:
            return [
                one_message(f, item, ctx, f"{path}[{i}]") for i, item in enumerate(v)
            ]
        if f.type == _d.FieldDescriptor.TYPE_ENUM:
            return [
                (
                    f.enum_type.values_by_number[x].name
                    if x in f.enum_type.values_by_number
                    else x
                )
                for x in v
            ]
        return list(v)
    if f.type == _d.FieldDescriptor.TYPE_MESSAGE:
        return one_message(f, v, ctx, path)
    if f.type == _d.FieldDescriptor.TYPE_ENUM:
        known = f.enum_type.values_by_number.get(v)
        return known.name if known else v  # open enum: keep the number
    if f.type == _d.FieldDescriptor.TYPE_BYTES:
        return base64.b64encode(v).decode()
    return v


def one_message(f, v, ctx, path):
    full = v.DESCRIPTOR.full_name
    if full == "substrait.ReadRel":
        return read_rel(v, ctx, path)
    if full in SUGARED and ctx.allow_sugar:
        text = {
            "substrait.Type": try_type,
            "substrait.NamedStruct": try_named_struct,
            "substrait.Expression.Literal": try_literal,
            "substrait.Expression": lambda m: try_expression(m, ctx),
        }[full](v)
        if text is not None:
            return text
        ctx.fallbacks.append(path)
    return to_doc(v, ctx, path)


def read_rel(rd, ctx, path):
    """base_schema + named_table become $table when the schema is expressible."""
    doc = {}
    used_sugar = False
    if (
        ctx.allow_table
        and rd.WhichOneof("read_type") == "named_table"
        and len(rd.named_table.names) == 1
    ):
        schema = try_named_struct(rd.base_schema)
        if schema is not None and not rd.named_table.advanced_extension.ByteSize():
            name = rd.named_table.names[0]
            prev = ctx.tables.get(name)
            if prev in (None, schema):
                ctx.tables[name] = schema
                doc["$table"] = name
                used_sugar = True
    for f, v in rd.ListFields():
        if used_sugar and f.name in ("base_schema", "named_table"):
            continue
        doc[f.name] = to_value(f, v, ctx, f"{path}/{f.name}")
    return doc


def render(plan, case_id="imported"):
    """Plan -> case document, guaranteed to lower back to `plan`.

    Sugar is attempted at three levels and the first one that survives an end-to-end
    check is returned: full sugar; no call sugar (aggregate and window functions are
    not rendered as calls, so their plans keep the extension section verbatim); and no
    sugar at all, which is the plain protobuf shape. `expect` is deliberately absent:
    the program does not depend on the expectation.
    """
    from . import canonical  # local: avoids an import cycle

    target = canonical.fingerprint(plan)
    attempts = []
    for level in (0, 1, 2):
        ctx = Ctx(plan)
        if level >= 1:
            ctx.reg_view, ctx.aliases = {}, {}
            ctx.explicit_extensions = True
        if level == 2:
            ctx.allow_sugar = ctx.allow_table = False
        body = to_doc(plan, ctx, "/plan")
        if level == 0 and ctx.rendered_calls != ctx.referenced:
            continue  # a declaration would vanish
        doc = {"id": case_id, "spec_ref": "TODO", "kind": "KIND_POSITIVE"}
        if ctx.aliases:
            doc["extensions"] = dict(ctx.aliases)
        if ctx.tables:
            doc["inputs"] = {n: {"schema": s} for n, s in sorted(ctx.tables.items())}
        if ctx.aliases:
            body.pop("extension_urns", None)  # the registry rebuilds them
            body.pop("extensions", None)
        doc["plan"] = body
        try:
            text = dump(doc)
            reloaded = yaml.load(text, Loader=lower.StrictLoader)
            if canonical.fingerprint(lower.build_plan(reloaded)) == target:
                return doc, ctx
            attempts.append(f"level {level}: lowered to a different program")
        except Exception as e:
            attempts.append(f"level {level}: {type(e).__name__}: {e}")
    raise lower.CaseError("cannot render this plan faithfully: " + "; ".join(attempts))
