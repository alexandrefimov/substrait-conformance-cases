# Substrait conformance cases

[![selfcheck](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml/badge.svg)](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml)

Executable cases comparing Substrait output schemas and relation semantics across libraries and
engines. Expectations are written from the specification text they cite, independently of the
implementation answers. The authored corpora target Substrait v0.102.0 and support the
[relation conformance proposal](https://github.com/substrait-io/substrait/issues/1164).

## Corpora

| Corpus | Scope | Participants |
| --- | --- | --- |
| [`derived-schema/`](derived-schema) | 108 generated plans testing schema derivation | substrait-java, substrait-python, substrait-go, substrait-validator, Isthmus/Calcite, DataFusion, DuckDB, Spark, Acero, Gluten |
| [`tests/relations/`](tests/relations) | 71 hand-written cases testing relation schemas and rows | substrait-java, substrait-go, DuckDB, DataFusion |
| [`producers/`](producers) | SQL-produced plans: declared types, bindings and consumer schemas | DuckDB, Isthmus, Spark and DataFusion producers; schema consumers |

The [results on GitHub Pages](https://alexandrefimov.github.io/substrait-conformance-cases/) show the
expectation and saved answer for each cell in the authored corpora.
[Schema differences](results/DIFFS.md) groups differing cases by participant; [FINDINGS.md](FINDINGS.md) links reproducers to upstream reports.

Producer plans are checked against the deriver's reading of v0.102.0, without a second oracle.
Their [results](results/producers) include a [consumer matrix](results/producers/CONSUME.txt);
schema comparisons establish neither row correctness nor general plan validity.

## Results

The schema columns were taken 2026-10-06 against the versions in
[`probe/versions.env`](probe/versions.env). They answer the 98 cases that carry an expectation.
Gluten is measured separately over the virtual-table variant and is outside the table below.

| | matched | differed | unsupported |
| --- | ---: | ---: | ---: |
| substrait-java | 92 | 3 | 3 |
| substrait-python | 95 | 1 | 2 |
| substrait-go | 69 | 2 | 27 |
| substrait-validator | 64 | 14 | 20 |
| Isthmus/Calcite | 57 | 4 | 37 |
| DataFusion | 59 | 7 | 32 |
| DuckDB | 36 | 21 | 41 |
| Spark | 31 | 6 | 61 |
| Acero | 4 | 16 | 78 |

A difference is a disagreement with this repository's reading of the specification, not proof
of a defect. The columns measure different consumer APIs and type systems; totals do not rank
engines. A schema match alone establishes neither correct rows nor independent type derivation.
The Java row is [calibration](METHOD.md#calibration); the [expand cases](METHOD.md#the-two-expand-cases)
illustrate its limits. [METHOD.md](METHOD.md) explains these boundaries and the declaration swap.

The [relation matrix](https://alexandrefimov.github.io/substrait-conformance-cases/#relations)
compares schemas and, for executing participants, rows. Its [measurement notes](probe/relations/README.md#saved-results)
describe the saved results and each participant's comparison limits.

## Reproduction

From the repository root:

```sh
bash probe/selfcheck.sh                    # committed-file checks; python3, no network
bash probe/replay_column.sh DUCKDB          # pinned schema column
bash probe/relations/replay.sh DUCKDB       # pinned relation column
```

Each replay downloads and builds the named participant, then requires the saved answers back.
The [schema probe guide](probe/README.md) and [relation probe guide](probe/relations/README.md)
list participant names and prerequisites. Gluten has a separate run path. The self-check
executes no participant and does not validate the specification reading.

## Documentation

- [Method](METHOD.md): expectation sources, calibration, coverage and measurement limits.
- [Findings](FINDINGS.md): specification questions, implementation reports and reproducers.
- [Relation test vectors](tests/relations/README.md): protobuf bundle contract and case authoring.
- [Generators](gen/README.md): building and extending the schema corpus.
- [Independent deriver](deriver/README.md): a second encoding of the specification rules.
- [Producer corpus](producers/README.md): saved SQL-produced plans, declaration checks and consumer results.
- [Producer shapes](probe/producer-shapes/README.md): plans from SQL passed between implementations.

Expectation corrections should name the case and the specification rule. Outstanding review
questions are listed in [METHOD.md](METHOD.md#reviewing-expectations).
