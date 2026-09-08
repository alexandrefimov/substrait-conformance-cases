# Substrait conformance cases: declared type against derived type

[![selfcheck](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml/badge.svg)](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml)

**[Every case against every implementation](https://alexandrefimov.github.io/substrait-conformance-cases/)** —
the matrix as a page, with the expectation and the answer beside each cell.

A plan declares types and a consumer derives them again — or reuses what the plan declared. When
the two disagree, nothing in the format notices. The main comparison corpus contains 95 plans built
to make such disagreements visible, an expected schema for 90 of them, and probes that put the corpus
through ten implementations.

[Focused diagnostics](probe/README.md#focused-schema-diagnostics) also include
minimal consumer cases with controls and checks of producer output. These can be
run separately and are not counted in the saved 95-plan matrix.

The expectations are the part worth being suspicious of, so this is how they are made. Each one is
written by hand from the spec — the derivation tables, the decimal formulas, the relation rules — in
`probe/expected.py`, which reads no plan and no consumer output. Nothing here asks an implementation
what the answer should be. The spec repo already ships function test cases, which check what a
scalar function returns; these cases compare schemas across relations.

Take `decimal_divide`, which divides `dec(10,2)` by `dec(5,1)`. The formula in
`functions_arithmetic_decimal.yaml` gives `dec(21,8)`, which six consumer paths report:

    substrait-java, substrait-go, substrait-python, validator, Isthmus, Gluten   dec(21,8)
    Spark        dec(17,8)
    DataFusion   dec(15,6)
    DuckDB       fp64
    Acero        dec(16,7)

To judge whether a case says what it claims, start with `derived-schema/manifest.json` rather than
with the plan. Its entry per case says what the case pins, the schema the spec gives it, and the
rule that schema comes from:

    aggregate_grouping_field_shared_by_sets   written by GenCases, from substrait-java#1161
      A field grouped on by both sets is one output column, not two.
      expected [str, i64?] — Aggregate: only fields absent from some grouping set become nullable

The plan beside it is protobuf-JSON — 78 lines for that case, between 33 and 180 across the corpus.
That is the form an engine loads with the protobuf library it already has, and it is not a form
anyone should have to read to judge whether a case says what it claims.

## What would help

Three things, in the order they are worth someone's time:

- **A reading of `probe/expected.py` against the spec.** It is 90 expectations written by hand from
  the spec text; nobody outside this repository has checked them, and an expectation that is wrong
  turns into a divergence reported against an implementation that was right.
- **For a participant's maintainer: the cases that differ for you.**
  [`results/DIFFS.md`](results/DIFFS.md) has them per implementation — 28 for the validator, 24 for
  substrait-python, 20 for DuckDB, 15 for Acero — each with the expectation, the answer your build
  gave, why it is recorded as a difference and what came of it. The plans need no part of this
  harness, and `derived-schema-virtual-tables/` carries the same cases with their rows inside, so
  nothing has to be registered before one runs. The cases to skip on the way in are named in
  `expected.json`: `spec_silent` holds the ones the spec does not settle, and `spec_says_invalid`
  the one plan that is invalid on purpose, where a refusal is the right answer. [FINDINGS.md](FINDINGS.md) is the same evidence the
  other way round: from a report to the cases that reproduce it.
- **One answer from the spec.** When a virtual table's rows disagree with the schema it declares —
  an i8 literal in an i32 column, a null in a required one — which wins? Four cases here go unscored
  pending clarification of exact type equality versus compatibility. We have not found an explicit
  rule that resolves this question.

Whether cases like these belong in the spec repository is the question under discussion in
[substrait#1164](https://github.com/substrait-io/substrait/issues/1164). This repository is where
they live meanwhile, kept reproducible: a case is added by adding a generator to `gen/`, any of
the nine columns is retaken by `probe/replay_column.sh` on any machine, and if a number on this
page is wrong, that is a bug here and worth an issue. Adding a case costs a JDK and a
substrait-java checkout, since the generators build the plans with that library's builders. The plan
JSON is generated and never edited, so what a reviewer reads and what a merge conflicts over is a
generator rather than protobuf.

## What the corpus says

The columns saved here were taken 2026-09-08 against the versions in `probe/versions.env`, which
each column's own first line names again. They answer the 90 cases that carry an expectation:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/matrix-dark.svg">
  <img src="docs/matrix.svg" width="838"
       alt="The corpus as a grid, cases down and implementations across: matched cells in a quiet
            grey, divergences in red, plans an implementation does not accept left as empty
            outlines, and limits of a type system hatched.">
</picture>

Silence is drawn as an outline rather than as a colour, so a column of refusals cannot be read as a
column of wrong answers, and a limit of a type system is hatched rather than red.
[The same matrix as a page](https://alexandrefimov.github.io/substrait-conformance-cases/) puts the
expectation and the answer beside each cell.

| | matched | differed | unsupported |
| --- | ---: | ---: | ---: |
| substrait-java | 85 | 2 | 3 |
| substrait-python | 65 | 24 | 1 |
| substrait-go | 59 | 4 | 27 |
| substrait-validator | 47 | 28 | 15 |
| Isthmus/Calcite | 51 | 5 | 34 |
| DataFusion | 54 | 9 | 27 |
| DuckDB | 34 | 20 | 36 |
| Spark | 29 | 6 | 55 |
| Acero | 4 | 15 | 71 |

**The first row is calibration, not a result.** Most plans are built with substrait-java builders,
and the same person wrote the generators, the expectations and part of substrait-java. Its 85
matches say the two encodings of a spec rule agree. They do not say the consumer derived anything:
swap a declared `output_type` for a false one and Java's answer follows it on ten of the 22 scored
cases that carry one, as do substrait-python and the validator. [METHOD.md](METHOD.md) has that
experiment, its tallies and what it cannot reach.

That row is no longer clean, and the two cells that broke it are the point of having it. Both are
`expand`: substrait-java returns a column fewer than the spec's output order gives, and
substrait-python, which returns that column, loses a nullability rule substrait-java gets right.
Neither is filed and neither waits on the spec; [METHOD.md](METHOD.md#the-two-expand-cases) has the
sentences each answer is short of, and the one thing the spec does leave open there.

These are nine consumer paths rather than nine engines — the Java core, Isthmus and Spark paths
share substrait-java, Isthmus adding Calcite conversion and Spark its Catalyst one. Gluten has a
separate cluster run over the virtual-table variant and is outside this comparison. *Unsupported*
means the probe produced no comparable schema: rejections, errors and crashes. Read *differed*
against *matched + differed*; the unsupported count records the rest of the cases.

*Differed* means the answer disagrees with this repository's reading of the spec, and not every such
cell is a defect. `differed.json` gives all 113 of them a reason and marks 17 as something other than
a divergence: six are limits of a type system, eleven a type the validator never resolved. Each
reason carries a property that `probe/check_differed.py` tests against the saved column or the case
inputs, so a reason cannot quietly describe a cell it does not fit; the cause it states still needs
a human reading. Naming is not counted as disagreement: where an engine spells types its own way,
`probe/check_expected.py` maps the vocabularies onto each other, so `Decimal128(38,10)` and
`decimal<38,10>` are the same answer. To reproduce one row of the table and see the cases behind it:
`probe/check_expected.py results/<NAME>.txt <format>`.

A column also has a reach, and a number read past it says nothing. The first line of each
`results/<NAME>.txt` says how far that one goes:

| | how far the column goes |
| --- | --- |
| DuckDB | carries no nullability in its logical types, so only types, arity and column order are compared. Comparing nullability would record the boundary of its type system as a divergence |
| DataFusion, DuckDB | have no string type with a length. Neither can represent `varchar<10>` or `fixedchar<5>`, which is why `stringlen_declared` differs there — not a defect |
| Acero, Spark | do carry nullability and are compared on it |
| Gluten | carries no nullability either, and repeats a function's declared type instead of deriving it |
| substrait-validator | the pinned revision retains declared function return types; schema output must be read alongside diagnostics. The mutation checks final output schemas, not every expression's type |

## What it covers

The picture above is depth: the cases are grouped by the behaviour each one pins. Breadth is the
other half substrait#1164 asks for — which relations the cases reach at all — and `probe/coverage.py`
counts that from the plans themselves:

<!-- coverage: written by probe/coverage.py, checked by probe/selfcheck.sh -->
| relation | cases | | relation | cases |
| --- | ---: | --- | --- | ---: |
| `read` | 95 | | `cross` | 1 |
| `filter` | 1 | | `write` | 1 |
| `fetch` | 1 | | `hash_join` | 3 |
| `aggregate` | 7 | | `merge_join` | 3 |
| `sort` | 1 | | `nested_loop_join` | 3 |
| `join` | 26 | | `window` | 3 |
| `project` | 9 | | `expand` | 2 |
| `set` | 16 | | `top_n` | 1 |

16 of the 24 relations `algebra.proto` defines at spec 0.102.0 appear in these 95 plans. The other 8 carry no case: `lateral_join`, `extension_single`, `extension_multi`, `extension_leaf`, `reference`, `ddl`, `update`, `exchange`. Three of the ones that do — `filter`, `fetch` and `sort` — appear only under an emit mapping, where the mapping is the subject and the relation is what it sits on.
<!-- /coverage -->

## What is here

Types on this page and in `expected.json` are in one normalized spelling — `i64`, `str`,
`dec(21,8)`, `vchar(10)`, `precision_timestamp(6)` — with `?` on a nullable field and nothing on a
required one. The plans carry protobuf type messages, and `results/<NAME>.txt` keeps whatever each
implementation calls the same type; `probe/check_expected.py` is where the three meet, and an
implementation taking these cases has that mapping to do for itself.

The corpus is `derived-schema/` — 95 plans as protobuf-JSON and as binary protobuf, with a
`manifest.json` describing every one — plus `derived-schema-virtual-tables/`, the same cases carrying
their own rows in a `virtual_table`, so a case runs with nothing registered first. Gluten needs that
form, reading only `virtual_table` and `local_files` out of a `ReadRel`, and it is also the form to
take into someone else's tests. The answers are `results/<NAME>.txt`, one file per implementation,
gathered by `probe/matrix.py` into `results/MATRIX.txt` and, per implementation, into
`results/DIFFS.md` by `probe/diffs.py`. The expectations are `expected.json`, generated by
`probe/expected.py`; the reasons are `differed.json`; the drawings are `docs/matrix.svg`,
`docs/matrix-dark.svg` and `docs/index.html`, written by `probe/heatmap.py`. A case is named by its
file name, and that name is what `expected.json`, `differed.json`, every column and
`results/DIFFS.md` key on: it is the identifier, it is not reused for a different case, and a rename
is named in the commit that makes it.

Further reading: [FINDINGS.md](FINDINGS.md) maps reported findings to cases, probes, issues and implementation PRs.

The other three pages: [METHOD.md](METHOD.md) — where an expectation comes from, what a match
proves, what has been corrected here. [`probe/README.md`](probe/README.md) — the probes, the pinned
versions, the environment, and what makes a run fail rather than report.
[`gen/README.md`](gen/README.md) — how a case is built and why the leaves are named tables.

## Running it

Reading the repository against itself needs python3 and nothing else, takes seconds, and is what CI
runs. It recomputes the numbers on this page from the committed files and compares them:

    bash probe/selfcheck.sh

Retaking one column needs nothing but the toolchain that participant installs with. It builds that
environment from the pinned version, puts the corpus through it and requires the answers to be
identical to the saved column:

    bash probe/replay_column.sh PYTHON|GO|DUCKDB|ACERO|VALIDATOR|JAVA|ISTHMUS|SPARK|DATAFUSION

`LATEST=1` selects current package releases or repository heads through `probe/versions-latest.env`
and reports what moved rather than failing on it; that is the weekly `drift` workflow. Spark follows
the selected substrait-java checkout's 3.5 variant, so this does not cover newer Spark patch releases
independently or Spark 4. The separate [Spark runtime profiles](probe/README.md#separate-spark-runtime-profiles)
run Spark 3.5.9, 4.0.4, 4.1.3 and 4.2.0 in both ANSI modes, plus focused decimal and overflow
diagnostics. Their CI artifacts report observations without replacing the saved matrix.
Repeating all nine columns is
`probe/reverify.sh`, which needs a substrait-java checkout, a DataFusion checkout and several
toolchains, and the Gluten column is taken separately, in a cluster;
[`probe/README.md`](probe/README.md) has the prerequisites and the commands.

## What is not settled

The self-checks compare committed artifacts with each other, which is a narrower thing than either
of the two questions a reader has: whether a rule is encoded as the spec means it, and whether a
result is read correctly. [METHOD.md](METHOD.md) records what has already been corrected here;
these are open:

- The rules encoded in `probe/expected.py` need independent review against the spec.
- One of the twenty-eight divergence-and-participant pairs in `differed.json` still needs
  investigation: Acero output nullability beyond direct field projections, which says what is
  missing. The three that stood beside it have since been reported, and Spark decimal nullability
  has become a question asked of the spec instead. Existing reports can cover only part of a linked
  observation, so their notes also matter. `open` is an allowed answer; a link does not prove a fix.
  The count is written down and `probe/check_differed.py` compares it.
- Rows are compared for three participants and ten cases; schemas for nine participants and 90
  cases. Five of the 95 cases link to the issue they came from; the rest record only their generator
  and the rule expected of them.
- The full sweep has run on this machine and in a container on clean Ubuntu 24.04, cloning this
  repository anonymously: nine columns, every tally matching the ones above. Nobody outside this
  project has run it. CI now retakes all nine on a machine that is not this one, each from the
  versions `probe/versions.env` pins, and otherwise only reads the repository against itself.
  Gluten, the tenth participant, runs in a cluster and its column is still taken by hand.
- What the columns say is dated: each is a measurement against one version. When a release moves
  an answer, the weekly `drift` run records it in `results/DRIFT.txt`, so the history starts
  from the day that file was added and says nothing about anything before it.

Apache 2.0 — the plans, the generators, the probes and these pages alike, so a case can be taken
into another project's tests under it.
