# Aggregation phase: three plans

Three plans showing that the DataFusion consumer does not read `AggregateFunction.phase`. To run
them: point `SUBSTRAIT_CORPUS_DIR` at this directory and run `probe/datafusion_corpus_probe.rs` as
an example inside a DataFusion checkout, the way section 2 of `reverify.sh` does.

| file | what is in it | what DataFusion answered at f96892a9b |
| --- | --- | --- |
| `a_rel_intermediate.json` | `PlanRel.rel` with no `RelRoot`, phase `INITIAL_TO_INTERMEDIATE`, declared type `STRUCT<i64,i64>` - the plan is valid throughout | accepted, `Float64?`, row `1.5` |
| `b_rel_result.json` | the same, but phase `INITIAL_TO_RESULT` and the type that phase calls for, `i64?` | accepted, `Float64?`, row `1.5` |
| `c_root_threenames.json` | a `RelRoot` with three names in depth, as the spec requires for a struct column | rejected: "Names list must match exactly to nested schema, but found 1 uses for 3 names" |

Why `PlanRel.rel` rather than `root`: the first version of this experiment used a pair of plans with
a `RelRoot` carrying one name instead of three, and its control plan kept a struct `outputType` under
the full phase. Neither plan was well-formed, so "two valid plans differing in one line" was not a
true description of them. Going through `rel` avoids the question of names entirely, and `a` is a
valid plan on which a silently wrong result is visible on its own.

`t_avg.c0` is `[1, 2]`, so avg's intermediate state is the pair (sum 3, count 2).
