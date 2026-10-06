"""Checks the call typing in deriver/calls.py on plans and declarations written here.

    python3 -m deriver.test_calls        # also run by probe/selfcheck.sh
    python3 -m pytest deriver -q

Every plan below is built in the test, and so is the extension file it names: a few functions shaped
like the ones in the Substrait files, small enough that each expected type can be worked out by
hand from the rule the test is about. That keeps the binding rules checkable without a Substrait
checkout. The last two tests use the real files and the corpus, and run only when SUBSTRAIT_DIR
names a checkout.
"""
import os, sys

from deriver import calls, extensions, type_model as types

URN = "extension:test:functions"

# A multiplication's decimal program, in the multi-line form the Substrait files use.
DECIMAL_PROGRAM = """init_scale = S1 + S2
init_prec = P1 + P2 + 1
min_scale = min(init_scale, 6)
delta = init_prec - 38
prec = min(init_prec, 38)
scale_after_borrow = max(init_scale - delta, min_scale)
scale = init_prec > 38 ? scale_after_borrow : init_scale
DECIMAL<prec, scale>"""

DOC = {
    "urn": URN,
    "scalar_functions": [
        {"name": "add", "impls": [
            {"args": [{"value": "i32"}, {"value": "i32"}], "return": "i32"},
            {"args": [{"value": "i64"}, {"value": "i64"}], "return": "i64"}]},
        {"name": "multiply", "impls": [
            {"args": [{"value": "decimal<P1,S1>"}, {"value": "decimal<P2,S2>"}],
             "return": DECIMAL_PROGRAM}]},
        {"name": "is_null", "impls": [
            {"args": [{"value": "any1"}], "nullability": "DECLARED_OUTPUT",
             "return": "boolean"}]},
        {"name": "g2", "impls": [
            {"args": [{"value": "any1"}, {"value": "any1?"}], "nullability": "DISCRETE",
             "return": "any1?"}]},
        {"name": "concat", "impls": [
            {"args": [{"value": "varchar<L1>"}], "variadic": {"min": 1},
             "return": "varchar<L1>"},
            {"args": [{"value": "string"}], "variadic": {"min": 1}, "return": "string"}]},
        {"name": "coalesce", "impls": [
            {"args": [{"value": "any1"}], "variadic": {"min": 2}, "return": "any1"}]},
        {"name": "extract", "impls": [
            {"args": [{"options": ["YEAR", "MONTH"]}, {"value": "date"}], "return": "i64"}]},
        {"name": "wrap", "impls": [
            {"args": [{"value": "any1"}], "nullability": "DECLARED_OUTPUT",
             "return": "LIST?<any>"}]},
    ],
    "aggregate_functions": [
        {"name": "count", "impls": [
            {"args": [], "nullability": "DECLARED_OUTPUT", "decomposable": "MANY",
             "intermediate": "i64", "return": "i64"},
            {"args": [{"value": "any"}], "nullability": "DECLARED_OUTPUT",
             "decomposable": "MANY", "intermediate": "i64", "return": "i64"}]},
        {"name": "avg", "impls": [
            {"args": [{"value": "fp64"}], "nullability": "DECLARED_OUTPUT",
             "decomposable": "MANY", "intermediate": "STRUCT<fp64,i64>", "return": "fp64?"}]},
        {"name": "std_dev", "impls": [
            {"args": [{"options": ["SAMPLE", "POPULATION"]}, {"value": "fp64"}],
             "nullability": "DECLARED_OUTPUT", "return": "fp64?"}]},
    ],
    "window_functions": [
        {"name": "rank", "impls": [
            {"args": [], "nullability": "DECLARED_OUTPUT", "decomposable": "NONE",
             "return": "i64?"}]},
    ],
}


def given():
    """The test file above, in place of the extension files, until the next call to given()."""
    extensions._LIBRARY[0] = extensions.Library(docs={URN: DOC})


# ------------------------------------------------------------------ plans, built by hand

def _proto(t):
    kind = {"boolean": "bool", "precision_timestamp": "precisionTimestamp"}.get(t.name, t.name)
    body = {"nullability": "NULLABILITY_NULLABLE" if t.nullable else "NULLABILITY_REQUIRED"}
    for name, value in zip(types.INT_PARAMS.get(t.name, ()), t.params):
        body[name] = value
    if t.name == "struct":
        body["types"] = [_proto(p) for p in t.params]
    return {kind: body}


def read(*columns):
    return {"read": {"baseSchema": {
        "names": ["c%d" % i for i in range(len(columns))],
        "struct": {"types": [_proto(types.parse(c)) for c in columns],
                   "nullability": "NULLABILITY_REQUIRED"}},
        "namedTable": {"names": ["t"]}}}


def field(i):
    return {"selection": {"directReference": {"structField": {"field": i}}, "rootReference": {}}}


def fn(anchor, *args, **extra):
    """A scalar function call; an argument that is a str is an enumeration."""
    body = {"functionReference": anchor,
            "arguments": [{"enum": a} if isinstance(a, str) else {"value": a} for a in args]}
    body.update(extra)
    return {"scalarFunction": body}


def project(rel, *expressions):
    return {"project": {"input": rel, "expressions": list(expressions)}}


def plan(names, rel, urn=URN):
    """A plan declaring `names` at anchors 1, 2, ... under `urn`, with `rel` as its root."""
    return {"extensionUrns": [{"extensionUrnAnchor": 1, "urn": urn}],
            "extensions": [{"extensionFunction": {"extensionUrnReference": 1,
                                                  "functionAnchor": i + 1, "name": n}}
                           for i, n in enumerate(names)],
            "relations": [{"root": {"input": rel}}]}


def records(doc):
    return calls.derive_calls(doc)


def one(doc):
    found = records(doc)
    assert len(found) == 1, found
    return found[0]


def outcome(r):
    return (r["status"], r.get("type"), r.get("binding"))


def project_call(name, columns, *args, **extra):
    return one(plan([name], project(read(*columns), fn(1, *args, **extra))))


# ------------------------------------------------------------------------ binding

def test_signature_binds_one_implementation():
    given()
    # "Extension declarations in plans identify functions by signature only".
    r = project_call("add:i32_i32", ["i32", "i32?"], field(0), field(1))
    assert outcome(r) == ("derived", "i32?", "signature")
    assert r["path"] == "relations[0].root.input.project.expressions[0].scalarFunction"
    assert (r["kind"], r["anchor"], r["name"], r["urn"]) == ("scalar", 1, "add:i32_i32", URN)
    # The signature names add:i32_i32, which does not accept i64 - even though add:i64_i64 would.
    r = project_call("add:i32_i32", ["i64", "i64"], field(0), field(1))
    assert r["status"] == "unbound", r
    r = project_call("add:fp32_fp32", ["fp32", "fp32"], field(0), field(1))
    assert r["status"] == "unbound" and "no function signature" in r["reason"], r


def test_bare_name_binds_by_argument_types():
    given()
    r = project_call("add", ["i64", "i64"], field(0), field(1))
    assert outcome(r) == ("derived", "i64", "name")
    r = project_call("add", ["fp32", "fp32"], field(0), field(1))
    assert r["status"] == "unbound" and "accepts" in r["reason"], r


def test_empty_signature_names_the_niladic_implementation():
    given()
    rel = {"aggregate": {"input": read("i64"), "measures": [
        {"measure": {"functionReference": 1, "phase": "AGGREGATION_PHASE_INITIAL_TO_RESULT"}}]}}
    r = one(plan(["count:"], rel))
    assert outcome(r) == ("derived", "i64", "signature")
    assert r["path"] == "relations[0].root.input.aggregate.measures[0].measure"


def test_unknown_names_and_urns_are_unbound():
    given()
    assert project_call("||", ["string", "string"], field(0), field(1))["status"] == "unbound"
    r = one(plan(["add:i32_i32"], project(read("i32"), fn(1, field(0), field(0))),
                 urn="extension:test:nowhere"))
    assert r["status"] == "unbound" and "urn" in r["reason"], r
    # A call whose anchor no declaration has.
    r = one(plan([], project(read("i32"), fn(4, field(0), field(0)))))
    assert r["status"] == "unbound" and r["name"] is None, r


def test_a_call_binds_only_its_own_kind_of_function():
    given()
    # "which must refer to a scalar function in the associated YAML file"
    r = project_call("count:any", ["i64"], field(0))
    assert r["status"] == "unbound" and "aggregate function" in r["reason"], r


# -------------------------------------------------------------------- nullability

def test_mirror_is_nullable_when_any_argument_is():
    given()
    assert outcome(project_call("add:i64_i64", ["i64", "i64"], field(0), field(1))) == \
        ("derived", "i64", "signature")
    assert outcome(project_call("add:i64_i64", ["i64?", "i64"], field(0), field(1)))[1] == "i64?"


def test_declared_output_ignores_the_arguments():
    given()
    assert outcome(project_call("is_null:any", ["i64?"], field(0)))[1] == "bool"


def test_discrete_matches_declared_nullability():
    given()
    # The table in scalar_functions.md: g2(any1, any1?) over (i32, i32?) returns i32?, and over
    # (i32, i32) or (i32?, i32?) does not bind.
    assert outcome(project_call("g2:any_any", ["i32", "i32?"], field(0), field(1)))[1] == "i32?"
    assert project_call("g2:any_any", ["i32", "i32"], field(0), field(1))["status"] == "unbound"
    assert project_call("g2:any_any", ["i32?", "i32?"], field(0), field(1))["status"] == "unbound"


# ----------------------------------------------------------- variadic, parameters, programs

def test_variadic_arguments():
    given()
    assert outcome(project_call("concat:str", ["string"] * 3, field(0), field(1), field(2)))[1] \
        == "str"
    assert project_call("concat:str", [], )["status"] == "unbound"      # min: 1
    assert outcome(project_call("coalesce:any", ["i32", "i32?"], field(0), field(1)))[1] == "i32?"
    assert project_call("coalesce:any", ["i32"], field(0))["status"] == "unbound"   # min: 2
    # any1 is one type per call, whatever the variadic argument's consistency.
    assert project_call("coalesce:any", ["i32", "i64"], field(0), field(1))["status"] == "unbound"
    # Same length: both readings of an unmarked variadic argument bind, and agree.
    assert outcome(project_call("concat:vchar", ["varchar<3>", "varchar<3>"],
                                field(0), field(1)))[1] == "vchar(3)"
    # Different lengths bind only if the argument is INCONSISTENT, which the file does not say.
    r = project_call("concat:vchar", ["varchar<3>", "varchar<5>"], field(0), field(1))
    assert r["status"] == "declined" and "INCONSISTENT" in r["reason"], r


def test_decimal_return_program():
    given()
    # init_scale 2 + 3 = 5, init_prec 10 + 5 + 1 = 16, under 38: dec(16,5).
    assert outcome(project_call("multiply:dec_dec", ["decimal<10,2>", "decimal<5,3>"],
                                field(0), field(1)))[1] == "dec(16,5)"
    # init_prec 51 is over 38: scale max(20 - 13, min(20, 6)) = 7, precision 38.
    assert outcome(project_call("multiply:dec_dec", ["decimal<30,10>", "decimal?<20,10>"],
                                field(0), field(1)))[1] == "dec(38,7)?"


def test_enumeration_arguments():
    given()
    assert outcome(project_call("extract:req_date", ["date"], "month", field(0)))[1] == "i64"
    r = project_call("extract:req_date", ["date"], "WEEK", field(0))
    assert r["status"] == "unbound" and "WEEK" in r["reason"], r
    # An enumeration position given a value.
    assert project_call("extract:req_date", ["date", "date"], field(0), field(1))["status"] == \
        "unbound"


# ------------------------------------------------------------------------- phases

def measure(anchor, *args, **extra):
    body = {"functionReference": anchor,
            "arguments": [{"enum": a} if isinstance(a, str) else {"value": a} for a in args]}
    body.update(extra)
    return {"measure": body}


def aggregate_call(name, columns, *args, **extra):
    rel = {"aggregate": {"input": read(*columns), "measures": [measure(1, *args, **extra)]}}
    return one(plan([name], rel))


def test_phases():
    given()
    r = aggregate_call("avg:fp64", ["fp64"], field(0),
                       phase="AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE")
    assert outcome(r)[1] == "struct(fp64,i64)"
    r = aggregate_call("avg:fp64", ["struct<fp64,i64>"], field(0),
                       phase="AGGREGATION_PHASE_INTERMEDIATE_TO_RESULT")
    assert outcome(r)[1] == "fp64?"
    # An unset phase "Implies INTERMEDIATE_TO_RESULT": the input must be the intermediate type.
    assert aggregate_call("avg:fp64", ["fp64"], field(0))["status"] == "unbound"
    assert outcome(aggregate_call("count:any", ["i64"], field(0)))[1] == "i64"
    # Not decomposable: INITIAL_TO_RESULT is the only valid phase, and unset is not that.
    r = aggregate_call("std_dev:req_fp64", ["fp64"], "sample", field(0))
    assert r["status"] == "unbound" and "decomposable" in r["reason"], r
    r = aggregate_call("std_dev:req_fp64", ["fp64"], "sample", field(0),
                       phase="AGGREGATION_PHASE_INITIAL_TO_RESULT")
    assert outcome(r)[1] == "fp64?"


def test_window_relation_and_expression():
    given()
    rel = {"window": {"input": read("i64"), "windowFunctions": [
        {"functionReference": 1, "phase": "AGGREGATION_PHASE_INITIAL_TO_RESULT"}]}}
    r = one(plan(["rank:"], rel))
    assert (r["kind"], outcome(r)) == ("window", ("derived", "i64?", "signature"))
    # A window call may name an aggregate function.
    call = {"windowFunction": {"functionReference": 1, "arguments": [{"value": field(0)}],
                               "phase": "AGGREGATION_PHASE_INITIAL_TO_RESULT"}}
    r = one(plan(["count:any"], project(read("i64"), call)))
    assert (r["kind"], outcome(r)[1]) == ("window", "i64")


# ------------------------------------------------------- where the columns come from

def test_every_call_is_found_and_typed_over_its_own_input():
    given()
    left, right = read("i64", "i64"), read("i64?")
    names = ["add:i64_i64", "is_null:any"]
    join = {"join": {"left": left, "right": right, "type": "JOIN_TYPE_LEFT",
                     "expression": fn(2, fn(1, field(0), field(2))),
                     "postJoinFilter": fn(2, fn(1, field(1), field(2)))}}
    got = {r["path"]: outcome(r) for r in records(plan(names, {"filter": {
        "input": join, "condition": fn(2, field(0))}}))}
    at = "relations[0].root.input.filter"
    # The join condition reads the inputs as they are, where the right column is i64?; the
    # post-join filter reads the join's output, the same here since the right side was nullable.
    assert got == {
        at + ".condition.scalarFunction": ("derived", "bool", "signature"),
        at + ".input.join.expression.scalarFunction": ("derived", "bool", "signature"),
        at + ".input.join.expression.scalarFunction.arguments[0].value.scalarFunction":
            ("derived", "i64?", "signature"),
        at + ".input.join.postJoinFilter.scalarFunction": ("derived", "bool", "signature"),
        at + ".input.join.postJoinFilter.scalarFunction.arguments[0].value.scalarFunction":
            ("derived", "i64?", "signature"),
    }, got
    # A left join nulls the right side in its output, so there a required right column is not.
    join = {"join": {"left": read("i64"), "right": read("i64"), "type": "JOIN_TYPE_LEFT",
                     "expression": fn(1, field(0), field(1)),
                     "postJoinFilter": fn(1, field(0), field(1))}}
    got = [outcome(r)[1] for r in records(plan(names, join))]
    assert got == ["i64", "i64?"], got


def test_an_unbound_argument_declines_its_caller():
    given()
    r = records(plan(["is_null:any", "add:i32_i32"],
                     project(read("i64", "i64"), fn(1, fn(2, field(0), field(1))))))
    assert [x["status"] for x in r] == ["declined", "unbound"], r
    assert "argument 0" in r[0]["reason"]


def test_declined_calls():
    given()
    # An argument this deriver has no rule for.
    in_list = {"singularOrList": {"value": field(0), "options": [field(0)]}}
    r = project_call("is_null:any", ["i64"], in_list)
    assert r["status"] == "declined", r
    # A return type naming `any`, which no argument binds.
    r = project_call("wrap:any", ["i64"], field(0))
    assert r["status"] == "declined" and "any" in r["reason"], r
    # A call over columns that are not derived: a projection mask listed out of order.
    rel = read("i64", "i64")
    rel["read"]["projection"] = {"select": {"structItems": [{"field": 1}, {"field": 0}]}}
    r = one(plan(["add:i64_i64"], project(rel, fn(1, field(0), field(1)))))
    assert r["status"] == "declined" and "not derived" in r["reason"], r


def test_if_expression_as_an_argument():
    given()
    # "all return expressions must be the same identical type": that type is the if's.
    same = {"ifThen": {"ifs": [{"if": field(2), "then": field(0)}], "else": field(1)}}
    r = project_call("add:i64_i64", ["i64?", "i64?", "boolean"], same, field(0))
    assert outcome(r)[1] == "i64?", r
    differ = {"ifThen": {"ifs": [{"if": field(2), "then": field(0)}], "else": field(1)}}
    r = project_call("add:i64_i64", ["i64", "i64?", "boolean"], differ, field(0))
    assert r["status"] == "declined" and "differ" in r["reason"], r


def test_output_type_is_not_read():
    given()
    honest = plan(["add:i64_i64"], project(read("i64", "i64?"), fn(1, field(0), field(1))))
    lying = plan(["add:i64_i64"], project(read("i64", "i64?"), fn(
        1, field(0), field(1), outputType={"string": {"nullability": "NULLABILITY_REQUIRED"}})))
    assert records(honest) == records(lying)


# ------------------------------------------------- the real files, when a checkout is there

def _checkout():
    """True when the real files can be read; otherwise a skip, under pytest or under main()."""
    reason = None
    if not os.environ.get("SUBSTRAIT_DIR"):
        reason = "SUBSTRAIT_DIR is not set"
    else:
        try:
            import yaml  # noqa: F401
        except ImportError:
            reason = "PyYAML is not installed"
    if reason is None:
        extensions._LIBRARY[0] = None
        return True
    if "pytest" in sys.modules:
        import pytest
        pytest.skip(reason)
    raise _Skipped(reason)


class _Skipped(Exception):
    pass


def test_real_files():
    _checkout()
    doc = plan(["add:i64_i64", "count:"], project(read("i64", "i64?"), fn(1, field(0), field(1))),
               urn="extension:io.substrait:functions_arithmetic")
    assert outcome(one(doc)) == ("derived", "i64?", "signature")


def test_declaration_swap_moves_nothing():
    _checkout()
    for corpus in calls.CORPORA:
        compared, moved = calls.lied_check(os.path.join(calls.ROOT, corpus))
        assert compared and not moved, (corpus, compared, moved)


def main():
    failed, skipped = [], []
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, test in tests:
        try:
            test()
        except AssertionError as why:
            failed.append("%s: %s" % (name, why))
        except _Skipped as why:
            skipped.append("%s (%s)" % (name, why))
        except Exception as why:
            failed.append("%s: %s %s" % (name, type(why).__name__, why))
    for line in failed:
        print("FAILED: %s" % line)
    if failed:
        return 1
    print("ok      the deriver's call typing holds on hand-built plans (%d checks%s)"
          % (len(tests) - len(skipped),
             "; %d need a checkout and were skipped" % len(skipped) if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
