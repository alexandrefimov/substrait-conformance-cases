# Method: where an expectation comes from, and what a match proves

This document explains how the generated schema corpus's plans and expectations are made,
what a match establishes, and how earlier claims have been corrected. The [README](README.md)
introduces both corpora and their saved results. The separate relation corpus's expectation,
row-order and validity contracts are in [its authoring guide](tests/relations/README.md).

For a specification review, start with [expectation sources](#where-the-expectations-come-from).
For a consumer result, read [what a match establishes](#what-a-match-establishes) and
[function binding](#whether-the-call-is-bound-at-all). For corpus adoption, read
[the upstream considerations](#what-moving-these-upstream-would-take).

## Where the expectations come from

`probe/expected.py` encodes expectations by hand from the specification text and records a
source per case. It reads neither spec files, plans, generators nor implementation answers;
`expected.json` is its output. Sources include decimal formulas, the Output Type Derivation
table, function return declarations, join nullability and emit order.

The script names its source files at [v0.102.0](https://github.com/substrait-io/substrait/tree/v0.102.0),
the release declared by the plans and pinned through substrait-packaging. Focused probes name
their own spec revision in [the probe guide](probe/README.md). Schemas use type-and-nullability
pairs: `[str, i64?]` here, `[["str", false], ["i64", true]]` in `expected.json`.

Case-specific expectations keep the oracle separate from plan generation and consumer output.
They are still one reading of the specification. Shared helpers such as `dec_return` and
`join_expected` can propagate a mistaken rule across a whole family, so independence from
the implementations does not establish correctness.

Ten cases also carry expected rows: eight set-operation cases transcribed from the spec's
examples and two window-bound cases. `probe/check_rows.py` compares these for three participants
as single-column multisets of integers. Other schemas can match while the returned values are
wrong; this corpus does not check rows for the two-column `emit_*` cases.

Ten cases carry no expectation. Seven of them wait on the spec, under `spec_silent`:

- Three have virtual-table row types or nullability different from the declared schema. The
  validity rule is unsettled; the examined Isthmus and Spark producers do not write such rows.
- An out-of-order projection mask `[2, 0]` has no settled output order. The spec says masks can
  only remove fields; all four participants applying this mask reorder the fields, four others
  ignore it, and Acero does not implement it.
- A lateral join without an anchor is permitted by `logical_relations.md` when the right input
  references no left row, but forbidden by `algebra.proto`. Python and DuckDB accept it; Java
  refuses it.
- Two `UpdateRel` cases give the root one name or two. The spec says "number of modified records"
  without defining an output schema. Java's core derives the table columns; Isthmus derives
  one `ROWCOUNT` column.

The other three, under `spec_says_invalid`, measure responses to invalid plans: a CTAS whose
input differs from `table_schema`, a root naming columns over a `DdlRel` with no output, and a
null row in a required virtual-table column. The last follows from `type_system.md`, which
restricts null to nullable types. Java's core, Isthmus and Spark reject it for that violation;
the validator rejects all `expressions` virtual tables, independently of the null. Other
participants reading virtual tables accept it.

## Corpus files

| | |
| --- | --- |
| `derived-schema/` | the 108 plans, protobuf-JSON and binary, beside a `manifest.json` saying per case what it pins, the schema expected of it and the spec rule that expectation comes from. Read that rather than the plan |
| `derived-schema-virtual-tables/` | the same cases carrying their own rows |
| `results/<NAME>.txt` | one column per implementation; `probe/matrix.py`, `probe/diffs.py` and `probe/heatmap.py` draw `results/MATRIX.txt`, `results/DIFFS.md` and the pictures out of them |
| `expected.json` | the expectations, written by `probe/expected.py` |
| `differed.json` | a reason per differing cell |
| `deriver/` | the same rules read a second time: an output schema computed from the plan and the spec text, by rules written separately from `probe/expected.py` and compared with it. [`deriver/README.md`](deriver/README.md) says what that establishes |

Everything keys on a case's file name, and nothing generated is edited by hand.

The generated schema corpus needs a JDK and a substrait-java checkout to add a plan. The
relation corpus is authored separately and compiles to protobuf test bundles; its
[authoring guide](tests/relations/README.md) covers setup and checks. Neither corpus takes an
implementation's answer as its expectation.

## What the corpus is made of

Plans are plain `substrait.Plan` protobuf-JSON, declaring spec 0.102. They are built with
substrait-java builders. Some reproduce fixed Java bugs; others exercise explicit rules for
set operations, read projection, aggregation phases and decimal arithmetic. Plan shapes and
declared types come from those builders; expectations come separately from the spec text.

Java's `JoinRecordTypeTest`, added in substrait-java change 1112, independently encodes the
same join rule as `join_expected` on different inputs. The source `AggregateRelTest` checks
grouping counts and round trips, not output schemas, so it supplies no equivalent cross-check.

`gen/make_manifest.sh` builds the manifest from generator output and joins expectations from
`expected.json`. `gen/sources.json` records source issues. Five cases have one so far; an entry
is added only when the case exercises the behaviour that the referenced change modified.
[gen/README.md](gen/README.md) describes generation and adding cases.

## Reviewing expectations

Independent review is still needed, especially for
[sixteen expectations relying on an unstated step](https://github.com/alexandrefimov/substrait-conformance-cases/issues/8),
thirteen of them joins. One expectation that contradicted the spec has already been corrected.
A wrong expectation can label a correct implementation as diverging.

The projection-mask question also needs a specification answer: DuckDB exports `[2, 0]` for
`SELECT c2, c0`, and every measured participant applying the mask uses the listed order, while
the spec says a mask can only remove fields. The case remains unscored.

## What moving these upstream would take

Substrait issue 1164 proposes a specification-owned corpus. This schema corpus has three
adoption constraints:

- Plans and expectations are separate files keyed by case name. The manifest and self-check
  enforce the pairing; copying a plan alone loses its expectation.
- Consuming a plan needs protobuf bindings, but regenerating this corpus needs a substrait-java
  checkout. In the spec repository that would be a dependency on one implementation.
- Plans declare spec 0.102; they are not version-agnostic fixtures.

The separate [relation corpus](tests/relations/README.md) uses protobuf test bundles carrying
the plan, input fixtures and expectations together.

## Calibration

The Java row in the [schema results](README.md#results) is calibration: the generators and
expectations were written by the same author, using Java builders. Its matches establish that
those encodings agree, not an independent review of the specification.

For example, `decimal_divide` of `dec(10,2)` by `dec(5,1)` is `dec(21,8)` under
`functions_arithmetic_decimal.yaml`. Java, Go, Python, the validator, Isthmus and Gluten return
that type; Spark returns `dec(17,8)`, DataFusion `dec(15,6)`, DuckDB `fp64` and Acero `dec(16,7)`.
The [expand cases](#the-two-expand-cases) expose disagreement even in the calibration row.

## The two expand cases

The spec orders expand fields before a duplicate-index column, without the "if applicable"
condition used for Aggregate's index. Java omits this column. Python returns it but loses the
nullability rule stated by `ExpandRel.SwitchingField`. The expectation was written before
either implementation was measured; each implements one of these two rules.

The index width is unsettled: `physical_relations.md` says i32 and `algebra.proto` says int64.
[Substrait issue 714](https://github.com/substrait-io/substrait/issues/714) tracks this conflict.
The expectation follows the documentation table. An i64 answer would therefore differ from
this expectation without the spec ruling that answer out; its reason must record that limit.

## What a match establishes

A consumer may repeat the plan's declared `output_type`. Such a match checks the declaration
against the expectation, not independent return-type inference. `probe/lie_matrix.sh` changes
only declared output types and records schema sensitivity in [results/LIE.txt](results/LIE.txt).

Five rows follow the changed declaration: 16 of substrait-java's matches, 15 of
substrait-python's, 13 each of substrait-go's and Isthmus's and 12 of the validator's are read
back. Only 29 of the 108 cases declare an output type, so the swap reaches no other case.

| | answers that move | of them with an expectation |
| --- | ---: | ---: |
| substrait-java | 17 | 16 |
| substrait-python | 15 | 15 |
| substrait-validator | 13 | 13 |
| substrait-go | 13 | 13 |
| Isthmus/Calcite | 13 | 13 |
| Acero | 0 | 0 |
| DataFusion | 0 | 0 |
| DuckDB | 0 | 0 |
| Spark | 0 | 0 |

For Java, the seventeen moving answers are the decimal, aggregate, nullability, predicate,
aggregation-phase and window cases, plus the unscored CTAS. Its twelve held `joineq_*` answers
do not establish inference: the changed declaration belongs to a predicate whose type never
reaches the output schema.

Acero, DataFusion, DuckDB and Spark hold their answers. That alone proves no derivation.
Their `decimal_divide` answers differ from the original declaration, which establishes that
they did not simply repeat it on that case.

29 of the 108 cases carry an `output_type` and 28 of those have an expectation. The remaining 70
scored plans declare none. These counts measure sensitivity, not independently derived schemas.

The swap preserves struct arity so a rejection cannot be explained by changed root-name counts.
It changes neither expressions nor `ReadRel.base_schema`; it therefore does not test function
binding or input-schema handling. Gluten is outside this experiment.

## Whether the call is bound at all

Binding and return-type inference are separate: a consumer can resolve a function and still
repeat its declared type. `probe/binding_matrix.sh` rewrites extension-function names while
preserving the rest of each plan. [results/BINDING.txt](results/BINDING.txt) records the run.

The rewrites use a compatible control, an existing key with mismatched argument types, an
undeclared signature and an unknown name. All nine participants accept the control. None
rejects `sum:i8` over an i64 argument, and its result is unchanged from `sum:i64`: looking up a
key does not establish that the call was checked against it.

The measured paths differ:

- Java, Isthmus and Spark look up the compound key in the loaded extension.
- DuckDB, DataFusion and Acero resolve the short name against their engine registry.
- Python resolves neither the declaration nor the function and emits no binding diagnostic.
- The validator warns about skipped YAML resolution, or unrecognised `name` and `impls` with
  resolution enabled. Its retained schema does not establish binding.
- Go fails while parsing the suffix as a type string, before lookup, so its counts describe
  parsing rather than binding.

Python both follows swapped output types and resolves no function, so those answers provide
no evidence of extension-based inference.

## What has already been corrected

Review has corrected three kinds of claim:

- Held answers in the swap were misread as independently derived, although the changed join
  predicate could not affect the output schema.
- DuckDB stack traces made saved answers machine-dependent. `normalize.py` now keeps the
  message and removes the trace; `OUT=` retains raw output. Answer-by-answer replay detected
  this where comparing totals had not.
- Reasons in `differed.json` described some cells incorrectly. Each reason now carries a
  test of an output property; that test checks the description, not its causal explanation.

Self-checks establish consistency between committed artifacts. The independent
[deriver](deriver/README.md) agrees with every scored expectation, but that is two encodings
of the same spec text, not proof that either reading is correct.

## What a case is worth as a test

`deriver/mutants.py` substitutes plausible alternative readings of specification rules and
derives the scored cases again. A changed answer shows that a case distinguishes those readings.
[COVERAGE.txt](deriver/COVERAGE.txt) records the rule results;
[PINNED.txt](deriver/PINNED.txt) records which cases distinguish each reading.

The first run missed seven readings, including aggregate grouping-before-measure order, MIRROR
nullability and the grouping-set index. Three added cases closed four gaps and exposed seven
new differing cells. The index came back as i32 from Java and Python, i64 from Isthmus and UInt8
from DataFusion.

Three readings remain undistinguished. Two are unobservable in valid plans: set inputs must
agree on field types, and write input must match `table_schema`. The third is the unresolved
projection-mask order; the deriver declines it rather than asserting a choice.

The battery covers only its authored alternatives. A rule without an alternative is absent,
not proved covered. Per-case results identify readings that would lose their sole check if a
particular case were removed.

## Acero input-schema correction

The Acero table provider materializes synthetic input tables using the decoded
`ReadRel.base_schema`, following the [Arrow callback contract](https://arrow.apache.org/docs/python/generated/pyarrow.substrait.run_query.html).
This supplies input types, not an expected output schema.

The former provider registered `t_str` with plain string and binary, stripping lengths before
execution. Correcting it made `stringlen_declared` match: Acero preserves varchar and fixed-char
lengths as Arrow extension types and fixed-binary width as a fixed-size binary type. Normalization
retains those widths and nullability.

Retaking the then-78-case column at the same PyArrow pin changed only that case; its old reason
was removed. A match on a bare read establishes input-schema preservation, not function-type
inference. A partial retake changes only the measured column's date.

## Reports and generator sources

`differed.json` carries a reason written by hand for all 74 of them, 16 marked as something other
than a divergence. Of those, six are limits of a type system, ten a type the validator never resolved.
The explanations record judgments about saved cells: sixteen of its twenty-one reasons link an issue or PR.
A linked fix does not change a saved answer; the column must be retaken to measure it.
`probe/check_differed.py` tests each reason's output property, not its causal explanation.
Each column's header states its comparison limits; DuckDB and Gluten carry no nullability.

[FINDINGS.md](FINDINGS.md) maps reports to reproducers, including rejected plans and producer
diagnostics outside the differing cells. Source attribution in `gen/sources.json` is separate:
it identifies where a case originated, not every report the case now reproduces.

Ordinary unsupported responses need no defect claim. [refused.json](refused.json) instead
records eleven cells where a participant died rather than refused, ten in DuckDB and one in
Acero. Each has a tested reason and triage. Comparing unsupported responses with declared engine
capabilities is limited by the spec: at v0.102.0, `dialects/` contains a schema and fixtures but
no engine capability files.

Triage is per reason and participant, and there are twenty-three of them;
two of those twenty-three still need investigation. Entries are `reported`, `spec-question`, `ours` or `open`. `open` may
mean a narrower reproducer or ownership decision is still needed; `ours` identifies an expectation
or harness error. A reported entry may link an existing PR without a separate issue, with its
coverage limits recorded. It establishes neither a merged fix nor a retaken measurement.
Every divergence needs triage for each affected participant; only divergences carry it, and
every report link must appear in FINDINGS.md.

## What the corpus covers

`probe/coverage.py` counts relation coverage from the plans. The generated block below is
checked by `probe/selfcheck.sh`:

<!-- coverage: written by probe/coverage.py, checked by probe/selfcheck.sh -->
| relation | cases | | relation | cases |
| --- | ---: | --- | --- | ---: |
| `read` | 106 | | `write` | 1 |
| `filter` | 1 | | `ddl` | 2 |
| `fetch` | 1 | | `update` | 2 |
| `aggregate` | 9 | | `hash_join` | 4 |
| `sort` | 1 | | `merge_join` | 4 |
| `join` | 26 | | `nested_loop_join` | 4 |
| `lateral_join` | 2 | | `window` | 3 |
| `project` | 10 | | `expand` | 2 |
| `set` | 16 | | `top_n` | 1 |
| `cross` | 1 | | | |

19 of the 24 relations `algebra.proto` defines at spec 0.102.0 appear in these 108 plans; `filter`, `fetch` and `sort` only under an emit mapping, which needs something to sit on. No case reaches `extension_single`, `extension_multi`, `extension_leaf`, `reference`, `exchange`.
<!-- /coverage -->

Apache 2.0, the plans included, so a case can go straight into another project's tests.
