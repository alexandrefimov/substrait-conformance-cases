# Method: where an expectation comes from, and what a match proves

The [README](README.md) is the result: the matrix, the tallies and what would help. This file is
the part a reader checking the result needs — how a case and its expectation are made, what a
matching answer does and does not establish, and what in here has already been corrected.

## Where the expectations come from

`probe/expected.py` encodes case-specific expectations by hand and records their source per case:
decimal formulas reimplemented from `functions_arithmetic_decimal.yaml`, the spec's Output Type
Derivation table, function return declarations, and relation rules such as join nullability and
emit order. It reads neither spec files nor plans. `expected.json` is the result. Eight set-operation
cases also carry expected multisets of rows transcribed from the spec's examples;
`probe/check_rows.py` compares those separately from schemas.

Five cases carry no expectation, for two different reasons that `expected.json` keeps apart. Four have
virtual-table row types or nullability different from the declared schema. They remain unscored
pending clarification of exact type equality versus compatibility between a row and its schema;
the `spec_silent` category records this unresolved question. The fifth is a CTAS whose input schema
does not match its `table_schema`. The spec requires them to match, so this plan is invalid and
what is worth measuring is whether the violation is reported.

## What the corpus is made of

The cases are plain `substrait.Plan` protobuf-JSON with no wrapper of any kind, and they declare spec
0.102. Most are the tests of bugs already fixed in substrait-java, rebuilt with the same builders so
that the expected schema is produced mechanically rather than retyped; the rest cover parts of the
spec — the set-operation derivation table, `ReadRel.projection`, aggregation phases, decimal
arithmetic — where the rule is written down and can be checked directly.

`derived-schema/manifest.json` has an entry per case: which generator writes it, the line that
generator prints for it, and its expectation with the wording of where that came from. It is built
by `gen/make_manifest.sh` from the generators themselves, so it says what the generators
say rather than what someone remembered about them; the only hand-written part is `gen/sources.json`, which records the issue a case
came from. Five cases have one so far — that is what is still thin here, and thin on purpose: an
entry is added only when the case exercises what the change it names actually changed. A case is added by adding a
generator to `gen/`; `gen/README.md` says how the corpus is built.

## What a match establishes

On some cases the consumer repeats the `output_type` the plan declares. The generator and
expectation script encode the same spec rule in separate code. A match then checks the generator's
declaration against that expectation, but does not demonstrate independent function return-type
inference by the consumer.

That is what the declaration swap measures. `probe/lie_matrix.sh` changes declared `output_type`
fields while preserving the rest of each plan and reports whose output schema moves;
`results/LIE.txt` is the saved run. For substrait-java, substrait-python and the validator a false
declaration moves the answer on ten of the 22 scored cases that carry one. For DuckDB, seventeen
output schemas stay unchanged and five pairs produce no comparable schema on either plan.

| | answers that move | of them with an expectation |
| --- | ---: | ---: |
| substrait-java | 11 | 10 |
| substrait-python | 10 | 10 |
| substrait-validator | 10 | 10 |
| DuckDB | 0 | 0 |

For substrait-java the eleven that move are the five decimal cases, `narrowing_count`, the two null
predicates and the two aggregation phases, plus `ctas_keeps_declared_schema`, which carries no
expectation.

Only 23 of the 78 cases carry an `output_type`; 22 of those have an expectation. For Java, ten
scored output schemas change and twelve hold. In those twelve cases the altered declaration belongs
to a join predicate, whose type is absent from the output schema. The predicate's declaration can
be copied without changing the join's output. The other 51 scored plans have no `output_type`.
These counts measure output sensitivity; they do not count independently derived schemas.

The swap preserves struct arity. Replacing a struct with a scalar would also change the number of
fields in depth, making the plan disagree with `Plan.Root.names`. A refusal over that disagreement
would not establish that the function's return type had been checked.

What this experiment cannot reach: it perturbs `output_type` and nothing else, so it says nothing
about a schema that comes from `ReadRel.base_schema`, which is where the other 51 get theirs. That
field is a legitimate source of input types rather than a declaration to be repeated — a consumer
that returned it unchanged would still fail the emit, projection and join cases — so the missing
half is a mutation that reaches the expression itself, not another swap of a declared output. And
only Java, Python, the validator and DuckDB were run through this script at all.

## What has already been corrected

The claims on these pages have been corrected as the measurements were reviewed, with each
correction recorded in a commit. The largest was reading a
held answer in the swap table as one the consumer derived: the twelve that held are the `joineq_*`
cases, where the swapped declaration is a join predicate whose type never reaches the output schema.

One of them was about reproducibility rather than about a result, which is why it lasted. Two cells
of the DuckDB column carried DuckDB's stack trace inside the message, and a stack trace is a fact
about the machine: mangled symbol names on macOS, the path of the loaded `.so` on Linux, and in a
virtual environment a run builds for itself, a temporary directory with a different name every time.
Those two cells could not reproduce anywhere but the workstation they were taken on. The full sweep
had already run on clean Ubuntu without noticing, because what was compared there was the tallies,
and the tallies were right. It took `probe/replay_column.sh` in a container, comparing answer
against answer, one cell at a time. `probe/normalize.py` now keeps the message and drops the trace;
the raw output a run saves under `OUT=` still has all of it.

Reasons in `differed.json` get rewritten too: ten were corrected after the answers behind them were
read one by one, and a second reader then found seven more that held for most of their cells and
described the rest wrongly. That is why a reason there has to carry a test.

The self-checks verify relationships between committed artifacts. They do not establish that every
encoded rule matches the spec or that every interpretation of a result is correct. The open items —
what has not been corrected, only listed — are in the README under *What is not settled*.

## Acero input-schema correction

The Acero table provider now materializes each known synthetic table with the schema requested by the Substrait reader. This is the decoded `ReadRel.base_schema`, as described by the [Arrow callback contract](https://arrow.apache.org/docs/python/generated/pyarrow.substrait.run_query.html); it supplies input types, not an expected output schema.

The previous provider ignored that schema and registered `t_str` with plain string and binary fields. It therefore removed the lengths before Acero executed `stringlen_declared`. With the requested schema, Acero preserves `varchar(10)` and `fixed_char(5)` as Arrow extension types and `fixed_binary(4)` as fixed-size binary. The comparison normalizes those names while retaining widths and nullability.

Retaking all 78 Acero cases with the same pinned PyArrow version changed only `stringlen_declared`; it now matches. The former `acero-drops-a-fixed-size-binary` explanation has been removed. A match on this bare read establishes preservation of the supplied input schema, not independent derivation of a function return type. Each column retains its own measurement date when only one participant is rerun.

## Reports and generator sources

[FINDINGS.md](FINDINGS.md) maps the reported findings to their reproducers and related implementation PRs. The explanations in `differed.json` remain judgments about the saved cells: fifteen of its twenty reasons link an issue or PR. The separate report map also covers rejected plans and producer diagnostics, which are outside those differing cells.

What came of a divergence is recorded beside it, and per participant rather than per reason, because one reason can cover four of them and no single report covers all four. Each entry says `reported`, `spec-question`, `ours` — the expectation or this harness is wrong — or `open`, and there are twenty-four of them; three of those twenty-four still need investigation, each saying what is missing. `open` includes an observation that has been examined but still needs a narrower reproducer or an ownership decision. A `reported` entry can link existing work, including a PR without a separate issue; its note states any coverage limits. It does not change the saved measurement or mean that a proposed fix has been rerun. What `probe/check_differed.py` requires is that every divergence carries an entry for every participant whose cells it covers, that only a divergence carries one, and that every link it names appears in FINDINGS.md.
