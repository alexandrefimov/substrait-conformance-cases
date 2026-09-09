"""Case-specific expectations encoded from the spec, separately from generators and consumers.

    python3 probe/expected.py > expected.json

This script reads neither spec files nor plans. It contains manually encoded rules and examples:
reimplemented decimal formulas, set-operation tables, function return declarations, and relation
rules such as join nullability and emit order. Some rules use helpers; other cases have literal
expected schemas. It is not a schema deriver for arbitrary plans.

Schemas use normalized (type, nullable) pairs for comparison across consumer outputs. Rows are
transcribed from the spec's set-operation examples and checked separately.

Every spec file named in the comments below is named at v0.102.0, the release these plans declare:

    https://github.com/substrait-io/substrait/tree/v0.102.0

    site/docs/relations/physical_relations.md      site/docs/types/type_system.md
    site/docs/relations/logical_relations.md       site/docs/types/type_parsing.md
    proto/substrait/algebra.proto                  extensions/functions_arithmetic.yaml
    extensions/functions_arithmetic_decimal.yaml   extensions/functions_aggregate_generic.yaml

Reading this file against the spec - the first thing the README asks for - should not start with
guessing which release to open. Where a probe outside this file read another one, probe/README.md
says which and why.
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
expected["aggregate_sum_i64"] = {"schema": [["i64", True]],
                                 "source": "sum(i64) in functions_arithmetic.yaml declares return: i64? with "
                                           "nullability: DECLARED_OUTPUT, and algebra.proto requires the plan's "
                                           "output_type to be set to exactly that, so the YAML is the answer and "
                                           "the plan repeats it"}
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
#
# Column order is stated, in Direct Output Order: semi and anti emit "either left or right only",
# mark emits one side "with a 'mark' column appended at the end", everything else is "the same as
# Input Order", which is the left input followed by the right. All twelve follow from that sentence.
#
# Nullability is not stated the same way, and the difference is worth keeping in view. The spec
# prints an output-type derivation table for set operations and writes the grouping-set rule out as a
# sentence; for joins it does neither, and the word "nullable" appears once in the whole Join section
# - the mark column, "will be of type nullable boolean". That one is quoted, not derived. The rest of
# what is encoded here reads a row-level phrase as a type rule: outer, left, right and single say the
# unmatched record comes back "along with nulls for the opposite input", and turning that into "the
# opposite side is typed nullable" needs type_system.md's definition of REQUIRED as the missing step.
# Inner, semi and anti assert no change at all, which needs no step.
#
# So: semi and anti return one side; mark returns one side plus a nullable boolean; single returns
# both sides with the opposite one made nullable; left/right/outer add nullability to whichever side
# can be left without a match. The first two are the spec's words. The last two are this reading of
# them, and a consumer that declined it would not be contradicting a sentence.
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

# The three physical join messages take the same rule and the same inputs: "Direct Output Order: Same
# as the Join operator" is what physical_relations.md gives HashJoin, MergeJoin and NestedLoopJoin,
# and each carries a JoinType enum with the same twelve names JoinRel's has. So these expectations are
# not a second reading of the spec - they are join_expected again, and a case that disagrees with one
# here disagrees with the same sentence its join_ counterpart already asserts. What they add is the
# entry point: everything above is a JoinRel, so a consumer that derives the rule once and wires it
# to one message of four looks correct until asked through another.
for kind in ["inner", "left", "left_mark"]:
    for message in ("hash", "merge", "nested"):
        expected["physjoin_%s_%s" % (message, kind)] = {
            "schema": join_expected(kind),
            "source": "physical_relations.md: the same Direct Output Order as the Join operator"}

# --- emit ---------------------------------------------------------------------------------------
# All of these carry the same outputMapping [2, 0], and all seven answer [bool, i64] - but not all of
# them for the same reason, and the short version of this note used to say they did. Only read,
# filter, sort and fetch put t_mix = (i64 R, string R, bool R) directly under the emit, where [2, 0]
# is that schema reversed. emit_project's relation derives four columns (the input plus the projected
# expression), emit_join's six (t_mix concatenated with itself), and emit_aggregate's three, which is
# three only because it has one grouping set and no measures. In each of those the mapping still
# lands on a bool and an i64, so the expectation holds; it is index arithmetic over the relation's
# own direct output, not a reversal of the read.
#
# One consequence worth recording: indices 2 and 0 point at columns that also sit at those positions
# in the bare read, so none of the seven can tell a consumer that applies emit against the input
# schema apart from one that applies it against the relation's output. emit_project with [3, 0], or
# emit_join with an index in 3..5, would.
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
#
# Both are two columns and the relation derives three. Two grouping sets mean the spec appends one
# more: "an aggregate relation with more than one grouping set receives an extra i32 column on the
# right-hand side" (logical_relations.md, Aggregate Operation), which is also why Direct Output Order
# ends "(if applicable)". Each plan carries emit [0, 1], which drops that index column. Without the
# emit these expectations would be one column short of the rule they cite.
expected["aggregate_grouping_field_shared_by_sets"] = {
    "schema": [["str", False], ["i64", True]],
    "source": "Aggregate: only fields absent from some grouping set become nullable, over the two "
              "grouping expressions emit [0, 1] keeps"}
expected["aggregate_grouping_sets_declared_order"] = {
    "schema": [["str", True], ["i64", True]],
    "source": "Aggregate: sets ((c),(a)) do not intersect, so both are nullable, over the two "
              "grouping expressions emit [0, 1] keeps"}

# Cases without an expectation come in two different kinds and must not be merged. For the first no
# rule in the spec reaches the case - a hole the corpus has to name rather than quietly patch. For
# the second the spec does answer, with "this plan is invalid", and what is measured there is not the
# type but whether anyone reports the violation.
#
# What "silent" means for the four below is narrower than it used to say here, and the narrowing
# matters. It is not that the spec fails to say which schema a consumer reports: Direct Schema
# "defines the schema of the output of the read" (logical_relations.md, Read Properties), so the
# declared schema is what comes out. What no sentence settles is whether a plan whose rows disagree
# with it is well-formed at all, and who has to say so. The spec writes a field-specific match rule
# whenever it wants one - WriteRel's table_schema, DynamicParameter's literal - and wrote none
# between VirtualTable's rows and base_schema. That absence is the claim; substrait-io/substrait#1211
# asks for it to be closed.
#
# Two of the four are closer to answered than the other two, and the reasons say so rather than
# sharing one sentence. Whether the first should move to SPEC_SAYS_INVALID is a live question, not
# something to settle quietly here while #1211 is open on all four together.
SPEC_SILENT = {
    # Each reason stands on its own. They used to say "same", which reads off the entry above it -
    # and expected.json is written sorted by key, so the literal-type one ended up under the CTAS
    # entry and its "same" said the plan was invalid, which is not the question there at all.
    "virtual_table_row_null_in_required_column":
        "a null value in a column the schema declares required: no rule covers a virtual table's "
        "rows against its base_schema, but this one is barely a question - type_system.md defines "
        "REQUIRED as a type whose values cannot be null, and the row supplies one",
    "virtual_table_row_nullable_in_required_column":
        "a nullable literal in a column the schema declares required: nullability is part of a type, "
        "so the cast rule would forbid it, yet nullability is also stripped before binding under "
        "MIRROR and DECLARED_OUTPUT - the spec is in tension with itself and settles nothing here",
    "virtual_table_row_required_in_nullable_column":
        "a required literal in a column the schema declares nullable: the same tension the other way "
        "round, and the direction engines widen silently",
    "virtual_table_literal_type_differs_from_schema":
        "an i8 literal in a column the schema declares i32: no rule names virtual table rows, but "
        "the general one reaches it - type_system.md allows no coercion and requires an explicit "
        "cast for all changes in types",
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
# differs from both. substrait-java returns the input type and Isthmus the declared schema. Those are
# not equally supported, as this note used to say: the Write Operator's Direct Output Order is
# "Unchanged from input" (logical_relations.md), which is substrait-java's answer. It is a weak thing
# to score a participant on, though, because the plan is invalid before that rule is reached and the
# spec never restates the table_schema requirement outside algebra.proto. What is worth measuring is
# whether anyone reports the mismatch, and that is what the swapped-declaration corpus does
# (probe/lie_matrix.sh), not this table.

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

# --- The window relation -------------------------------------------------------------------------
# The spec says one thing about this relation's output and says it plainly: "Direct Output Order:
# same as Project operator (input followed by each window expression)" (physical_relations.md,
# Consistent Partition Window Operation). That fixes the order and the count. It does not fix the
# type of an added column: that is the return the extension declares, which the plan repeats and
# ConsistentPartitionWindow.deriveRecordType reads back, so a match on that half is the same
# calibration the decimal cases carry rather than a derivation.
expected["window_output_order"] = {
    "schema": [["i64", False], ["str", False], ["bool", False], ["i64", True], ["fp64", True]],
    "source": "physical_relations.md, Consistent Partition Window: the input followed by each "
              "window expression; the two added types are the returns functions_arithmetic.yaml "
              "declares, row_number i64? and cume_dist fp64?"}

# One frame written through each of the two encodings of a bound. Both plans are legal - the spec
# requires at least one of `offset` and `offset_expr` and allows either alone - and both say ROWS
# BETWEEN 1 PRECEDING AND CURRENT ROW, so the schema and the rows are the same in both. What differs
# is which field a consumer reads, and the spec is imperative: "Consumers must use offset_expr when
# it is set and ignore offset."
for _case in ("window_bound_offset", "window_bound_offset_expr"):
    expected[_case] = {
        "schema": [["i64", False], ["i64", True]],
        "source": "the input followed by the window expression; sum:i64 returns i64? in "
                  "functions_arithmetic.yaml"}
    rows[_case] = {
        # check_rows.py reads every integer in the answer and compares the multiset, which was
        # written for the set-operation cases, whose output is one column. Here the output is two,
        # so the pairing of a row with its sum is not what gets compared - the bag of numbers is.
        # It still separates the answers that matter: a frame that read no offset at all sums each
        # row with nothing, giving 1, 2, 3, 4 and the bag [1,1,2,2,3,3,4,4].
        "rows": sorted([1, 1, 2, 3, 3, 5, 4, 7]),
        "source": "the frame ROWS BETWEEN 1 PRECEDING AND CURRENT ROW over the rows 1, 2, 3, 4 the "
                  "plan carries: each sum is its row and the one before it, so the rows are "
                  "(1,1), (2,3), (3,5), (4,7), compared as the multiset of every integer in them"}

# --- The expand relation -------------------------------------------------------------------------
# Two rules, both stated and neither declared in the plan: an ExpandField carries no output_type, so
# a consumer has to derive these rather than repeat them.
#
# The output order is unconditional in the spec's table: "The expand fields followed by an i32 column
# describing the index of the duplicate that the row is derived from" (physical_relations.md, Expand
# Operation). Two expand fields therefore make three columns.
#
# The width of that last column is where the spec answers twice. algebra.proto's own comment on
# ExpandRel says "an extra int64 field is emitted" instead, and substrait#714 is open to reconcile
# the two; this expectation follows the docs table, which is a choice and not the only reading. No
# cell here turns on it - substrait-python emits the column as i32 and substrait-java emits none, so
# nothing has yet answered i64 - and a participant that does answer i64 is not diverging from the
# spec while that issue is open, whatever this expectation says.
#
# Its nullability is a reading too, and the argument that reached it first does not hold. That
# argument was that the docs write the column as a type and a type without a "?" is REQUIRED, citing
# type_system.md ("Either NULLABLE (? suffix) or REQUIRED (no suffix)") and type_parsing.md ("Optional,
# defaults to non-nullable"). Both quotes are there, but the "?" marker appears nowhere in
# site/docs/relations/ - not once, in either file - so its absence on this column carries nothing. The
# objection raised against the proto's "int64 field" above, that it is prose and not that notation,
# applies to "an i32 column describing the index" in the same way.
#
# Two things do support REQUIRED. Where these docs mean a nullable added column they say so in words:
# the mark column "will be of type nullable boolean" (logical_relations.md, Join Types), and nothing
# of the kind is said here or of the aggregate grouping-set index. And the proto calls this column "a
# zero-indexed ordinal corresponding to the duplicate definition" - an ordinal every row has.
#
# Neither plan carries Plan.Root.names. With three names - what this expectation implies - substrait-
# java refuses on the count before reporting any schema, because it derives two columns, and the
# disagreement about the index would turn into a names error and land in the refusals, where nothing
# records it. With none, every participant reports what it derives and substrait-python flags the
# absence beside its answer. The second is the lesser distortion: it moves a note into one column,
# where the first moves the finding out of the data.
INDEX = ["i32", False]
expected["expand_consistent_fields"] = {
    "schema": [["i64", False], ["i64", True], INDEX],
    "source": "physical_relations.md, Expand Operation: the expand fields followed by an i32 column "
              "for the duplicate index; the two fields are direct references to t_rn's columns"}

# And a switching field's type: "All duplicates must return the same type class but may differ in
# nullability. The effective type of the output field will be nullable if any of the duplicate
# expressions are nullable" (ExpandRel.SwitchingField in algebra.proto). The field here switches
# between t_rn's required column and its nullable one, so it is nullable.
expected["expand_switching_nullability"] = {
    "schema": [["i64", False], ["i64", True], INDEX],
    "source": "ExpandRel.SwitchingField in algebra.proto: nullable if any duplicate is, over the "
              "expand fields followed by the i32 duplicate index"}

# --- Cross product and Top-N ----------------------------------------------------------------------
# "Direct Output Order: Same as the `Input Order`" (logical_relations.md, Cross Product Operation):
# the left input's fields and then the right input's. Nullability is the half worth measuring - a
# cross product pads nothing, every output row pairing a real left row with a real right row, so a
# required column stays required on both sides. The join cases in this corpus already found three
# participants widening a side that a join does pad; this asks the same question where the answer is
# no. t_rn is (required, nullable) and t_nr is (nullable, required), so a side coming back wholly one
# way, or in the wrong order, shows in the pattern alone.
expected["cross_preserves_nullability"] = {
    "schema": [["i64", False], ["i64", True], ["i64", True], ["i64", False]],
    "source": "logical_relations.md, Cross Product Operation: the same order as the inputs, with "
              "neither side padded"}

# "Direct Output Order: The field order of the input" (physical_relations.md, Top-N Operation).
# Sorting and cutting change which rows come back, not which columns.
expected["topn_keeps_the_input_schema"] = {
    "schema": [["i64", False], ["i64", True]],
    "source": "physical_relations.md, Top-N Operation: the field order of the input"}

print(json.dumps({"expected": expected, "rows": rows, "disputed": DISPUTED,
                  "spec_silent": sorted(SPEC_SILENT), "spec_says_invalid": sorted(SPEC_SAYS_INVALID)},
                 ensure_ascii=False, indent=1, sort_keys=True))
