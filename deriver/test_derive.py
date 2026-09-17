"""Checks the parts of the deriver that the corpus does not reach, or reaches only one way.

    python3 deriver/test_derive.py

Two things here are not covered by running the 98 cases. The return type expression evaluator is
exercised by five decimal cases, all of which use the same four formulas, so an operator precedence
it gets wrong in a way those formulas do not notice would never show. And the relation rules are
each reached by the cases that exist: a join type the corpus has no case for, or a set operation
over three inputs of differing nullability, is only asserted here.

These are unit checks against the rules as this deriver states them, not against the corpus. They
cannot show that a rule matches the specification; only the comparison in deriver/check.py does
that, and only for the readings both it and probe/expected.py happen to share.
"""
import sys

from deriver import derive, extensions, types
from deriver.types import Type, Unsupported

FAILED = []


def check(label, got, want):
    if got != want:
        FAILED.append("%s: got %r, want %r" % (label, got, want))


def evaluate(text, **bound):
    """The evaluator on its own, with parameters bound by name."""
    return types.render_field(extensions._expression(text, bound))


def test_expression_language():
    # Precedence: an additive expression is compared, then the comparison chooses. Read the other
    # way round - the ternary binding tighter than `>` - `init_prec > 38 ? a : b` silently becomes
    # a comparison against a number that is always truthy, and every wide decimal comes out wrong.
    check("ternary after comparison", evaluate("p = a + 1 > 3 ? 7 : 9\nDECIMAL<p,0>", a=3),
          "dec(7,0)")
    check("ternary else branch", evaluate("p = a > 3 ? 7 : 9\nDECIMAL<p,0>", a=1), "dec(9,0)")
    check("multiplication before addition", evaluate("p = a + b * 2\nDECIMAL<p,0>", a=1, b=3),
          "dec(7,0)")
    check("parentheses", evaluate("p = (a + b) * 2\nDECIMAL<p,0>", a=1, b=3), "dec(8,0)")
    check("min and max nest", evaluate("p = max(min(a, 6), 2)\nDECIMAL<p,0>", a=4), "dec(4,0)")
    check("subtraction is left associative", evaluate("p = a - b - 1\nDECIMAL<p,0>", a=10, b=3),
          "dec(6,0)")
    check("unary minus", evaluate("p = max(-a, 0)\nDECIMAL<p,0>", a=5), "dec(0,0)")
    check("integer division truncates", evaluate("p = a / 2\nDECIMAL<p,0>", a=7), "dec(3,0)")
    # Toward zero rather than toward minus infinity. The two agree on every positive numerator, so
    # a negative one is the only thing that says which was implemented - and the spec says neither,
    # which is why the choice is asserted here rather than left to be discovered.
    check("integer division truncates toward zero",
          evaluate("p = a / 2 + 4\nDECIMAL<p,0>", a=-7), "dec(1,0)")
    check("a later line sees an earlier one",
          evaluate("x = a + 1\ny = x * 2\nDECIMAL<y,x>", a=1), "dec(4,2)")
    # A name the expression never computes must stop the run: filled with a zero, it would produce
    # a plausible width nothing in the plan asked for.
    try:
        evaluate("DECIMAL<nowhere,0>")
        FAILED.append("an unbound parameter in a return expression was accepted")
    except Unsupported:
        pass


def test_type_syntax():
    for written, rendered in [("i64?", "i64?"), ("boolean", "bool"), ("varchar<10>", "vchar(10)"),
                              ("STRUCT<i64,i64>", "struct(i64,i64)"), ("decimal<38,9>", "dec(38,9)"),
                              ("list<i32?>", "list(i32?)"), ("u!geometry", "u!geometry")]:
        check("type syntax %s" % written, types.render_field(types.parse(written)), rendered)
    # Nullability is never guessed: type.proto gives NULLABILITY_UNSPECIFIED no meaning, and a plan
    # that leaves it out has not said which the column is.
    try:
        types.from_plan({"i64": {}})
        FAILED.append("a type with unspecified nullability was read as an answer")
    except Unsupported:
        pass


def read(*columns):
    """A ReadRel over the given columns, written as the type syntax."""
    return {"read": {"baseSchema": {
        "names": ["c%d" % i for i in range(len(columns))],
        "struct": {"types": [_proto(types.parse(c)) for c in columns],
                   "nullability": "NULLABILITY_REQUIRED"}}}}


def _proto(t):
    kind = {"boolean": "bool", "string": "string"}.get(t.name, t.name)
    body = {"nullability": "NULLABILITY_NULLABLE" if t.nullable else "NULLABILITY_REQUIRED"}
    if t.name == "decimal":
        body["precision"], body["scale"] = t.params
    return {kind: body}


def schema(rel):
    return types.render_schema(derive.rel_schema(rel, derive.Plan({})))


def test_join_types():
    left, right = read("i64", "i64?"), read("i64", "i64?")
    want = {
        "JOIN_TYPE_INNER": "[i64, i64?, i64, i64?]",
        "JOIN_TYPE_OUTER": "[i64?, i64?, i64?, i64?]",
        "JOIN_TYPE_LEFT": "[i64, i64?, i64?, i64?]",
        "JOIN_TYPE_RIGHT": "[i64?, i64?, i64, i64?]",
        "JOIN_TYPE_LEFT_SINGLE": "[i64, i64?, i64?, i64?]",
        "JOIN_TYPE_RIGHT_SINGLE": "[i64?, i64?, i64, i64?]",
        "JOIN_TYPE_LEFT_SEMI": "[i64, i64?]",
        "JOIN_TYPE_RIGHT_SEMI": "[i64, i64?]",
        "JOIN_TYPE_LEFT_ANTI": "[i64, i64?]",
        "JOIN_TYPE_RIGHT_ANTI": "[i64, i64?]",
        "JOIN_TYPE_LEFT_MARK": "[i64, i64?, bool?]",
        "JOIN_TYPE_RIGHT_MARK": "[i64, i64?, bool?]",
    }
    # Every join type algebra.proto declares has a row here, so a type added upstream arrives as a
    # missing key rather than as a case nobody wrote.
    declared = set(derive.JOIN_TYPES)
    check("every join type is asserted", sorted(want), sorted(declared))
    for kind, expected in want.items():
        check("join %s" % kind,
              schema({"join": {"left": left, "right": right, "type": kind}}), expected)
    # The physical joins say "Same as the Join operator" for both orders, so they must answer the
    # same thing over the same inputs.
    for rel in ("hashJoin", "mergeJoin", "nestedLoopJoin"):
        check("%s follows the join rule" % rel,
              schema({rel: {"left": left, "right": right, "type": "JOIN_TYPE_LEFT"}}),
              want["JOIN_TYPE_LEFT"])


def test_set_operations():
    # The worked example on the spec page, over three inputs: the one place the table's wording and
    # its example can disagree, and the deriver reads the wording.
    pattern = [("i64", "i64", "i64"), ("i64", "i64", "i64?"), ("i64", "i64?", "i64"),
               ("i64", "i64?", "i64?"), ("i64?", "i64", "i64"), ("i64?", "i64", "i64?"),
               ("i64?", "i64?", "i64"), ("i64?", "i64?", "i64?")]
    inputs = [read(*[row[i] for row in pattern]) for i in range(3)]
    want = {
        "SET_OP_MINUS_PRIMARY": "RRRRNNNN", "SET_OP_MINUS_PRIMARY_ALL": "RRRRNNNN",
        "SET_OP_MINUS_MULTISET": "RRRRNNNN", "SET_OP_INTERSECTION_PRIMARY": "RRRRRNNN",
        "SET_OP_INTERSECTION_MULTISET": "RRRRRRRN",
        "SET_OP_INTERSECTION_MULTISET_ALL": "RRRRRRRN",
        "SET_OP_UNION_DISTINCT": "RNNNNNNN", "SET_OP_UNION_ALL": "RNNNNNNN",
    }
    for op, expected in want.items():
        got = schema({"set": {"inputs": inputs, "op": op}})
        check("set %s" % op, "".join("N" if f.endswith("?") else "R"
                                     for f in got[1:-1].split(", ")), expected)
    # "All inputs must have identical field types" - a disagreement about anything but nullability
    # is what that sentence forbids, and resolving it in favour of the primary would hide it.
    try:
        schema({"set": {"inputs": [read("i64"), read("i32")], "op": "SET_OP_UNION_ALL"}})
        FAILED.append("a set over differing field types was answered rather than reported")
    except Unsupported:
        pass


def test_emit_and_passthrough():
    body = read("i64", "string", "boolean")
    check("emit reorders and drops",
          schema({"filter": {"input": body, "common": {"emit": {"outputMapping": [2, 0]}}}}),
          "[bool, i64]")
    check("an unset emit kind is direct",
          schema({"filter": {"input": body, "common": {}}}), "[i64, str, bool]")
    check("an absent common section is direct",
          schema({"filter": {"input": body}}), "[i64, str, bool]")
    try:
        schema({"filter": {"input": body, "common": {"emit": {"outputMapping": [3]}}}})
        FAILED.append("an emit mapping past the end of the relation was accepted")
    except Unsupported:
        pass


def main():
    for test in (test_expression_language, test_type_syntax, test_join_types,
                 test_set_operations, test_emit_and_passthrough):
        test()
    for line in FAILED:
        print("FAILED: %s" % line)
    if not FAILED:
        print("ok      the deriver's return type expressions and relation rules hold on their own")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
