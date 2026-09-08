# Substrait conformance cases: declared type against derived type

[![selfcheck](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml/badge.svg)](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml)

**[Every case against every implementation](https://alexandrefimov.github.io/substrait-conformance-cases/)** —
the matrix as a page, with the expectation and the answer beside each cell.

A plan declares types and a consumer derives them again — or reuses what the plan declared. When
the two disagree, nothing in the format notices. The main comparison corpus contains 83 plans built
to make such disagreements visible, an expected schema for 78 of them, and probes that put the corpus
through ten implementations.

[Focused diagnostics](probe/README.md#focused-schema-diagnostics) also include
minimal consumer cases with controls and checks of producer output. These can be
run separately and are not counted in the saved 83-plan matrix.

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

(Types are shown in the corpus's own notation; `results/<NAME>.txt` keeps each implementation's spelling.)

## What would help

Three things, in the order they are worth someone's time:

- **A reading of `probe/expected.py` against the spec.** It is 78 expectations written by hand from
  the spec text; nobody outside this repository has checked them, and an expectation that is wrong
  turns into a divergence reported against an implementation that was right.
- **For a participant's maintainer: the cases that differ for you.** `differed.json` names them per
  participant with a reason each — 28 for the validator, 18 for DuckDB, 17 for substrait-python,
  16 for Acero — as plans you can take into your own tests without any of this harness.
- **One answer from the spec.** When a virtual table's rows disagree with the schema it declares —
  an i8 literal in an i32 column, a null in a required one — which wins? Four cases here go unscored
  pending clarification of exact type equality versus compatibility. We have not found an explicit
  rule that resolves this question.

Whether cases like these belong in the spec repository is the question under discussion in
[substrait#1164](https://github.com/substrait-io/substrait/issues/1164). This repository is where
they live meanwhile, kept reproducible: a case is added by adding a generator to `gen/`, any of
the nine columns is retaken by `probe/replay_column.sh` on any machine, and if a number on this
page is wrong, that is a bug here and worth an issue.

## What the corpus says

The columns saved here were taken 2026-09-08 against the versions in `probe/versions.env`, which
each column's own first line names again. They answer the 78 cases that carry an expectation:

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
| substrait-java | 76 | 2 | 0 |
| substrait-python | 59 | 18 | 1 |
| substrait-go | 55 | 2 | 21 |
| substrait-validator | 45 | 28 | 5 |
| Isthmus/Calcite | 49 | 5 | 24 |
| DataFusion | 52 | 9 | 17 |
| DuckDB | 33 | 19 | 26 |
| Spark | 28 | 6 | 44 |
| Acero | 3 | 15 | 60 |

**The first row is calibration, not a result.** Most plans are built with substrait-java builders,
and the same person wrote the generators, the expectations and part of substrait-java. Its 76
matches say the two encodings of a spec rule agree. They do not say the consumer derived anything:
swap a declared `output_type` for a false one and Java's answer follows it on ten of the 22 scored
cases that carry one, as do substrait-python and the validator. [METHOD.md](METHOD.md) has that
experiment, its tallies and what it cannot reach.

That row is no longer clean, and the two cells that broke it are the point of having it. Both are
`expand`, where the spec's output order is the expand fields followed by an i32 column carrying the
index of the duplicate a row came from; substrait-java stops at the fields. The expectation was
written from that sentence before any implementation was asked, and substrait-python — which
derives the third column and loses the nullability rule substrait-java gets right — is what keeps
the reading from being this repository's alone. Neither is filed: two implementations each carrying
one of the relation's two rules may be a question for the spec as much as a defect in either.

These are nine consumer paths rather than nine engines — the Java core, Isthmus and Spark paths
share substrait-java, Isthmus adding Calcite conversion and Spark its Catalyst one. Gluten has a
separate cluster run over the virtual-table variant and is outside this comparison. *Unsupported*
means the probe produced no comparable schema: rejections, errors and crashes. Read *differed*
against *matched + differed*; the unsupported count records the rest of the cases.

*Differed* means the answer disagrees with this repository's reading of the spec, and not every such
cell is a defect. `differed.json` gives all 104 of them a reason and marks 17 as something other than
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

## What is here

The corpus is `derived-schema/` — 83 plans as protobuf-JSON and as binary protobuf, with a
`manifest.json` describing every one — plus `derived-schema-virtual-tables/`, the same cases rewritten
for Gluten, which reads only `virtual_table` and `local_files` out of a `ReadRel`. The answers are
`results/<NAME>.txt`, one file per implementation, gathered by `probe/matrix.py` into
`results/MATRIX.txt`. The expectations are `expected.json`, generated by `probe/expected.py`; the
reasons are `differed.json`; the drawings are `docs/matrix.svg`, `docs/matrix-dark.svg` and
`docs/index.html`, written by `probe/heatmap.py`.

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

The self-checks verify relationships between committed artifacts. They do not establish that every
encoded rule matches the spec or that every interpretation of a result is correct.
[METHOD.md](METHOD.md) records what has already been corrected here; these are open:

- The rules encoded in `probe/expected.py` need independent review against the spec.
- Two of the twenty-four divergence-and-participant pairs in `differed.json` still need
  investigation: Acero output nullability beyond direct field projections and Spark decimal nullability.
  Each says what is missing. Existing reports can cover only part of a linked observation, so
  their notes also matter. `open` is an allowed answer; a link does not prove a fix. The count is
  written down and `probe/check_differed.py` compares it.
- Rows are compared for three participants and ten cases; schemas for nine participants and 78
  cases. Five of the 83 cases link to the issue they came from; the rest record only their generator
  and the rule expected of them.
- The full sweep has run on this machine and in a container on clean Ubuntu 24.04, cloning this
  repository anonymously: nine columns, every tally matching the ones above. Nobody outside this
  project has run it. CI now retakes all nine on a machine that is not this one, each from the
  versions `probe/versions.env` pins, and otherwise only reads the repository against itself.
  Gluten, the tenth participant, runs in a cluster and its column is still taken by hand.
- What the columns say is dated: each is a measurement against one version. When a release moves
  an answer, the weekly `drift` run records it in `results/DRIFT.txt`, so the history starts
  from the day that file was added and says nothing about anything before it.

Apache 2.0.
