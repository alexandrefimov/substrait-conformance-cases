# Where each implementation differs

Written by `probe/diffs.py`; `probe/selfcheck.sh` checks it against the saved columns.

If you maintain one of these implementations, this page is for you: it lists your cases, what
the spec says each should derive, what your build answered, why it is recorded as a
difference, and what came of it. The plans are
in [`derived-schema/`](../derived-schema), and [`derived-schema-virtual-tables/`](../derived-schema-virtual-tables) has the same cases carrying their own rows, which need no
table registered and no part of this harness. A difference is measured against this
repository's reading of the spec, not against your own tests: some of these are questions
for the spec and some are ours, and each says which.

Columns taken 2026-09-09. [FINDINGS.md](../FINDINGS.md) maps the reports the other way, from a
finding to its reproducers.

## substrait-java — 2 cases

`results/JAVA.txt`, substrait-java fff63906.

### `java-expand-omits-the-duplicate-index`

The spec's output order for this relation is the expand fields followed by an i32 column carrying the index of the duplicate a row came from, and the rule is unconditional in that table. substrait-java maps the fields and stops, so its answer is a column short on both cases. The reading is not only this repository's: substrait-python returns the third column, and it is the one implementation here that does.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-java/issues/1296

Both normative texts say a column follows the expand fields - physical_relations.md an i32 one, algebra.proto an int64 one - so an answer carrying none is short under either, and substrait-io/substrait#714, which is open on that width, does not reach this. The report covers both cases here; which width a fix should pick is left to substrait-io/substrait#714.

| case | expected | substrait-java answered | the expectation comes from |
| --- | --- | --- | --- |
| [expand_consistent_fields](../derived-schema/expand_consistent_fields.json) | `[i64, i64?, i32]` | `Struct{nullable=false, fields=[I64{nullable=false}, I64{nullable=true}]}` | physical_relations.md, Expand Operation: the expand fields followed by an i32 column for the duplicate index; the two fields are direct references to t_rn's columns |
| [expand_switching_nullability](../derived-schema/expand_switching_nullability.json) | `[i64, i64?, i32]` | `Struct{nullable=false, fields=[I64{nullable=false}, I64{nullable=true}]}` | ExpandRel.SwitchingField in algebra.proto: nullable if any duplicate is, over the expand fields followed by the i32 duplicate index |

## substrait-python — 24 cases

`results/PYTHON.txt`, substrait 0.31.0.

### `python-expand-switching-stays-required`

A switching field takes the type class its duplicates share and is nullable if any of them is, which algebra.proto states on SwitchingField itself. The field here switches between t_rn's required column and its nullable one, and substrait-python returns it required. It returns the duplicate index the same case asks for, which substrait-java does not - each of the two carries one rule and misses the other.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-python/issues/269

ExpandRel.SwitchingField in algebra.proto states the rule outright, and substrait-python 0.31.0 takes the first duplicate's type instead. The report shows the answer following the order the duplicates are written in, which this case alone does not: it carries one order only. substrait-io/substrait-python#267 and substrait-io/substrait-python#268 are the join and grouping-key sides of the same shape and neither reaches this relation.

| case | expected | substrait-python answered | the expectation comes from |
| --- | --- | --- | --- |
| [expand_switching_nullability](../derived-schema/expand_switching_nullability.json) | `[i64, i64?, i32]` | `[?:i64, ?:i64, ?:i32]  !! names 0, types 3` | ExpandRel.SwitchingField in algebra.proto: nullable if any duplicate is, over the expand fields followed by the i32 duplicate index |

### `python-go-aggregate-all-required`

substrait-python and substrait-go return both emitted grouping keys required. In aggregate_grouping_sets_declared_order both keys are absent from one set and should be nullable. In aggregate_grouping_field_shared_by_sets the string key is shared and correctly stays required, but the i64 key is absent from the second set and should be nullable. Neither plan contains measures; emit hides the grouping-set index.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-python/issues/268

The report includes both grouping-set layouts used here: disjoint keys and one shared key. Both nullable-key observations are covered; these plans contain no measures.

| case | expected | substrait-python answered | the expectation comes from |
| --- | --- | --- | --- |
| [aggregate_grouping_field_shared_by_sets](../derived-schema/aggregate_grouping_field_shared_by_sets.json) | `[str, i64?]` | `[c:str, a:i64]` | Aggregate: only fields absent from some grouping set become nullable, over the two grouping expressions emit [0, 1] keeps |
| [aggregate_grouping_sets_declared_order](../derived-schema/aggregate_grouping_sets_declared_order.json) | `[str?, i64?]` | `[c:str, a:i64]` | Aggregate: sets ((c),(a)) do not intersect, so both are nullable, over the two grouping expressions emit [0, 1] keeps |

### `python-join-concatenates-the-inputs`

substrait-python drops a side for semi and anti, which match. Everywhere else it returns the two inputs concatenated with their own nullability - inner matches too, but only because the concatenation is the right answer there. It never widens a side to nullable for left, right, outer or single, and for a mark join it appends the mark column without dropping the right side. The physical joins answer the same way: HashJoinRel, MergeJoinRel and NestedLoopJoinRel all reach one deriver, so left widens nothing and a mark join keeps both sides there too, while their inner cases match for the reason inner always matches here.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-python/issues/263 https://github.com/substrait-io/substrait-python/issues/267

263 is the four mark joins, reproduced by these cases; 267 is the ten left, right, outer and single ones, reproduced by probe/python_nullability.py. Both reports are written about JoinRel, and the physjoin_* cells show the same two answers arriving through HashJoinRel, MergeJoinRel and NestedLoopJoinRel, which neither report mentions.

| case | expected | substrait-python answered | the expectation comes from |
| --- | --- | --- | --- |
| [join_left](../derived-schema/join_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [join_left_mark](../derived-schema/join_left_mark.json) | `[i64, i64?, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | the spec rules for join types and Direct Output Order |
| [join_left_single](../derived-schema/join_left_single.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [join_outer](../derived-schema/join_outer.json) | `[i64?, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [join_right](../derived-schema/join_right.json) | `[i64?, i64?, i64?, i64]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [join_right_mark](../derived-schema/join_right_mark.json) | `[i64?, i64, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | the spec rules for join types and Direct Output Order |
| [join_right_single](../derived-schema/join_right_single.json) | `[i64?, i64?, i64?, i64]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [joineq_left](../derived-schema/joineq_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [joineq_left_mark](../derived-schema/joineq_left_mark.json) | `[i64, i64?, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | the spec rules for join types and Direct Output Order |
| [joineq_left_single](../derived-schema/joineq_left_single.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [joineq_outer](../derived-schema/joineq_outer.json) | `[i64?, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [joineq_right](../derived-schema/joineq_right.json) | `[i64?, i64?, i64?, i64]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [joineq_right_mark](../derived-schema/joineq_right_mark.json) | `[i64?, i64, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | the spec rules for join types and Direct Output Order |
| [joineq_right_single](../derived-schema/joineq_right_single.json) | `[i64?, i64?, i64?, i64]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | the spec rules for join types and Direct Output Order |
| [physjoin_hash_left](../derived-schema/physjoin_hash_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | physical_relations.md: the same Direct Output Order as the Join operator |
| [physjoin_hash_left_mark](../derived-schema/physjoin_hash_left_mark.json) | `[i64, i64?, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | physical_relations.md: the same Direct Output Order as the Join operator |
| [physjoin_merge_left](../derived-schema/physjoin_merge_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | physical_relations.md: the same Direct Output Order as the Join operator |
| [physjoin_merge_left_mark](../derived-schema/physjoin_merge_left_mark.json) | `[i64, i64?, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | physical_relations.md: the same Direct Output Order as the Join operator |
| [physjoin_nested_left](../derived-schema/physjoin_nested_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | physical_relations.md: the same Direct Output Order as the Join operator |
| [physjoin_nested_left_mark](../derived-schema/physjoin_nested_left_mark.json) | `[i64, i64?, bool?]` | `[c0:i64, c1:i64?, c2:i64?, ?:i64, ?:bool?]  !! names 3, types 5` | physical_relations.md: the same Direct Output Order as the Join operator |

### `read-projection-ignored`

ReadRel.projection masks the read's columns before anything else; both return the unmasked schema, all three columns of it. substrait-python labels the first two with the root's names and the third with none, which its probe flags; Isthmus keeps the schema's own names.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-python/issues/264

| case | expected | substrait-python answered | the expectation comes from |
| --- | --- | --- | --- |
| [read_projection_mask](../derived-schema/read_projection_mask.json) | `[i64, bool]` | `[k0:i64, k1:str, ?:bool]  !! names 2, types 3` | Read / Direct Output Order: the schema after projection is applied |

## substrait-go — 4 cases

`results/GO.txt`, substrait-go/v9 v9.0.0-alpha.0.0.20260902180101-cb2d6e648bc0.

### `go-physical-join-keeps-input-nullability`

A left join widens the right side to nullable. substrait-go does that for JoinRel - join_left and joineq_left both match - and not for HashJoinRel or MergeJoinRel, where it returns the two inputs concatenated with their own nullability. Its nested-loop join is unimplemented and its physical mark joins fail on the output-name count instead, so these two cells are where the difference is visible as a schema.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-go/issues/330

The contrast is inside this column: the same rule, the same two inputs and the same join type, right on the logical message and wrong on two physical ones. The report names the cause, HashJoinRel and MergeJoinRel concatenating their inputs without reading the join type. Whether the other nine join types behave the same way is not established here, because these cases carry only inner, left and left mark.

| case | expected | substrait-go answered | the expectation comes from |
| --- | --- | --- | --- |
| [physjoin_hash_left](../derived-schema/physjoin_hash_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | physical_relations.md: the same Direct Output Order as the Join operator |
| [physjoin_merge_left](../derived-schema/physjoin_merge_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:i64, c1:i64?, c2:i64?, c3:i64]` | physical_relations.md: the same Direct Output Order as the Join operator |

### `python-go-aggregate-all-required`

substrait-python and substrait-go return both emitted grouping keys required. In aggregate_grouping_sets_declared_order both keys are absent from one set and should be nullable. In aggregate_grouping_field_shared_by_sets the string key is shared and correctly stays required, but the i64 key is absent from the second set and should be nullable. Neither plan contains measures; emit hides the grouping-set index.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-go/pull/324

The PR makes each grouping key nullable when absent from any set; the shared key stays required. Both emitted outputs are covered; these plans contain no measures.

| case | expected | substrait-go answered | the expectation comes from |
| --- | --- | --- | --- |
| [aggregate_grouping_field_shared_by_sets](../derived-schema/aggregate_grouping_field_shared_by_sets.json) | `[str, i64?]` | `[c:string, a:i64]` | Aggregate: only fields absent from some grouping set become nullable, over the two grouping expressions emit [0, 1] keeps |
| [aggregate_grouping_sets_declared_order](../derived-schema/aggregate_grouping_sets_declared_order.json) | `[str?, i64?]` | `[c:string, a:i64]` | Aggregate: sets ((c),(a)) do not intersect, so both are nullable, over the two grouping expressions emit [0, 1] keeps |

## substrait-validator — 28 cases

`results/VALIDATOR.txt`, substrait-validator 0.1.4 at 2a10470.

### `validator-aggregate-gives-i32-and-unresolved`

These plans contain two grouping expressions and no measures. The validator does not parse the relation-level grouping expressions, so its direct output contains only the grouping-set index, i32. The emit mapping [0, 1] exposes that index and an out-of-range reference, which remains unresolved.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-validator/pull/567

The PR parses relation-level grouping expressions and their references, covering both emitted fields in these plans; this links the proposed fix, not a rerun of its head.

| case | expected | substrait-validator answered | the expectation comes from |
| --- | --- | --- | --- |
| [aggregate_grouping_field_shared_by_sets](../derived-schema/aggregate_grouping_field_shared_by_sets.json) | `[str, i64?]` | `[i32, unresolved]` | Aggregate: only fields absent from some grouping set become nullable, over the two grouping expressions emit [0, 1] keeps |
| [aggregate_grouping_sets_declared_order](../derived-schema/aggregate_grouping_sets_declared_order.json) | `[str?, i64?]` | `[i32, unresolved]` | Aggregate: sets ((c),(a)) do not intersect, so both are nullable, over the two grouping expressions emit [0, 1] keeps |

### `validator-does-not-resolve`

The validator answers with an unresolved type class rather than a type. It is not a wrong derivation and not a limit of a type system: nothing was derived to compare.

Recorded as a type this participant never resolved.

| case | expected | substrait-validator answered | the expectation comes from |
| --- | --- | --- | --- |
| [emit_aggregate](../derived-schema/emit_aggregate.json) | `[bool, i64]` | `[unresolved, unresolved]` | RelCommon.emit: the listed order of direct outputs |
| [precision_timestamp_p00](../derived-schema/precision_timestamp_p00.json) | `[precision_timestamp(0)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p01](../derived-schema/precision_timestamp_p01.json) | `[precision_timestamp(1)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p02](../derived-schema/precision_timestamp_p02.json) | `[precision_timestamp(2)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p03](../derived-schema/precision_timestamp_p03.json) | `[precision_timestamp(3)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p04](../derived-schema/precision_timestamp_p04.json) | `[precision_timestamp(4)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p06](../derived-schema/precision_timestamp_p06.json) | `[precision_timestamp(6)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p07](../derived-schema/precision_timestamp_p07.json) | `[precision_timestamp(7)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p09](../derived-schema/precision_timestamp_p09.json) | `[precision_timestamp(9)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p12](../derived-schema/precision_timestamp_p12.json) | `[precision_timestamp(12)]` | `[c:unresolved]` | a read with no operations: the schema is base_schema |
| [virtual_table_emit_mapping](../derived-schema/virtual_table_emit_mapping.json) | `[str]` | `[unresolved]` | RelCommon.emit over a virtual table: the listed order of direct outputs |

### `validator-join-concatenates-the-inputs`

The validator applies the join type on inner, outer, left, right, left semi, left anti and left single, all of which match - plain right included, which is the point of the contrast. On the five it leaves unimplemented - right semi, right anti, right single and a mark join on either side - the concatenated inputs stay in place as the schema, with their own nullability and no mark column.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-validator/issues/580

The two right-single cells are adjacent evidence, outside what that issue reports.

| case | expected | substrait-validator answered | the expectation comes from |
| --- | --- | --- | --- |
| [join_left_mark](../derived-schema/join_left_mark.json) | `[i64, i64?, bool?]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [join_right_anti](../derived-schema/join_right_anti.json) | `[i64?, i64]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [join_right_mark](../derived-schema/join_right_mark.json) | `[i64?, i64, bool?]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [join_right_semi](../derived-schema/join_right_semi.json) | `[i64?, i64]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [join_right_single](../derived-schema/join_right_single.json) | `[i64?, i64?, i64?, i64]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [joineq_left_mark](../derived-schema/joineq_left_mark.json) | `[i64, i64?, bool?]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [joineq_right_anti](../derived-schema/joineq_right_anti.json) | `[i64?, i64]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [joineq_right_mark](../derived-schema/joineq_right_mark.json) | `[i64?, i64, bool?]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [joineq_right_semi](../derived-schema/joineq_right_semi.json) | `[i64?, i64]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |
| [joineq_right_single](../derived-schema/joineq_right_single.json) | `[i64?, i64?, i64?, i64]` | `[i64, i64?, i64?, i64]` | the spec rules for join types and Direct Output Order |

### `validator-setop-takes-the-first-input`

The validator returns the first input's nullability for every set operation, union included.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-validator/issues/579

| case | expected | substrait-validator answered | the expectation comes from |
| --- | --- | --- | --- |
| [setop_intersection_multiset](../derived-schema/setop_intersection_multiset.json) | `[i64, i64, i64, i64, i64, i64, i64, i64?]` | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | the Output Type Derivation Examples table in the spec |
| [setop_intersection_multiset_all](../derived-schema/setop_intersection_multiset_all.json) | `[i64, i64, i64, i64, i64, i64, i64, i64?]` | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | the Output Type Derivation Examples table in the spec |
| [setop_intersection_primary](../derived-schema/setop_intersection_primary.json) | `[i64, i64, i64, i64, i64, i64?, i64?, i64?]` | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | the Output Type Derivation Examples table in the spec |
| [setop_union_all](../derived-schema/setop_union_all.json) | `[i64, i64?, i64?, i64?, i64?, i64?, i64?, i64?]` | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | the Output Type Derivation Examples table in the spec |
| [setop_union_distinct](../derived-schema/setop_union_distinct.json) | `[i64, i64?, i64?, i64?, i64?, i64?, i64?, i64?]` | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | the Output Type Derivation Examples table in the spec |

## Isthmus/Calcite — 5 cases

`results/ISTHMUS.txt`, substrait-java fff63906.

### `isthmus-setop-nullable-if-any-input-is`

The spec's Output Type Derivation table gives a pattern per operation. Isthmus applies the union pattern - nullable where any input is - to intersection and minus as well.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-java/issues/186

The updated reproducer in the issue covers these four intersection and minus operations; the corpus shows their output-schema disagreement without adding a projection above the set.

| case | expected | Isthmus/Calcite answered | the expectation comes from |
| --- | --- | --- | --- |
| [setop_intersection_multiset](../derived-schema/setop_intersection_multiset.json) | `[i64, i64, i64, i64, i64, i64, i64, i64?]` | `[c0:BIGINT, c1:BIGINT?, c2:BIGINT?, c3:BIGINT?, c4:BIGINT?, c5:BIGINT?, c6:BIGINT?, c7:BIGINT?]` | the Output Type Derivation Examples table in the spec |
| [setop_intersection_multiset_all](../derived-schema/setop_intersection_multiset_all.json) | `[i64, i64, i64, i64, i64, i64, i64, i64?]` | `[c0:BIGINT, c1:BIGINT?, c2:BIGINT?, c3:BIGINT?, c4:BIGINT?, c5:BIGINT?, c6:BIGINT?, c7:BIGINT?]` | the Output Type Derivation Examples table in the spec |
| [setop_minus_primary](../derived-schema/setop_minus_primary.json) | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | `[c0:BIGINT, c1:BIGINT?, c2:BIGINT?, c3:BIGINT?, c4:BIGINT?, c5:BIGINT?, c6:BIGINT?, c7:BIGINT?]` | the Output Type Derivation Examples table in the spec |
| [setop_minus_primary_all](../derived-schema/setop_minus_primary_all.json) | `[i64, i64, i64, i64, i64?, i64?, i64?, i64?]` | `[c0:BIGINT, c1:BIGINT?, c2:BIGINT?, c3:BIGINT?, c4:BIGINT?, c5:BIGINT?, c6:BIGINT?, c7:BIGINT?]` | the Output Type Derivation Examples table in the spec |

### `read-projection-ignored`

ReadRel.projection masks the read's columns before anything else; both return the unmasked schema, all three columns of it. substrait-python labels the first two with the root's names and the third with none, which its probe flags; Isthmus keeps the schema's own names.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-java/pull/1280

A fix, opened without a separate issue.

| case | expected | Isthmus/Calcite answered | the expectation comes from |
| --- | --- | --- | --- |
| [read_projection_mask](../derived-schema/read_projection_mask.json) | `[i64, bool]` | `[c0:BIGINT, c1:VARCHAR, c2:BOOLEAN]` | Read / Direct Output Order: the schema after projection is applied |

## DataFusion — 9 cases

`results/DATAFUSION.txt`, datafusion cc29ea12a.

How far this column goes. DataFusion maps varchar/fixedchar to Utf8, which carries no length.

### `avg-over-integers-returns-float`

functions_arithmetic.yaml declares avg:i64 with return i64?, truncating partial values; the answer is a float.

Recorded as a divergence, asked of the spec. https://github.com/substrait-io/substrait/issues/1210

| case | expected | DataFusion answered | the expectation comes from |
| --- | --- | --- | --- |
| [phase_final](../derived-schema/phase_final.json) | `[i64?]` | `[r:Float64?]` | the declared return of avg:i64 in functions_arithmetic.yaml |

### `datafusion-intersection-takes-the-first-input`

DataFusion returns the first input's nullability for intersection. Its union shows this is not what it does everywhere - that answer is nullable wherever any input is, which the first input is not - while minus cannot tell the two apart, because there the spec's pattern is the first input.

Recorded as a divergence, reported. https://github.com/apache/datafusion/issues/25042

| case | expected | DataFusion answered | the expectation comes from |
| --- | --- | --- | --- |
| [setop_intersection_multiset](../derived-schema/setop_intersection_multiset.json) | `[i64, i64, i64, i64, i64, i64, i64, i64?]` | `[c0:Int64, c1:Int64, c2:Int64, c3:Int64, c4:Int64?, c5:Int64?, c6:Int64?, c7:Int64?]` | the Output Type Derivation Examples table in the spec |
| [setop_intersection_multiset_all](../derived-schema/setop_intersection_multiset_all.json) | `[i64, i64, i64, i64, i64, i64, i64, i64?]` | `[c0:Int64, c1:Int64, c2:Int64, c3:Int64, c4:Int64?, c5:Int64?, c6:Int64?, c7:Int64?]` | the Output Type Derivation Examples table in the spec |
| [setop_intersection_primary](../derived-schema/setop_intersection_primary.json) | `[i64, i64, i64, i64, i64, i64?, i64?, i64?]` | `[c0:Int64, c1:Int64, c2:Int64, c3:Int64, c4:Int64?, c5:Int64?, c6:Int64?, c7:Int64?]` | the Output Type Derivation Examples table in the spec |

### `decimal-own-derivation`

functions_arithmetic_decimal.yaml fixes the precision and scale of the result; these return a decimal and compute their own. Acero's and Spark's answers here are also nullable where the expectation is required, which is the same loss their own reasons describe elsewhere.

Recorded as a divergence, reported. https://github.com/apache/datafusion/issues/25043

| case | expected | DataFusion answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_add_overflow](../derived-schema/decimal_add_overflow.json) | `[dec(38,9)]` | `[r:Decimal128(38, 10)]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [decimal_divide](../derived-schema/decimal_divide.json) | `[dec(21,8)]` | `[r:Decimal128(15, 6)]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [decimal_multiply_overflow](../derived-schema/decimal_multiply_overflow.json) | `[dec(38,6)]` | `[r:Decimal128(38, 20)]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |

### `grouping-key-nullability`

A field grouped on by every set stays required; one absent from some set becomes nullable. DataFusion makes the key nullable.

Recorded as a divergence, reported. https://github.com/apache/datafusion/issues/24968

| case | expected | DataFusion answered | the expectation comes from |
| --- | --- | --- | --- |
| [aggregate_grouping_field_shared_by_sets](../derived-schema/aggregate_grouping_field_shared_by_sets.json) | `[str, i64?]` | `[c:Utf8?, a:Int64?]` | Aggregate: only fields absent from some grouping set become nullable, over the two grouping expressions emit [0, 1] keeps |

### `no-string-with-length`

Neither type system has a string carrying a length, so varchar<10> and fixedchar<5> cannot come back as declared. DataFusion returns FixedSizeBinary(4) for the fixed-size binary and differs only on the two strings; DuckDB has no fixed-size binary either and returns BLOB.

Recorded as a limit of this type system.

| case | expected | DataFusion answered | the expectation comes from |
| --- | --- | --- | --- |
| [stringlen_declared](../derived-schema/stringlen_declared.json) | `[vchar(10), fchar(5), fbin(4), str]` | `[c0:Utf8, c1:Utf8, c2:FixedSizeBinary(4), c3:Utf8]` | a read with no operations: the schema is base_schema |

## DuckDB — 20 cases

`results/DUCKDB.txt`, duckdb 1.5.5.

How far this column goes. carries no nullability in its logical types - types, arity and order are compared.

### `avg-over-integers-returns-float`

functions_arithmetic.yaml declares avg:i64 with return i64?, truncating partial values; the answer is a float.

Recorded as a divergence, asked of the spec. https://github.com/substrait-io/substrait/issues/1210

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [phase_final](../derived-schema/phase_final.json) | `[i64?]` | `[r:DOUBLE]` | the declared return of avg:i64 in functions_arithmetic.yaml |

### `decimal-own-derivation`

functions_arithmetic_decimal.yaml fixes the precision and scale of the result; these return a decimal and compute their own. Acero's and Spark's answers here are also nullable where the expectation is required, which is the same loss their own reasons describe elsewhere.

Recorded as a divergence, reported. https://github.com/substrait-io/duckdb-substrait-extension/issues/276

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_multiply](../derived-schema/decimal_multiply.json) | `[dec(16,3)]` | `[r:DECIMAL(15,3)]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |

### `duckdb-decimal-divide-returns-double`

divide:dec is declared to return a decimal; DuckDB returns DOUBLE, so the result is not a decimal of another precision but not a decimal at all.

Recorded as a divergence, reported. https://github.com/substrait-io/duckdb-substrait-extension/issues/276

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_divide](../derived-schema/decimal_divide.json) | `[dec(21,8)]` | `[r:DOUBLE]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |

### `duckdb-emit-ignored-except-on-a-project`

RelCommon.emit names which columns the relation returns and in what order. DuckDB applies it on a ProjectRel - emit_project matches - and applies ReadRel.projection, which is a different field. On these six relations and on a virtual table it returns the leading columns of the leaf read's schema instead, the aggregate included, whose own output is neither that nor the mapping.

Recorded as a divergence, reported. https://github.com/substrait-io/duckdb-substrait-extension/issues/267

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [emit_aggregate](../derived-schema/emit_aggregate.json) | `[bool, i64]` | `[k0:BIGINT, k1:VARCHAR]` | RelCommon.emit: the listed order of direct outputs |
| [emit_fetch](../derived-schema/emit_fetch.json) | `[bool, i64]` | `[k0:BIGINT, k1:VARCHAR]` | RelCommon.emit: the listed order of direct outputs |
| [emit_filter](../derived-schema/emit_filter.json) | `[bool, i64]` | `[k0:BIGINT, k1:VARCHAR]` | RelCommon.emit: the listed order of direct outputs |
| [emit_join](../derived-schema/emit_join.json) | `[bool, i64]` | `[k0:BIGINT, k1:VARCHAR]` | RelCommon.emit: the listed order of direct outputs |
| [emit_read](../derived-schema/emit_read.json) | `[bool, i64]` | `[k0:BIGINT, k1:VARCHAR]` | RelCommon.emit: the listed order of direct outputs |
| [emit_sort](../derived-schema/emit_sort.json) | `[bool, i64]` | `[k0:BIGINT, k1:VARCHAR]` | RelCommon.emit: the listed order of direct outputs |
| [virtual_table_emit_mapping](../derived-schema/virtual_table_emit_mapping.json) | `[str]` | `[col2:INTEGER]` | RelCommon.emit over a virtual table: the listed order of direct outputs |

### `duckdb-sum-returns-hugeint`

functions_arithmetic.yaml declares sum:i64 as returning i64? with nullability DECLARED_OUTPUT, and the plan carries that output_type. DuckDB binds its own SUM over BIGINT, whose result is HUGEINT - a wider native type, not the one the function was called under. The widening is deliberate on DuckDB's side, and it is still a type the plan did not ask for; nullability is not compared here, as everywhere in this column.

Recorded as a divergence, reported. https://github.com/substrait-io/duckdb-substrait-extension/issues/276

Reported as a comment on substrait-io/duckdb-substrait-extension#276 rather than a fourth issue: that one already reports a native return type in place of the declared one, though its body is written about the decimal functions. aggregate_sum_i64 is a plain aggregate and window_bound_offset the same call inside a window, so the widening is in how sum is bound and not in the window relation, whose support is separately unfinished there. The comment also measures the consequence: three rows of 2^62 come back as 13835058055282163712, outside the i64 the plan declared. Whether the decimal and the integer paths are one is asked there and not established here.

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [aggregate_sum_i64](../derived-schema/aggregate_sum_i64.json) | `[i64?]` | `[s:HUGEINT]` | sum(i64) in functions_arithmetic.yaml declares return: i64? with nullability: DECLARED_OUTPUT, and algebra.proto requires the plan's output_type to be set to exactly that, so the YAML is the answer and the plan repeats it |
| [window_bound_offset](../derived-schema/window_bound_offset.json) | `[i64, i64?]` | `[v:BIGINT, s:HUGEINT]` | the input followed by the window expression; sum:i64 returns i64? in functions_arithmetic.yaml |

### `duckdb-timestamp-is-microseconds`

DuckDB has second, millisecond, microsecond and nanosecond timestamps and no others, so precisions 1, 2, 4 and 7 have nothing to come back as. That does not make the answer right: the reader returns a bare microsecond TIMESTAMP rather than the nearest type DuckDB has, where its own CAST to TIMESTAMP(1) gives TIMESTAMP_MS, and it does the same on the precisions DuckDB can express, which the next reason counts as a divergence.

Recorded as a limit of this type system.

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [precision_timestamp_p01](../derived-schema/precision_timestamp_p01.json) | `[precision_timestamp(1)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p02](../derived-schema/precision_timestamp_p02.json) | `[precision_timestamp(2)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p04](../derived-schema/precision_timestamp_p04.json) | `[precision_timestamp(4)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p07](../derived-schema/precision_timestamp_p07.json) | `[precision_timestamp(7)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |

### `duckdb-timestamp-precision-ignored`

DuckDB has TIMESTAMP_S, TIMESTAMP_MS and TIMESTAMP_NS, and its reader rejects a precision above 9, so it reads the field; every declared precision still comes back as microseconds.

Recorded as a divergence, reported. https://github.com/substrait-io/duckdb-substrait-extension/issues/268

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [precision_timestamp_p00](../derived-schema/precision_timestamp_p00.json) | `[precision_timestamp(0)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p03](../derived-schema/precision_timestamp_p03.json) | `[precision_timestamp(3)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |
| [precision_timestamp_p09](../derived-schema/precision_timestamp_p09.json) | `[precision_timestamp(9)]` | `[c:TIMESTAMP]` | a read with no operations: the schema is base_schema |

### `no-string-with-length`

Neither type system has a string carrying a length, so varchar<10> and fixedchar<5> cannot come back as declared. DataFusion returns FixedSizeBinary(4) for the fixed-size binary and differs only on the two strings; DuckDB has no fixed-size binary either and returns BLOB.

Recorded as a limit of this type system.

| case | expected | DuckDB answered | the expectation comes from |
| --- | --- | --- | --- |
| [stringlen_declared](../derived-schema/stringlen_declared.json) | `[vchar(10), fchar(5), fbin(4), str]` | `[c0:VARCHAR, c1:VARCHAR, c2:BLOB, c3:VARCHAR]` | a read with no operations: the schema is base_schema |

## Spark — 6 cases

`results/SPARK.txt`, spark 3.5.4.

### `decimal-own-derivation`

functions_arithmetic_decimal.yaml fixes the precision and scale of the result; these return a decimal and compute their own. Acero's and Spark's answers here are also nullable where the expectation is required, which is the same loss their own reasons describe elsewhere.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-java/issues/1292

The report isolates decimal_divide precision using nullable operands and output; the required-input matrix case also differs in nullability, which remains a separate question.

| case | expected | Spark answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_divide](../derived-schema/decimal_divide.json) | `[dec(21,8)]` | `[r:decimal(17,8)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |

### `spark-decimal-result-nullable`

Spark returns a nullable decimal from arithmetic over required inputs; the precision and scale are the spec's.

Recorded as a divergence, asked of the spec. https://github.com/substrait-io/substrait/issues/990

The four add/multiply cases match precision and scale; they return nullable with ANSI disabled and required with ANSI enabled. add and multiply carry only overflow, whose values name no NULL, so substrait-io/substrait#990 as filed does not reach them; what a consumer may return when it omits an option is asked in its thread. probe/spark_function_options.py separately evaluates explicit overflow=ERROR, which still returns null with ANSI disabled and is reported in substrait-io/substrait-java#1293. The saved plans omit that option.

| case | expected | Spark answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_add](../derived-schema/decimal_add.json) | `[dec(11,2)]` | `[r:decimal(11,2)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [decimal_add_overflow](../derived-schema/decimal_add_overflow.json) | `[dec(38,9)]` | `[r:decimal(38,9)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [decimal_multiply](../derived-schema/decimal_multiply.json) | `[dec(16,3)]` | `[r:decimal(16,3)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [decimal_multiply_overflow](../derived-schema/decimal_multiply_overflow.json) | `[dec(38,6)]` | `[r:decimal(38,6)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |

### `spark-projection-not-applied`

ReadRel.projection names which columns the read returns and in what order. Spark returns the first two columns of the unmasked schema. The count matches what the mask selects; this corpus cannot tell that apart from the count of the root's names, which is the same in every case here.

Recorded as a divergence, reported. https://github.com/substrait-io/substrait-java/issues/1290

| case | expected | Spark answered | the expectation comes from |
| --- | --- | --- | --- |
| [read_projection_mask](../derived-schema/read_projection_mask.json) | `[i64, bool]` | `[k0:bigint, k1:string]` | Read / Direct Output Order: the schema after projection is applied |

## Acero — 15 cases

`results/ACERO.txt`, pyarrow 25.0.1.

### `acero-required-kept-only-on-a-bare-read`

control_passthrough_rn and stringlen_declared are the only two answers Acero returns with a required field. Everything else comes back wholly nullable - including emit_read, a read whose one addition is an emit mapping, which Acero applies correctly apart from that.

Recorded as a divergence, open.

Probe/structural_cases.py acero isolates identity and reordered emit over a required/nullable input: native and Substrait field-reference projects make the required field nullable while preserving rows. apache/arrow#51231 covers direct field references. Native inner, left and right joins also widen output fields; HashJoinSchema creates nullable fields, and the existing inner-join report apache/arrow#45557 was closed after a stale notice. Native is_null/is_valid projections and count also return nullable fields while preserving the tested values. General function and aggregate output inference remains outside those reports, so this broader entry stays open.

| case | expected | Acero answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_add](../derived-schema/decimal_add.json) | `[dec(11,2)]` | `[r:decimal128(11, 2)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [decimal_multiply](../derived-schema/decimal_multiply.json) | `[dec(16,3)]` | `[r:decimal128(16, 3)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
| [emit_fetch](../derived-schema/emit_fetch.json) | `[bool, i64]` | `[k0:bool?, k1:int64?]` | RelCommon.emit: the listed order of direct outputs |
| [emit_filter](../derived-schema/emit_filter.json) | `[bool, i64]` | `[k0:bool?, k1:int64?]` | RelCommon.emit: the listed order of direct outputs |
| [emit_project](../derived-schema/emit_project.json) | `[bool, i64]` | `[k0:bool?, k1:int64?]` | RelCommon.emit: the listed order of direct outputs |
| [emit_read](../derived-schema/emit_read.json) | `[bool, i64]` | `[k0:bool?, k1:int64?]` | RelCommon.emit: the listed order of direct outputs |
| [emit_sort](../derived-schema/emit_sort.json) | `[bool, i64]` | `[k0:bool?, k1:int64?]` | RelCommon.emit: the listed order of direct outputs |
| [joineq_inner](../derived-schema/joineq_inner.json) | `[i64, i64?, i64?, i64]` | `[c0:int64?, c1:int64?, c2:int64?, c3:int64?]` | the spec rules for join types and Direct Output Order |
| [joineq_left](../derived-schema/joineq_left.json) | `[i64, i64?, i64?, i64?]` | `[c0:int64?, c1:int64?, c2:int64?, c3:int64?]` | the spec rules for join types and Direct Output Order |
| [joineq_right](../derived-schema/joineq_right.json) | `[i64?, i64?, i64?, i64]` | `[c0:int64?, c1:int64?, c2:int64?, c3:int64?]` | the spec rules for join types and Direct Output Order |
| [narrowing_count](../derived-schema/narrowing_count.json) | `[i64]` | `[n:int64?]` | the declared return of count: i64 required |
| [narrowing_is_not_null](../derived-schema/narrowing_is_not_null.json) | `[bool]` | `[r:bool?]` | is_not_null returns a required boolean |
| [narrowing_is_null](../derived-schema/narrowing_is_null.json) | `[bool]` | `[r:bool?]` | is_null returns a required boolean |

### `avg-over-integers-returns-float`

functions_arithmetic.yaml declares avg:i64 with return i64?, truncating partial values; the answer is a float.

Recorded as a divergence, asked of the spec. https://github.com/substrait-io/substrait/issues/1210

| case | expected | Acero answered | the expectation comes from |
| --- | --- | --- | --- |
| [phase_final](../derived-schema/phase_final.json) | `[i64?]` | `[r:double?]` | the declared return of avg:i64 in functions_arithmetic.yaml |

### `decimal-own-derivation`

functions_arithmetic_decimal.yaml fixes the precision and scale of the result; these return a decimal and compute their own. Acero's and Spark's answers here are also nullable where the expectation is required, which is the same loss their own reasons describe elsewhere.

Recorded as a divergence, reported. https://github.com/apache/arrow/issues/51234

Probe/structural_cases.py acero-functions isolates modern extension URNs reaching the legacy name-only fallback. The decimal URI is rejected, but the decimal URN executes native divide as decimal(16,7), losing the final digit of the exactly representable 1.00 / 256.0 result. An unregistered add URN is also accepted while its legacy URI is rejected. The report concerns extension resolution; nullability remains separate.

| case | expected | Acero answered | the expectation comes from |
| --- | --- | --- | --- |
| [decimal_divide](../derived-schema/decimal_divide.json) | `[dec(21,8)]` | `[r:decimal128(16, 7)?]` | the functions_arithmetic_decimal.yaml formula, computed in expected.py |
