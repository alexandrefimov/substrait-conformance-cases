"""Independent expectations for part of the corpus: computed from the spec, not from substrait-java.

    python3 probe/expected.py > expected.json

Why. The manifest covers 4 cases out of 78, and for three of them the expectation comes from the
same ProtoPlanConverter that is then checked against it - change that converter and both sides of
the comparison move together, so the regression disappears. The expectations here are obtained
four other ways:

  formula  - the rules of functions_arithmetic_decimal.yaml, re-implemented;
  table    - the set-operation Output Type Derivation table printed in the spec;
  yaml     - the declared return of a function (avg:i64 -> i64?);
  join     - the spec rules for each side's nullability by join type.

Schemas are written normalized, as a list of (type, nullable) pairs, so they can be compared with
any participant's output rather than only with this project's format.
"""
import json

def dec_return(op, p1, s1, p2, s2):
    """The spec formula for add/multiply/divide over decimal (functions_arithmetic_decimal.yaml)."""
    if op == "add":
        init_scale, init_prec = max(s1, s2), max(s1, s2) + max(p1 - s1, p2 - s2) + 1
    elif op == "multiply":
        init_scale, init_prec = s1 + s2, p1 + p2 + 1
    elif op == "divide":
        init_scale = max(6, s1 + p2 + 1)
        init_prec = p1 - s1 + p2 + init_scale
    else:
        raise ValueError(op)
    min_scale = min(init_scale, 6)
    delta = init_prec - 38
    prec = min(init_prec, 38)
    scale = max(init_scale - delta, min_scale) if init_prec > 38 else init_scale
    return "dec(%d,%d)" % (prec, scale)

# The t_dec columns: c0 dec(10,2), c1 dec(5,1), c2 dec(38,10), c3 dec(38,10) - as in Tables and
# in the probes.
DEC = {"decimal_add": ("add", 10, 2, 5, 1),
       "decimal_add_overflow": ("add", 38, 10, 38, 10),
       "decimal_multiply": ("multiply", 10, 2, 5, 1),
       "decimal_multiply_overflow": ("multiply", 38, 10, 38, 10),
       "decimal_divide": ("divide", 10, 2, 5, 1)}

# The spec table: inputs (R,R,R,R,N,N,N,N) / (R,R,N,N,R,R,N,N) / (R,N,R,N,R,N,R,N).
SETOP = {
    "setop_minus_primary":            "RRRRNNNN",
    "setop_minus_primary_all":        "RRRRNNNN",
    "setop_minus_multiset":           "RRRRNNNN",
    "setop_intersection_primary":     "RRRRRNNN",
    "setop_intersection_multiset":    "RRRRRRRN",
    "setop_intersection_multiset_all":"RRRRRRRN",
    "setop_union_distinct":           "RNNNNNNN",
    "setop_union_all":                "RNNNNNNN",
}

expected = {}
for case, (op, p1, s1, p2, s2) in DEC.items():
    expected[case] = {"schema": [[dec_return(op, p1, s1, p2, s2), False]],
                      "source": "the functions_arithmetic_decimal.yaml formula, computed in expected.py"}
for case, pattern in SETOP.items():
    expected[case] = {"schema": [["i64", ch == "N"] for ch in pattern],
                      "source": "the Output Type Derivation Examples table in the spec"}
expected["phase_final"] = {"schema": [["i64", True]],
                           "source": "the declared return of avg:i64 in functions_arithmetic.yaml"}
expected["narrowing_is_null"] = {"schema": [["bool", False]],
                                 "source": "is_null returns a required boolean"}
expected["narrowing_is_not_null"] = {"schema": [["bool", False]],
                                     "source": "is_not_null returns a required boolean"}
expected["control_passthrough_rn"] = {"schema": [["i64", False], ["i64", True]],
                                      "source": "a read with no operations: the schema is base_schema"}


# --- Joins ---------------------------------------------------------------------------------------
# The inputs: left t_rn = (R, N), right t_nr = (N, R), all columns i64.
# The spec rules (Join Types + Direct Output Order): semi and anti return one side; mark returns one
# side plus a nullable boolean; single returns both sides with the opposite one made nullable;
# left/right/outer add nullability to whichever side can be left without a match.
LEFT_IN = [False, True]    # t_rn
RIGHT_IN = [True, False]   # t_nr

def join_expected(kind):
    L, R = list(LEFT_IN), list(RIGHT_IN)
    if kind == "inner":        return [["i64", n] for n in L + R]
    if kind == "outer":        return [["i64", True] for _ in L + R]
    if kind == "left":         return [["i64", n] for n in L] + [["i64", True] for _ in R]
    if kind == "right":        return [["i64", True] for _ in L] + [["i64", n] for n in R]
    if kind == "left_semi":    return [["i64", n] for n in L]
    if kind == "left_anti":    return [["i64", n] for n in L]
    if kind == "right_semi":   return [["i64", n] for n in R]
    if kind == "right_anti":   return [["i64", n] for n in R]
    if kind == "left_single":  return [["i64", n] for n in L] + [["i64", True] for _ in R]
    if kind == "right_single": return [["i64", True] for _ in L] + [["i64", n] for n in R]
    if kind == "left_mark":    return [["i64", n] for n in L] + [["bool", True]]
    if kind == "right_mark":   return [["i64", n] for n in R] + [["bool", True]]
    raise ValueError(kind)

for kind in ["inner", "outer", "left", "right", "left_semi", "left_anti", "right_semi",
             "right_anti", "left_single", "right_single", "left_mark", "right_mark"]:
    for prefix in ("join_", "joineq_"):
        expected[prefix + kind] = {
            "schema": join_expected(kind),
            "source": "the spec rules for join types and Direct Output Order"}

# --- emit ---------------------------------------------------------------------------------------
# All of these carry the same outputMapping [2, 0] over t_mix = (i64 R, string R, bool R), so by
# the spec the output is two columns in reverse order.
for rel in ["read", "filter", "project", "sort", "fetch", "aggregate", "join"]:
    expected["emit_" + rel] = {
        "schema": [["bool", False], ["i64", False]],
        "source": "RelCommon.emit: the listed order of direct outputs"}


# --- The rest, derivable from the spec mechanically ----------------------------------------------

# The ReadRel.projection mask over t_mix (i64 R, string R, bool R) selects structItems
# [{field:2},{}], that is column 2 then column 0: by the spec, Read's Direct Output Order is the
# schema after the mask.
expected["read_projection_mask"] = {
    "schema": [["bool", False], ["i64", False]],
    "source": "Read / Direct Output Order: the schema after projection is applied"}

# A read with no operations: the schema equals the declared base_schema.
expected["stringlen_declared"] = {
    "schema": [["vchar(10)", False], ["fchar(5)", False], ["fbin(4)", False], ["str", False]],
    "source": "a read with no operations: the schema is base_schema"}
expected["control_join_without_relcommon"] = {
    "schema": [["i64", False], ["i64", True], ["i64", True], ["i64", False]],
    "source": "inner join without RelCommon: inputs concatenated, nullability unchanged"}

# count over a nullable column returns a required i64 (functions_aggregate_generic.yaml).
expected["narrowing_count"] = {
    "schema": [["i64", False]],
    "source": "the declared return of count: i64 required"}

# Nine precision_timestamp cases: a read of the declared column, so the schema is base_schema.
for p_ in ["00", "01", "02", "03", "04", "06", "07", "09", "12"]:
    expected["precision_timestamp_p" + p_] = {
        "schema": [["precision_timestamp(%d)" % int(p_), False]],
        "source": "a read with no operations: the schema is base_schema"}

# Two aggregates over foo(a i64 R, b i64 R, c string R) with different grouping sets - and their
# expectations DIFFER, which is the whole point of the spec rule:
#   ..._field_shared_by_sets: sets ((c,a),(c)) - c is in both, so it stays required;
#   ..._sets_declared_order:  sets ((c),(a))   - no field is in all of them, so both are nullable.
expected["aggregate_grouping_field_shared_by_sets"] = {
    "schema": [["str", False], ["i64", True]],
    "source": "Aggregate: only fields absent from some grouping set become nullable"}
expected["aggregate_grouping_sets_declared_order"] = {
    "schema": [["str", True], ["i64", True]],
    "source": "Aggregate: sets ((c),(a)) do not intersect, so both are nullable"}

# Cases without an expectation come in two different kinds and must not be merged. For the first the
# spec really gives no answer - a hole the corpus has to name rather than quietly patch. For the
# second the spec does answer, with "this plan is invalid", and what is measured there is not the
# type but whether anyone reports the violation.
SPEC_SILENT = {
    # Each reason stands on its own. They used to say "same", which reads off the entry above it -
    # and expected.json is written sorted by key, so the literal-type one ended up under the CTAS
    # entry and its "same" said the plan was invalid, which is not the question there at all.
    "virtual_table_row_null_in_required_column":
        "a null value in a column the schema declares required: the spec does not say which wins, "
        "the row or the schema",
    "virtual_table_row_nullable_in_required_column":
        "a nullable literal in a column the schema declares required: the spec does not say which "
        "wins, the row or the schema",
    "virtual_table_row_required_in_nullable_column":
        "a required literal in a column the schema declares nullable: the spec does not say which "
        "wins, the row or the schema",
    "virtual_table_literal_type_differs_from_schema":
        "an i8 literal in a column the schema declares i32: the spec does not say which wins, the "
        "row or the schema",
}
SPEC_SAYS_INVALID = {
    "ctas_keeps_declared_schema":
        "the spec requires the input schema to match table_schema (algebra.proto); this case breaks "
        "that deliberately, so what is measured is not the type but whether anyone reports it",
}
DISPUTED = dict(SPEC_SILENT)
DISPUTED.update(SPEC_SAYS_INVALID)


# --- Set-operation rows --------------------------------------------------------------------------
# The values are transcribed from the examples printed in the spec (Set Operation, the Examples
# column). They all share one schema: a single required i64 column. The row expectation is a
# multiset.
SETDATA = {
    "minus_primary":            ([1,2,2,3,3,3,4], [1,2],        [3],        [4]),
    "minus_primary_all":        ([1,2,2,3,3,3,3], [1,2,3,4],    [3],        [2,3,3]),
    "minus_multiset":           ([1,2,3,4],       [1,2],        [1,2,3],    [3,4]),
    "intersection_primary":     ([1,2,2,3,3,3,4], [1,2,3,5],    [2,3,6],    [1,2,3]),
    "intersection_multiset":    ([1,2,3,4],       [2,3],        [3,4],      [3]),
    "intersection_multiset_all":([1,2,2,3,3,3,4], [1,2,3,3,5],  [2,3,3,6],  [2,3,3]),
    "union_distinct":           ([1,2,2,3,3,3,4], [2,3,5],      [1,6],      [1,2,3,4,5,6]),
    "union_all":                ([1,2,2,3,3,3,4], [2,3,5],      [1,6],
                                 [1,2,2,3,3,3,4,2,3,5,1,6]),
}
rows = {}
for op, (p_, s1, s2, out) in SETDATA.items():
    case = "setdata_" + op
    expected[case] = {"schema": [["i64", False]],
                      "source": "one required i64 column on every input"}
    rows[case] = {"rows": sorted(out),
                  "source": "the example the spec prints for this operation"}

# On ctas_keeps_declared_schema, which is listed above as SPEC_SAYS_INVALID: on a well-formed plan
# the input type and the declared table_schema agree, so the spec has no third answer here that
# differs from both. substrait-java returns the input type and Isthmus the declared schema, and both
# positions are defensible. What is worth measuring is whether anyone reports the mismatch, and that
# is what the swapped-declaration corpus does (probe/lie_matrix.sh), not this table.

# emit over a virtual table: outputMapping selects a single column.
expected["virtual_table_emit_mapping"] = {
    "schema": [["str", False]],
    "source": "RelCommon.emit over a virtual table: the listed order of direct outputs"}

# The spec gives the type of the intermediate phase explicitly: in functions_arithmetic.yaml avg has
# `intermediate: "STRUCT<i64,i64>"` for every integral overload. Listing this case as disputed was an
# oversight - the spec is not silent here.
expected["phase_intermediate"] = {
    "schema": [["struct(i64,i64)", False]],
    "source": "functions_arithmetic.yaml: avg:i64, intermediate: STRUCT<i64,i64>"}

print(json.dumps({"expected": expected, "rows": rows, "disputed": DISPUTED,
                  "spec_silent": sorted(SPEC_SILENT), "spec_says_invalid": sorted(SPEC_SAYS_INVALID)},
                 ensure_ascii=False, indent=1, sort_keys=True))
