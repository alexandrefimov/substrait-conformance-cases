"""A Substrait type, however it arrives, written the way the corpus writes one.

Types reach this file in two spellings. A plan carries the `Type` message as protobuf-JSON,
`{"decimal": {"precision": 11, "scale": 2, "nullability": "NULLABILITY_REQUIRED"}}`. An extension
file carries the type syntax of `site/docs/types/type_parsing.md`, `decimal<P,S>` or `i64?`. Both
become the same triple here, so the derivation rules below never have to know which one they got.

The rendering goes the other way, into the notation `expected.json` and the participant columns use:
`dec(11,2)`, `vchar(10)`, `str`, `i64?`. Parameterized types are written with the signature short
names of the extension docs, which is what the comparison in probe/check_expected.py already
normalizes every participant's spelling into.

The file is not called `types.py`, which is what it wants to be called, and the code still imports
it as `types`. `deriver/check.py` runs as a file, so its own directory goes first on the import
path, and a module named `types` sitting there shadows the standard library one that `json` and
`re` pull in on the way up. Python 3.14 resolved it anyway and 3.12 did not, so the repository was
green on a workstation and red in CI. Renaming the file fixes it wherever the module is imported
from; renaming it in the code would only have moved the trap.
"""
import re

# Type.kind at spec 0.102.0 (proto/substrait/type.proto), mapped to the name the same type class
# carries in the extension files. A kind absent here is one this deriver cannot read; it fails
# rather than guessing, because a type silently dropped would shorten a schema and the comparison
# would report the difference against the implementation instead of against this file.
PROTO_KIND = {
    "bool": "boolean", "i8": "i8", "i16": "i16", "i32": "i32", "i64": "i64",
    "fp32": "fp32", "fp64": "fp64", "string": "string", "binary": "binary", "date": "date",
    "intervalYear": "interval_year", "intervalDay": "interval_day",
    "intervalCompound": "interval_compound", "uuid": "uuid",
    "fixedChar": "fixedchar", "varchar": "varchar", "fixedBinary": "fixedbinary",
    "decimal": "decimal", "precisionTime": "precision_time",
    "precisionTimestamp": "precision_timestamp", "precisionTimestampTz": "precision_timestamp_tz",
    "struct": "struct", "list": "list", "map": "map",
}

# The integer parameters of each parameterized type class, in the order the type syntax declares
# them, beside the protobuf-JSON field each is read from.
INT_PARAMS = {
    "decimal": ("precision", "scale"),
    "varchar": ("length",), "fixedchar": ("length",), "fixedbinary": ("length",),
    "precision_time": ("precision",), "precision_timestamp": ("precision",),
    "precision_timestamp_tz": ("precision",),
}

# How a type class is written in the corpus notation when it differs from its own name.
SHORT = {"boolean": "bool", "string": "str", "binary": "vbin", "fixedchar": "fchar",
         "varchar": "vchar", "fixedbinary": "fbin", "decimal": "dec",
         "interval_year": "iyear", "interval_day": "iday", "interval_compound": "icompound",
         "precision_time": "pt"}


class Unsupported(Exception):
    """Something in the plan or the extension file this deriver does not read.

    Raised rather than answered: a guess here would be indistinguishable from a derivation in the
    comparison, which is the one thing this program exists to keep apart.
    """


class Type:
    """A type class, its parameters, and whether a value of it may be null.

    `params` holds integers for `decimal<P,S>` and friends and `Type`s for `struct`, `list` and
    `map`. `nullable` is a bool once a type is concrete; a signature type that carries no `?` is
    non-nullable, which is what the type syntax says the absence of the marker means.
    """
    __slots__ = ("name", "params", "nullable")

    def __init__(self, name, params=(), nullable=False):
        self.name, self.params, self.nullable = name, tuple(params), bool(nullable)

    def with_nullable(self, nullable):
        return Type(self.name, self.params, nullable)

    def __eq__(self, other):
        return (isinstance(other, Type) and self.name == other.name
                and self.params == other.params and self.nullable == other.nullable)

    def __hash__(self):
        return hash((self.name, self.params, self.nullable))

    def __repr__(self):
        return "Type(%s)" % render_field(self)


def from_plan(node):
    """One `Type` message of a plan, as protobuf-JSON.

    protobuf-JSON leaves out fields holding their default, so a `decimal` with scale 0 arrives
    without a `scale` key and an absent `nullability` is NULLABILITY_UNSPECIFIED. Unspecified is
    kept out: `type.proto` gives it no meaning, and reading it as either answer would put a
    nullability into the output that nothing in the plan said.
    """
    if not isinstance(node, dict) or len(node) != 1:
        raise Unsupported("a Type message with %d fields set" % len(node or ()))
    (kind, body), = node.items()
    if kind not in PROTO_KIND:
        raise Unsupported("type kind %r" % kind)
    name = PROTO_KIND[kind]
    nullability = body.get("nullability", "NULLABILITY_UNSPECIFIED")
    if nullability == "NULLABILITY_UNSPECIFIED":
        raise Unsupported("%s with unspecified nullability" % name)
    nullable = nullability == "NULLABILITY_NULLABLE"
    if name == "struct":
        return Type(name, [from_plan(t) for t in body.get("types", [])], nullable)
    if name == "list":
        return Type(name, [from_plan(body["type"])], nullable)
    if name == "map":
        return Type(name, [from_plan(body["key"]), from_plan(body["value"])], nullable)
    return Type(name, [int(body.get(f, 0)) for f in INT_PARAMS.get(name, ())], nullable)


def from_named_struct(node):
    """A `NamedStruct` - what ReadRel.base_schema and WriteRel.table_schema hold - as a column list.

    The names go with the struct rather than with the fields, and the comparison is over types and
    nullability alone, so they are read only to be counted: a schema whose names and types disagree
    in number is malformed, and saying so is more use than deriving from the half that parses.
    """
    names, struct = node.get("names", []), node.get("struct", {})
    fields = [from_plan(t) for t in struct.get("types", [])]
    if len(names) != len(fields):
        raise Unsupported("base schema with %d names over %d types" % (len(names), len(fields)))
    return fields


_TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*|\d+|[<>,?!]|\[\d+\])")


def parse(text):
    """A type written in the syntax of `site/docs/types/type_parsing.md`: `i64?`, `decimal<P1,S1>`.

    Used on extension files, where a parameter is a name rather than a value, so `decimal<P1,S1>`
    parses into a type whose params are the strings "P1" and "S1". Binding fills them in.
    """
    tokens, pos = _TOKEN.findall(text.strip()), [0]
    if "".join(tokens) != re.sub(r"\s+", "", text.strip()):
        raise Unsupported("type syntax %r" % text)

    def take():
        if pos[0] >= len(tokens):
            raise Unsupported("type syntax %r ends early" % text)
        pos[0] += 1
        return tokens[pos[0] - 1]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def one():
        name = take().lower()
        if name == "u" and peek() == "!":
            # A user-defined type is written `u!<name>`: extensions/index.md, Type Short Names.
            take()
            return Type("u!" + take().lower(), (), False)
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            raise Unsupported("type name %r in %r" % (name, text))
        nullable = False
        if peek() == "?":
            take()
            nullable = True
        if peek() is not None and peek().startswith("["):
            take()  # a type variation: not part of the type class this comparison reads
        params = []
        if peek() == "<":
            take()
            while True:
                params.append(_param(peek()) if _is_int_param(name) else one())
                nxt = take()
                if nxt == ">":
                    break
                if nxt != ",":
                    raise Unsupported("type syntax %r" % text)
        return Type(name, params, nullable)

    def _param(_):
        token = take()
        return int(token) if token.isdigit() else token

    parsed = one()
    if pos[0] != len(tokens):
        raise Unsupported("trailing text in type syntax %r" % text)
    return parsed


def _is_int_param(name):
    """Whether this type class's parameters are integers rather than nested types."""
    return name in INT_PARAMS


def render(t):
    """The corpus notation for a type, without its nullability: `dec(11,2)`, `struct(i64,str?)`."""
    if t.name == "struct":
        return "struct(%s)" % ",".join(render_field(f) for f in t.params)
    if t.name in ("list", "map"):
        return "%s(%s)" % (t.name, ",".join(render_field(f) for f in t.params))
    base = SHORT.get(t.name, t.name)
    return "%s(%s)" % (base, ",".join(str(p) for p in t.params)) if t.params else base


def render_field(t):
    """A column: its type, with `?` when it may be null. This is how a schema is written."""
    return render(t) + ("?" if t.nullable else "")


def render_schema(fields):
    """A whole output schema, in the bracketed form the probe columns print."""
    return "[%s]" % ", ".join(render_field(f) for f in fields)
