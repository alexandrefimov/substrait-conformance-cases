"""The output schema of a relation, derived from the plan and the specification text.

    python3 -m deriver.derive <plan.json>        # the schema of each root in the plan

Each rule below quotes the sentence it implements, from the Substrait documentation at v0.102.0:
`site/docs/relations/logical_relations.md` and `physical_relations.md` for the relations,
`common_fields.md` for emit. Where the text leaves something open the code says so at the point
where it had to choose, and deriver/README.md collects those places; they are the reason for
writing this rather than the cost of it.

Two things this file deliberately does not do. It never reads a declared `output_type`: a function
call's return type is derived from the extension file in deriver/extensions.py, so that an answer
here cannot be the plan's own declaration handed back. And it derives types only - no rows, no
names - because that is what the corpus compares.
"""
import json, os, sys

from . import extensions, types
from .types import Type, Unsupported

# The i32 column Aggregate and Expand append. Neither page states its nullability; the value is the
# index of a grouping set or of a duplicate, which every row of the output has, so it is written
# here as required. Nothing in the corpus contradicts that, and nothing in the spec confirms it.
INDEX_COLUMN = Type("i32", (), False)


class Plan:
    """A plan and the extension declarations its calls point at."""

    def __init__(self, doc):
        self.doc = doc
        urns = {u.get("extensionUrnAnchor", 0): u["urn"] for u in doc.get("extensionUrns", [])}
        self.functions = {}
        for e in doc.get("extensions", []):
            f = e.get("extensionFunction")
            if f is None:
                continue
            anchor = f.get("extensionUrnReference", 0)
            if anchor not in urns:
                raise Unsupported("function %r points at urn anchor %s, which the plan does not "
                                  "declare" % (f.get("name"), anchor))
            self.functions[f.get("functionAnchor", 0)] = (urns[anchor], f["name"])

    def declaration(self, reference):
        if reference not in self.functions:
            raise Unsupported("no extension declares function anchor %s" % reference)
        return self.functions[reference]


def schema_of(doc):
    """The output schema of the plan's first root relation, as a list of columns."""
    plan = Plan(doc)
    roots = [r["root"] for r in doc.get("relations", []) if "root" in r]
    if not roots:
        raise Unsupported("the plan has no root relation")
    return rel_schema(roots[0]["input"], plan)


def rel_schema(node, plan):
    """The output schema of one relation: its direct output order, then its emit mapping."""
    if not isinstance(node, dict) or len(node) != 1:
        raise Unsupported("a Rel with %d fields set" % len(node or ()))
    (kind, rel), = node.items()
    rule = RULES.get(kind)
    if rule is None:
        raise Unsupported("relation %r" % kind)
    return _emit(rule(rel, plan), rel.get("common"), kind)


def _emit(fields, common, kind):
    """Apply RelCommon.Emit.

    "A relation which has a direct emit kind outputs the relation's output without reordering or
    selection. A relation that specifies an emit output mapping can output its output columns in
    any order and may leave output columns out." An unset emit_kind, and an absent common section,
    are Direct - common_fields.md says both in as many words.
    """
    if not common or "emit" not in common:
        return fields
    mapping = common["emit"].get("outputMapping", [])
    for i in mapping:
        if not 0 <= i < len(fields):
            raise Unsupported("%s emits column %d of %d" % (kind, i, len(fields)))
    return [fields[i] for i in mapping]


# ---------------------------------------------------------------- expressions

def expr_type(node, input_fields, plan):
    """The type of one Expression over an input whose columns are `input_fields`."""
    if not isinstance(node, dict) or len(node) != 1:
        raise Unsupported("an Expression with %d fields set" % len(node or ()))
    (kind, body), = node.items()
    if kind == "selection":
        return _selection(body, input_fields)
    if kind == "literal":
        return _literal(body)
    if kind == "scalarFunction":
        return _call(body, input_fields, plan, "scalar")
    if kind == "cast":
        return types.from_plan(body["type"])
    raise Unsupported("expression %r" % kind)


def _selection(body, input_fields):
    """A FieldReference into the input record.

    Only a direct reference from the root is read. An outer reference belongs to a relation none of
    these plans use, and a masked reference selects several fields at once, which is not one column
    and so not one expression type.
    """
    if "rootReference" not in body:
        raise Unsupported("a field reference that is not rooted in the input record")
    segment = body.get("directReference")
    if segment is None:
        raise Unsupported("a masked field reference")
    t = None
    fields = input_fields
    while segment:
        (seg, spec), = segment.items()
        if seg != "structField":
            raise Unsupported("reference segment %r" % seg)
        i = spec.get("field", 0)
        if fields is None or not 0 <= i < len(fields):
            raise Unsupported("field %d of %s" % (i, "a non-struct" if fields is None
                                                  else "%d" % len(fields)))
        t = fields[i]
        fields = t.params if t.name == "struct" else None
        segment = spec.get("child")
    return t


def _literal(body):
    """A Literal: its type class is the field that is set, its nullability the `nullable` flag."""
    kinds = [k for k in body if k not in ("nullable", "typeVariationReference")]
    if len(kinds) != 1:
        raise Unsupported("a Literal with %d type fields set" % len(kinds))
    (kind,) = kinds
    if kind == "null":
        # "a typed null literal ... must be nullable by definition"
        return types.from_plan(body["null"]).with_nullable(True)
    nullable = bool(body.get("nullable", False))
    if kind == "decimal":
        d = body["decimal"]
        return Type("decimal", (int(d.get("precision", 0)), int(d.get("scale", 0))), nullable)
    if kind in ("fixedChar", "varChar", "fixedBinary"):
        written = {"fixedChar": "fixedchar", "varChar": "varchar",
                   "fixedBinary": "fixedbinary"}[kind]
        value = body[kind]
        length = (len(value) if isinstance(value, str)
                  else int(value.get("length", len(value.get("value", "")))))
        return Type(written, (length,), nullable)
    simple = {"boolean": "boolean", "i8": "i8", "i16": "i16", "i32": "i32", "i64": "i64",
              "fp32": "fp32", "fp64": "fp64", "string": "string", "binary": "binary",
              "date": "date", "uuid": "uuid"}
    if kind in simple:
        return Type(simple[kind], (), nullable)
    raise Unsupported("literal of type %r" % kind)


def _call(body, input_fields, plan, kind):
    """A function call: bind the extension declaration and derive its return type from it.

    `output_type` is beside every one of these in the plan and is not read. algebra.proto says what
    that field is - "Must be set to the return type of the function, exactly as derived using the
    declaration in the extension" - so deriving it is the only way to have anything to check it
    against.
    """
    urn, name = plan.declaration(body.get("functionReference", 0))
    args = []
    for arg in body.get("arguments", []):
        if "value" not in arg:
            raise Unsupported("a %s argument that is not a value" % name)
        args.append(expr_type(arg["value"], input_fields, plan))
    impl = extensions.library().lookup(urn, name)
    phase = body.get("phase", "AGGREGATION_PHASE_INITIAL_TO_RESULT")
    if kind == "scalar":
        return extensions.return_type(impl, args)
    return extensions.return_type(impl, args, phase)


# ------------------------------------------------------------------ relations

def _read(rel, plan):
    """Read: "Defaults to the schema of the data read after the optional projection ... is applied."

    The schema is ReadRel.base_schema, the Direct Schema the properties table calls "the schema of
    the output of the read (before any projection or emit remapping/hiding)". A virtual table's
    literals are not consulted: the read's own declaration is what the page points at, and whether
    a row literal may disagree with it is a separate question this corpus keeps open.
    """
    if "baseSchema" not in rel:
        raise Unsupported("a read with no base schema")
    fields = types.from_named_struct(rel["baseSchema"])
    if "projection" in rel:
        fields = _mask(rel["projection"], fields)
    return fields


def _mask(mask, fields):
    """ReadRel.projection, a MaskExpression over the direct schema.

    algebra.proto calls a mask "a reference that takes an existing subtype and selectively removes
    fields from it" and adds that it "does not fundamentally alter the structure of data beyond the
    elimination of unnecessary elements". Removal, not reordering: the fields keep the order of the
    schema they were selected from. A mask that lists its items out of order would make the two
    readings differ, and there is nothing in the text to decide between them, so such a mask stops
    the run instead of being answered under one of them.
    """
    items = mask.get("select", {}).get("structItems", [])
    picked = [i.get("field", 0) for i in items]
    if any("child" in i for i in items):
        raise Unsupported("a projection mask that reaches into a nested field")
    if picked != sorted(picked):
        raise Unsupported("a projection mask listing fields out of order: %s" % picked)
    for i in picked:
        if not 0 <= i < len(fields):
            raise Unsupported("projection selects field %d of %d" % (i, len(fields)))
    return [fields[i] for i in picked]


def _passthrough(field):
    """Filter, Sort, Fetch and Top-N: "The field order of the input", "Unchanged from input"."""
    def rule(rel, plan):
        return rel_schema(rel[field], plan)
    return rule


def _project(rel, plan):
    """Project: "The field order of the input + the list of new expressions in the order they are
    declared in the expressions list."
    """
    fields = rel_schema(rel["input"], plan)
    return fields + [expr_type(e, fields, plan) for e in rel.get("expressions", [])]


def _cross(rel, plan):
    """Cross product: "The input order is the left input followed by the right input", and the
    direct output order is the same as the input order. Nothing about nullability changes: every
    record is paired, so no side is filled with nulls."""
    return rel_schema(rel["left"], plan) + rel_schema(rel["right"], plan)


# The Join Types table of logical_relations.md, read one row at a time. Each entry says which side
# reaches the output and which side is filled with nulls for non-matching records. The direct
# output order is "the same as Input Order" - left then right - except for the semi, anti and mark
# joins, which the same row of the signature table singles out.
JOIN_TYPES = {
    # "For each cross input match, return a record including the data from both sides."
    "JOIN_TYPE_INNER": ("both", ()),
    # "For any remaining non-match records, return the record from the corresponding input along
    # with nulls for the opposite input."
    "JOIN_TYPE_OUTER": ("both", ("left", "right")),
    # "For any remaining non-matching records from the left input, return the left record along
    # with nulls for the right input."
    "JOIN_TYPE_LEFT": ("both", ("right",)),
    "JOIN_TYPE_RIGHT": ("both", ("left",)),
    # "Return all records from the left input with no join expansion. ... For any left records
    # without matching right records, return the left record along with nulls for the right input."
    "JOIN_TYPE_LEFT_SINGLE": ("both", ("right",)),
    "JOIN_TYPE_RIGHT_SINGLE": ("both", ("left",)),
    # "Returns records from the left input." - one side only, and the signature table repeats it:
    # "For semi joins and anti joins, the emit order is either left or right only."
    "JOIN_TYPE_LEFT_SEMI": ("left", ()),
    "JOIN_TYPE_RIGHT_SEMI": ("right", ()),
    "JOIN_TYPE_LEFT_ANTI": ("left", ()),
    "JOIN_TYPE_RIGHT_ANTI": ("right", ()),
    # "Appends one additional "mark" column to the output of the join. The new column will be
    # listed after all columns from left side and will be of type nullable boolean."
    "JOIN_TYPE_LEFT_MARK": ("left+mark", ()),
    "JOIN_TYPE_RIGHT_MARK": ("right+mark", ()),
}
MARK_COLUMN = Type("boolean", (), True)


def _join(rel, plan):
    """Every join relation, logical and physical.

    HashJoinRel, MergeJoinRel and NestedLoopJoinRel each say "Same as the Join operator" for both
    input order and direct output order, and take their join types from it, so one rule serves all
    four. The enum numbers differ between JoinRel and NestedLoopJoinRel, which matters not at all
    here: a protobuf-JSON plan carries the name.
    """
    left = rel_schema(rel["left"], plan)
    right = rel_schema(rel["right"], plan)
    kind = rel.get("type", "JOIN_TYPE_UNSPECIFIED")
    if kind not in JOIN_TYPES:
        raise Unsupported("join type %r" % kind)
    sides, nulled = JOIN_TYPES[kind]
    if "left" in nulled:
        left = [f.with_nullable(True) for f in left]
    if "right" in nulled:
        right = [f.with_nullable(True) for f in right]
    return {"both": left + right, "left": left, "right": right,
            "left+mark": left + [MARK_COLUMN], "right+mark": right + [MARK_COLUMN]}[sides]


# The Output Nullability column of the Set Operation Types table. Each is transcribed as the rule
# it states, not as the row of the worked example below it, so the example stays available as a
# check on the reading rather than as its source.
def _set_nullability(op, per_input):
    primary, secondary = per_input[0], per_input[1:]
    if op in ("SET_OP_MINUS_PRIMARY", "SET_OP_MINUS_PRIMARY_ALL", "SET_OP_MINUS_MULTISET"):
        return primary                                          # "The same as the primary input."
    if op == "SET_OP_INTERSECTION_PRIMARY":
        # "If a field is nullable in the primary input and in any of the secondary inputs, it is
        # nullable in the output."
        return primary and any(secondary)
    if op in ("SET_OP_INTERSECTION_MULTISET", "SET_OP_INTERSECTION_MULTISET_ALL"):
        # "If a field is required in any of the inputs, it is required in the output."
        return all(per_input)
    if op in ("SET_OP_UNION_DISTINCT", "SET_OP_UNION_ALL"):
        # "If a field is nullable in any of the inputs, it is nullable in the output."
        return any(per_input)
    raise Unsupported("set operation %r" % op)


def _set(rel, plan):
    """Set: "The field order of the inputs. All inputs must have identical field *types*, but field
    nullabilities may vary."

    The type class therefore comes from the primary input and the nullability from the table above.
    A disagreement between the inputs about anything but nullability is what that sentence forbids,
    so it is reported rather than resolved in favour of the primary.
    """
    inputs = [rel_schema(i, plan) for i in rel.get("inputs", [])]
    if len(inputs) < 2:
        raise Unsupported("a set relation with %d inputs" % len(inputs))
    op = rel.get("op", "SET_OP_UNSPECIFIED")
    width = len(inputs[0])
    if any(len(i) != width for i in inputs):
        raise Unsupported("set inputs of widths %s" % [len(i) for i in inputs])
    out = []
    for column in range(width):
        column_types = [i[column] for i in inputs]
        shapes = {(t.name, t.params) for t in column_types}
        if len(shapes) != 1:
            raise Unsupported("set inputs declare %s for column %d" %
                              (sorted(types.render(t) for t in column_types), column))
        out.append(column_types[0].with_nullable(_set_nullability(op, [t.nullable for t in
                                                                      column_types])))
    return out


def _aggregate(rel, plan):
    """Aggregate: "The list of grouping expressions in declaration order followed by the list of
    measures in declaration order, followed by an `i32` describing the associated particular
    grouping set the value is derived from (if applicable)."

    Two further sentences on the same page give the rest. "The columns for grouping expressions
    that do *not* appear in *all* grouping sets will be nullable (regardless of the nullability of
    the type returned by the grouping expression)". And: "an aggregate relation with more than one
    grouping set receives an extra `i32` column on the right-hand side" - which is what the "(if
    applicable)" above refers to.
    """
    fields = rel_schema(rel["input"], plan)
    groupings = rel.get("groupings", [])
    expressions = rel.get("grouping_expressions", rel.get("groupingExpressions", []))
    out = []
    for i, e in enumerate(expressions):
        t = expr_type(e, fields, plan)
        in_every_set = all(i in g.get("expressionReferences", []) for g in groupings)
        out.append(t if in_every_set else t.with_nullable(True))
    for m in rel.get("measures", []):
        out.append(_call(m["measure"], fields, plan, "aggregate"))
    if len(groupings) > 1:
        out.append(INDEX_COLUMN)
    if not out:
        raise Unsupported("an aggregate relation yielding zero columns")
    return out


def _window(rel, plan):
    """Consistent partition window: "Same as Project operator (input followed by each window
    expression)." The functions are declared in ConsistentPartitionWindowRel.window_functions and
    are bound like any other call.
    """
    fields = rel_schema(rel["input"], plan)
    calls = rel.get("windowFunctions", [])
    if not calls:
        raise Unsupported("a window relation with no window functions")
    return fields + [_call(c, fields, plan, "window") for c in calls]


def _expand(rel, plan):
    """Expand: "The expand fields followed by an i32 column describing the index of the duplicate
    that the row is derived from."

    That order carries no condition, unlike Aggregate's index column on the same page, so the
    column is appended for every expand. A switching field's type comes from algebra.proto: "All
    duplicates must return the same type class but may differ in nullability. The effective type of
    the output field will be nullable if any of the duplicate expressions are nullable."
    """
    fields = rel_schema(rel["input"], plan)
    declared = rel.get("fields", [])
    out = []
    for f in declared:
        if "consistentField" in f:
            out.append(expr_type(f["consistentField"], fields, plan))
        elif "switchingField" in f:
            duplicates = [expr_type(e, fields, plan)
                          for e in f["switchingField"].get("duplicates", [])]
            if not duplicates:
                raise Unsupported("a switching field with no duplicates")
            shapes = {(t.name, t.params) for t in duplicates}
            if len(shapes) != 1:
                raise Unsupported("a switching field over %s" %
                                  sorted(types.render(t) for t in duplicates))
            out.append(duplicates[0].with_nullable(any(t.nullable for t in duplicates)))
        else:
            raise Unsupported("an expand field that is neither switching nor consistent")
    # "There should be one definition here for each input field. Any fields beyond the provided
    # definitions will be emitted as is."
    out.extend(fields[len(declared):])
    return out + [INDEX_COLUMN]


def _write(rel, plan):
    """Write: "Unchanged from input".

    What a write outputs at all depends on its output mode, and the page says so - "Output depends
    on OutputMode (none, or modified records)" - but the order and types of whatever it does output
    are the input's. `table_schema` is the schema of the table being written, which the page
    requires the input to match; it is not read here, because reading it would answer with the
    declaration instead of with the input, and the difference between the two is a case in this
    corpus.
    """
    return rel_schema(rel["input"], plan)


RULES = {
    "read": _read,
    "filter": _passthrough("input"),
    "sort": _passthrough("input"),
    "fetch": _passthrough("input"),
    "topN": _passthrough("input"),
    "project": _project,
    "cross": _cross,
    "join": _join,
    "hashJoin": _join,
    "mergeJoin": _join,
    "nestedLoopJoin": _join,
    "set": _set,
    "aggregate": _aggregate,
    "window": _window,
    "expand": _expand,
    "write": _write,
}


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    doc = json.load(open(argv[1], encoding="utf-8"))
    try:
        print(types.render_schema(schema_of(doc)))
    except Unsupported as why:
        print("not derived: %s" % why, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
