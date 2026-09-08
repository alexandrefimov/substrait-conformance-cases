# Reported findings and their reproducers

This map links the 22 reports filed during the [Substrait #1164 investigation](https://github.com/substrait-io/substrait/issues/1164) to the cases and probes that exercise their specific contracts. It includes the focused diagnostics outside the saved 78-plan matrix.

An implementation PR link identifies work on the report; it does not mean that the change is merged or included in the pinned measurements. Follow the issue and PR for current status. A missing PR link means none is recorded here, not that nobody is working on it.

## Specification questions

| Finding | Reproducer or evidence | Report |
| --- | --- | --- |
| Return type of AVG over integers | [phase_final](derived-schema/phase_final.json), which references `avg:i64`; the comparison concerns the declared function contract. | [substrait #1210](https://github.com/substrait-io/substrait/issues/1210) |
| Virtual-table row nullability versus `base_schema` | [Required row in a nullable column](derived-schema/virtual_table_row_required_in_nullable_column.json), [nullable row in a required column](derived-schema/virtual_table_row_nullable_in_required_column.json), and [null row in a required column](derived-schema/virtual_table_row_null_in_required_column.json). These cases remain unscored. | [substrait #1211](https://github.com/substrait-io/substrait/issues/1211) |

The separate `virtual_table_literal_type_differs_from_schema` case also has no settled expectation here, but is not a direct reproducer of the nullability question filed in #1211.

## Consumers and schema inference

| Finding | Reproducer in this repository | Issue / implementation PR |
| --- | --- | --- |
| Spark self-join resolution depends on table registration | [min_self_join.json](probe/min_self_join.json), run by [DiagnoseSelfJoin.java](probe/DiagnoseSelfJoin.java) with temporary-view and catalog-table registration. | [substrait-java #1245](https://github.com/substrait-io/substrait-java/issues/1245) |
| Spark read projection is not applied | [read_projection_mask](derived-schema/read_projection_mask.json), with [SparkSchemaOf.java](probe/SparkSchemaOf.java) in `--relation` mode to separate relation output from root naming. | [substrait-java #1290](https://github.com/substrait-io/substrait-java/issues/1290) |
| Python mark joins retain both inputs | [join_left_mark](derived-schema/join_left_mark.json) and [join_right_mark](derived-schema/join_right_mark.json); the matching `joineq_*` cases cover equality conditions. | [substrait-python #263](https://github.com/substrait-io/substrait-python/issues/263) / [PR #265](https://github.com/substrait-io/substrait-python/pull/265) |
| Python read projection is ignored | [read_projection_mask](derived-schema/read_projection_mask.json), through [python_one.py](probe/python_one.py). | [substrait-python #264](https://github.com/substrait-io/substrait-python/issues/264) / [PR #266](https://github.com/substrait-io/substrait-python/pull/266) |
| Python outer and single joins retain input nullability | [python_nullability.py](probe/python_nullability.py) with `--area join`: left, right, outer and both single joins over all four input-nullability pairs; inner joins are controls. | [substrait-python #267](https://github.com/substrait-io/substrait-python/issues/267) |
| Python grouping sets retain required grouping keys | [python_nullability.py](probe/python_nullability.py) with `--area grouping`: disjoint sets, a shared key, a grand total and reversed sets; one grouping set is a control. | [substrait-python #268](https://github.com/substrait-io/substrait-python/issues/268) |
| Validator set operations reuse primary-input nullability | [setop_union_all](derived-schema/setop_union_all.json), [setop_union_distinct](derived-schema/setop_union_distinct.json), and the three `setop_intersection_*` cases. Minus cases are controls. | [substrait-validator #579](https://github.com/substrait-io/substrait-validator/issues/579) / [PR #582](https://github.com/substrait-io/substrait-validator/pull/582) |
| Validator leaves a schema for unimplemented join kinds | [join_right_semi](derived-schema/join_right_semi.json), right anti and both mark joins, plus their `joineq_*` variants. Right-single behavior is adjacent evidence, outside this report. | [substrait-validator #580](https://github.com/substrait-io/substrait-validator/issues/580) |
| Validator rejects valid virtual-table expression rows | [Four structural cases](probe/structural-cases/validator), run with `python3 probe/structural_cases.py validator`: one column, two columns and emit, with an empty-table control. | [substrait-validator #584](https://github.com/substrait-io/substrait-validator/issues/584) |
| DuckDB ignores emit mappings on several relations | [emit_read](derived-schema/emit_read.json), `emit_filter`, `emit_sort`, `emit_fetch`, `emit_join`, `emit_aggregate`, and [virtual_table_emit_mapping](derived-schema/virtual_table_emit_mapping.json). `emit_project` is a passing control. | [duckdb-substrait-extension #267](https://github.com/substrait-io/duckdb-substrait-extension/issues/267) / [PR #274](https://github.com/substrait-io/duckdb-substrait-extension/pull/274) |
| DuckDB timestamp literals lose nanosecond precision | [precision_timestamp_p09](derived-schema/precision_timestamp_p09.json). The other precision cases provide related support and type-system-boundary observations. | [duckdb-substrait-extension #268](https://github.com/substrait-io/duckdb-substrait-extension/issues/268) / [PR #275](https://github.com/substrait-io/duckdb-substrait-extension/pull/275) |
| DuckDB binds decimal functions to native return types | [decimal_divide](derived-schema/decimal_divide.json), `decimal_multiply` and both overflow cases, with `decimal_add` as the passing control; use [duckdb_one.py](probe/duckdb_one.py) with `--describe`. | [duckdb-substrait-extension #276](https://github.com/substrait-io/duckdb-substrait-extension/issues/276) |
| DuckDB crashes while reporting unsupported operations | [Five structural cases](probe/structural-cases/duckdb), run with `python3 probe/structural_cases.py duckdb`: union-distinct and right-mark, with read, inner-join and union-all controls. | [duckdb-substrait-extension #277](https://github.com/substrait-io/duckdb-substrait-extension/issues/277) |
| DataFusion consumes unsupported aggregation phases | [a_rel_intermediate and b_rel_result](probe/phase-cases/README.md), through [datafusion_corpus_probe.rs](probe/datafusion_corpus_probe.rs). The rooted three-name case isolates naming behavior. | [DataFusion #24967](https://github.com/apache/datafusion/issues/24967) / [PR #25045](https://github.com/apache/datafusion/pull/25045) |
| DataFusion widens a grouping key present in every set | [aggregate_grouping_field_shared_by_sets](derived-schema/aggregate_grouping_field_shared_by_sets.json); `aggregate_grouping_sets_declared_order` is a companion case. | [DataFusion #24968](https://github.com/apache/datafusion/issues/24968) |
| DataFusion intersections retain primary-input nullability | [setop_intersection_primary](derived-schema/setop_intersection_primary.json), `setop_intersection_multiset` and `setop_intersection_multiset_all`; union and minus are controls. | [DataFusion #25042](https://github.com/apache/datafusion/issues/25042) |
| DataFusion decimal return types differ from standard functions | [decimal_divide](derived-schema/decimal_divide.json), `decimal_add_overflow` and `decimal_multiply_overflow`, with small add/multiply controls; use [datafusion_corpus_probe.rs](probe/datafusion_corpus_probe.rs). | [DataFusion #25043](https://github.com/apache/datafusion/issues/25043) |
| Go panics when a join omits optional `RelCommon` | [Three structural cases](probe/structural-cases/go), run with `python3 probe/structural_cases.py go`: absent common, with empty and direct common as controls. | [substrait-go #328](https://github.com/substrait-io/substrait-go/issues/328) |

## Producers

These probes generate plans during the run. A static consumer fixture would not exercise the producer defect.

| Finding | Reproducer | Report |
| --- | --- | --- |
| DataFusion aggregates omit required `output_type` | [datafusion_producer_probe.rs](probe/datafusion_producer_probe.rs) with `--aggregate-output-types`, inspecting count, sum, avg and min directly in the produced protobuf. | [DataFusion #25049](https://github.com/apache/datafusion/issues/25049) |
| DuckDB decimal addition changes type through its own export/import | [duckdb_producer.py](probe/duckdb_producer.py) with `--load-only --decimal-roundtrip`: three additions and a read control. | [duckdb-substrait-extension #278](https://github.com/substrait-io/duckdb-substrait-extension/issues/278) |

## Scope of this map

[Probe setup and commands](probe/README.md) describe the environments. The focused structural and phase cases have their own setup notes and controls. Reproduce against the issue's stated revision before interpreting a result from a newer implementation.

[gen/sources.json](gen/sources.json) records where a generator originally came from. That is a different relation from the reports reproduced by its cases, so this map does not rewrite those source entries. The map also does not classify every divergence as a filed issue or every rejection as a defect.
