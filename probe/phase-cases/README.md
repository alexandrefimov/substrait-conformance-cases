# Aggregation phase: three plans

Three plans showing that the DataFusion consumer does not read `AggregateFunction.phase`, filed as
apache/datafusion#24967, whose "To Reproduce" links to this directory at tag `v0.1.0`. That tag is
therefore load-bearing: it cannot be moved or deleted, and if these plans change, the new state gets
a new tag rather than the old one being repointed. To run them: point `SUBSTRAIT_CORPUS_DIR` at this directory and run
`probe/datafusion_corpus_probe.rs` as an example inside a DataFusion checkout, the way section 2 of
`reverify.sh` does.

| file | what is in it | what DataFusion answered at `f96892a9b`, and again at `cc29ea12a` |
| --- | --- | --- |
| `a_rel_intermediate.json` | `PlanRel.rel` with no `RelRoot`, phase `INITIAL_TO_INTERMEDIATE`, declared type `STRUCT<i64,i64>` - the plan is valid throughout | accepted, `Float64?`, row `1.5` |
| `b_rel_result.json` | the same, but phase `INITIAL_TO_RESULT` and the type that phase calls for, `i64?` | accepted, `Float64?`, row `1.5` |
| `c_root_threenames.json` | a `RelRoot` with three names in depth, as the spec requires for a struct column | rejected: "Names list must match exactly to nested schema, but found 1 uses for 3 names" |

Why `PlanRel.rel` rather than `root`: the first version of this experiment used a pair of plans with
a `RelRoot` carrying one name instead of three, and its control plan kept a struct `outputType` under
the full phase. Neither plan was well-formed, so "two valid plans differing in one line" was not a
true description of them. Going through `rel` avoids the question of names entirely, and `a` is a
valid plan on which a silently wrong result is visible on its own.

`t_avg.c0` is `[1, 2]`, so avg's intermediate state is the pair (sum 3, count 2), and
`functions_arithmetic.yaml` declares `avg:i64` with `return: i64?`, truncating partial values. The
answer `Float64? 1.5` is therefore neither: not the intermediate state the phase asks for, and not
the integral result the declared return calls for. It is DataFusion's own avg, run complete whatever
the phase says.

In the corpus proper the same thing shows in the DataFusion column: `phase_final` answers
`Float64?` where the declared return is `i64?`, and `phase_intermediate` is refused over the names a
struct column needs — which is why these three plans exist, since going through `PlanRel.rel` avoids
the question of names entirely.
