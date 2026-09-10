"""The checks a case must pass, one function each, so a harness can report them apart.

Every check is blocking. Each returns None when the case satisfies it, a string
describing the violation when it does not, and SKIP when it does not apply to this
kind of case -- an unresolved case is never scored against an expectation it is not
allowed to carry.

What is worth knowing before trusting a green run: `check_declarations` and
`check_schema` both go through the deriver, so they are one implementation and a
mistaken rule inside it would be reflected in both. The redundancy that does exist is
between the tool and the schema a human wrote in the case file, and it only fails to
catch a mistake when the author made the same one as the tool.
"""

import os
from collections import Counter

import yaml
from google.protobuf import json_format

from . import check_decl, deriver, lower, paths, render

SKIP = "skip"


class Case:
    """One authored case, lowered once and reused by every check."""

    def __init__(self, path, ext_dir):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.area = os.path.basename(os.path.dirname(path))
        self.ext_dir = ext_dir
        self.text = open(path).read()
        self.doc = lower.load_case(path)
        self.plan = lower.build_plan(self.doc)
        self.plan_dict = json_format.MessageToDict(self.plan)
        self.env = build_envelope(self.doc, self.plan)
        self.blob = self.env.SerializeToString(deterministic=True)

    @property
    def kind(self):
        return self.doc["kind"]

    @property
    def expect(self):
        return self.doc.get("expect")


def build_envelope(doc, plan):
    import substrait.test.relation_test_pb2 as rt

    env = rt.RelationTestCase()
    env.id = doc["id"]
    env.spec_ref = doc["spec_ref"]
    env.kind = rt.RelationTestCase.Kind.Value(doc["kind"])
    env.plan.CopyFrom(plan)
    for t in lower.build_tables(doc, rt.RelationTestCase.InputTable):
        env.tables.add().CopyFrom(t)
    expect = doc.get("expect")
    if expect:
        if isinstance(expect["schema"], str):
            env.expect.schema.CopyFrom(lower.parse_named_struct(expect["schema"]))
        else:
            lower.fill(env.expect.schema, expect["schema"], None, {}, "/expect/schema")
        if "rows" in expect:
            env.expect.rows.order = rt.RelationTestCase.RowSet.Order.Value(
                expect["rows"]["order"]
            )
            for row in expect["rows"]["values"]:
                s = env.expect.rows.values.add()
                for cell in row:
                    s.fields.append(lower.parse_literal(cell))
    return env


def shorthand(type_msg):
    """A protobuf Type in the checker's own vocabulary, so both sides are comparable."""
    return deriver.render(deriver.type_from_proto(json_format.MessageToDict(type_msg)))


# ------------------------------------------------------------------------- checks
ID_AREAS = None  # filled from the directory layout on first use


def check_identity(case):
    """The envelope must survive its own bytes, and must say what it is.

    A case whose `spec_ref` is empty pins nothing: it records an answer without
    recording the sentence the answer comes from, which is the whole difference between
    a conformance case and a regression test. An id that does not start with the
    directory the case lives in makes a consumer's report hard to trace back.
    """
    import substrait.test.relation_test_pb2 as rt

    back = rt.RelationTestCase()
    back.ParseFromString(case.blob)
    if back.SerializeToString(deterministic=True) != case.blob:
        return "the envelope does not round trip through its own bytes"
    if not case.env.id.strip():
        return "the case has no id"
    if case.env.id.split("/")[0] != case.area:
        return f"id {case.env.id!r} does not start with its area {case.area!r}"
    if len(case.env.id.split("/")) < 2:
        return f"id {case.env.id!r} should read area/case/aspect"
    if not case.env.spec_ref.strip():
        return "the case pins no spec_ref"
    if case.env.kind == rt.RelationTestCase.KIND_UNSPECIFIED:
        return "the case declares no kind"
    return None


def check_roundtrip(case):
    """The plan must survive a trip out to source and back unchanged.

    `render` raises unless the document it produces, serialised and reloaded, lowers to
    exactly the plan it was given, so this check is that every case in the corpus can be
    handed to a reviewer or a generator as source and not only as bytes. It is the check
    that fails when a plan uses a shape the authoring format cannot express, which is the
    point at which a case would otherwise start being quietly approximated.

    Source formatting and comments are deliberately not compared. What must not drift is
    the compiled bundle, and `check_drift` is what holds that.
    """
    from . import canonical

    doc, _ = render.render(case.plan, case.name)
    reloaded = lower.build_plan(yaml.load(render.dump(doc), Loader=lower.StrictLoader))
    if canonical.fingerprint(reloaded) != canonical.fingerprint(case.plan):
        return "the rendered source lowers to a different program"
    return None


def check_schema(case):
    """The independent deriver must reproduce the schema the author wrote.

    Only a positive case is scored this way. An unresolved case carries no expectation
    by definition, and an invalid plan has no derived schema worth agreeing with: the
    thing wrong with it is upstream of its output type.
    """
    if case.kind != "KIND_POSITIVE":
        return SKIP
    derived = deriver.derive(case.plan_dict, case.ext_dir)
    authored = [
        [shorthand(t)[0], getattr(t, t.WhichOneof("kind")).nullability == 1]
        for t in case.env.expect.schema.struct.types
    ]
    if derived != authored:
        return f"derived {derived} vs authored {authored}"
    return None


def check_unresolved(case):
    """An unresolved case carries no expectation: it is shipped, never scored."""
    if case.kind != "KIND_UNRESOLVED":
        return SKIP
    if case.expect:
        return "an unresolved case must carry no expectation"
    if not (case.doc.get("unresolved") or {}).get("issue"):
        return "an unresolved case must name what is unsettled"
    return None


def check_declarations(case):
    """Every declared output_type must equal the one the extension derives.

    algebra.proto requires it exactly, so a case carrying a false declaration is a
    case about something other than what it claims. An invalid-plan case is allowed
    to violate this, and is required to violate something -- see check_kind.
    """
    findings = check_decl.check(case.plan_dict, case.ext_dir)
    if findings and case.kind != "KIND_INVALID_PLAN":
        return str(findings[:2])
    return None


def check_kind(case):
    """A case claiming to be invalid must actually violate a stated validity rule."""
    if case.kind != "KIND_INVALID_PLAN":
        return SKIP
    if not check_decl.check(case.plan_dict, case.ext_dir):
        return "KIND_INVALID_PLAN but no plan-validity violation found"
    return None


def _cell_class(lit):
    return deriver.render(deriver.Deriver.literal_type(json_format.MessageToDict(lit)))[
        0
    ]


def _rowset(label, schema, structs):
    cols = [shorthand(t)[0] for t in schema.struct.types]
    required = [
        getattr(t, t.WhichOneof("kind")).nullability == 2 for t in schema.struct.types
    ]
    for i, st in enumerate(structs):
        if len(st.fields) != len(cols):
            return f"{label} row {i}: {len(st.fields)} cells for {len(cols)} columns"
        for j, lit in enumerate(st.fields):
            if lit.WhichOneof("literal_type") == "null":
                if required[j]:
                    return f"{label} row {i} cell {j}: null in a required column"
                continue
            got = _cell_class(lit)
            if got != cols[j]:
                return f"{label} row {i} cell {j}: {got} in a {cols[j]} column"
    return None


def check_rows(case):
    """Fixture and expected rows must conform to the schemas declared for them.

    The checker's own vocabulary decides what a literal is, so this is not the
    lowering agreeing with itself.
    """
    problems = []
    for t in case.env.tables:
        problems.append(_rowset(f"table {'.'.join(t.name)}", t.schema, t.rows))
    if case.expect and case.env.expect.HasField("rows"):
        problems.append(
            _rowset("expected", case.env.expect.schema, case.env.expect.rows.values)
        )
    problems = [p for p in problems if p]
    return "; ".join(problems[:2]) if problems else None


def check_vt_arity(case):
    """A virtual table's rows must have as many cells as its base_schema has columns.

    Whether a row's types have to match base_schema is the open question in
    substrait-io/substrait#1211 and is deliberately not decided here. How many
    columns a row has is not part of that question.
    """
    if case.kind != "KIND_POSITIVE":
        return SKIP

    def walk(rel, path="/"):
        which = rel.WhichOneof("rel_type")
        node = getattr(rel, which)
        if which == "read" and node.WhichOneof("read_type") == "virtual_table":
            want = len(node.base_schema.struct.types)
            for i, st in enumerate(node.virtual_table.expressions):
                if len(st.fields) != want:
                    return (
                        f"{path}read row {i}: {len(st.fields)} cells for {want} columns"
                    )
        for f, v in node.ListFields():
            if f.message_type and f.message_type.full_name == "substrait.Rel":
                for item in v if f.is_repeated else [v]:
                    got = walk(item, path + which + "/")
                    if got:
                        return got
        return None

    for pr in case.plan.relations:
        bad = walk(pr.root.input if pr.HasField("root") else pr.rel)
        if bad:
            return bad
    return None


def _name_count(t):
    """Depth-first named-field count, the rule Plan.Root.names must satisfy."""
    if t.WhichOneof("kind") == "struct":
        return 1 + sum(_name_count(x) for x in t.struct.types)
    return 1


def check_names(case):
    """Root names, when the plan has them, must match the expectation's columns.

    Root names are optional and some cases deliberately omit them, so their absence
    is not a failure. Their presence in a different count or a different order is.
    """
    if not case.expect or case.kind != "KIND_POSITIVE":
        return SKIP
    root_names = list(case.plan.relations[0].root.names) if case.plan.relations else []
    if not root_names:
        return SKIP
    want = list(case.env.expect.schema.names)
    needed = sum(_name_count(t) for t in case.env.expect.schema.struct.types)
    if len(root_names) != needed:
        return f"{len(root_names)} root names for a schema needing {needed}"
    if want and root_names[: len(want)] != want:
        return (
            f"expect.schema names {want} are not the plan's root names "
            f"{root_names[: len(want)]}"
        )
    return None


def check_drift(case, bundles=None):
    """The committed bundle must be the bytes this case compiles to today.

    A consumer reads the bundle, not the case file, so an out-of-date bundle is a
    corpus that tests something nobody wrote.
    """
    out = os.path.join(bundles or paths.bundles_dir(), case.area, case.name + ".pb")
    if not os.path.exists(out):
        return f"no committed bundle at {os.path.relpath(out, paths.RELATIONS)}"
    if open(out, "rb").read() != case.blob:
        return "the committed bundle differs from what the case compiles to"
    return None


CHECKS = [
    check_identity,
    check_roundtrip,
    check_schema,
    check_unresolved,
    check_declarations,
    check_kind,
    check_rows,
    check_vt_arity,
    check_names,
    check_drift,
]


# ----------------------------------------------------------------------- coverage
def _enum_name(msg, field):
    """The enum value's name, so the committed baseline reads as words not numbers."""
    enum = msg.DESCRIPTOR.fields_by_name[field].enum_type
    return enum.values_by_number[getattr(msg, field)].name


def coverage(plan, counter=None):
    """What this plan exercises, in the terms the ratchet is kept in."""
    counter = Counter() if counter is None else counter

    def walk(rel):
        which = rel.WhichOneof("rel_type")
        counter[f"rel:{which}"] += 1
        node = getattr(rel, which)
        if which in ("join", "hash_join", "merge_join", "nested_loop_join"):
            counter[f"join_type:{_enum_name(node, 'type')}"] += 1
        if which == "set":
            counter[f"set_op:{_enum_name(node, 'op')}"] += 1
        if which == "read":
            counter[f"read:{node.WhichOneof('read_type')}"] += 1
            if node.HasField("projection"):
                counter["read:projection"] += 1
        if node.HasField("common") and node.common.WhichOneof("emit_kind") == "emit":
            counter["emit"] += 1
        for f, v in node.ListFields():
            if f.message_type and f.message_type.full_name == "substrait.Rel":
                for item in v if f.is_repeated else [v]:
                    walk(item)

    for pr in plan.relations:
        walk(pr.root.input if pr.HasField("root") else pr.rel)
    return counter


def case_files(root=None):
    root = root or paths.cases_dir()
    out = []
    for area in sorted(os.listdir(root)):
        d = os.path.join(root, area)
        if os.path.isdir(d):
            out += [
                os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".yaml")
            ]
    return out
