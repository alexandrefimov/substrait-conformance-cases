# Substrait conformance cases: declared type against derived type

[![selfcheck](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml/badge.svg)](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml)

**[Every case against every implementation](https://alexandrefimov.github.io/substrait-conformance-cases/)** —
the matrix as a page, with the expectation and the answer beside each cell.

A plan declares types and a consumer derives them again — or repeats what the plan declared — and
when the two disagree, nothing in the format notices. The main comparison corpus contains 98 plans
built to make such disagreements visible, an expected schema for 93 of them, and probes that put the
corpus through ten implementations. Take `decimal_divide`, `dec(10,2)` over `dec(5,1)`, where
`functions_arithmetic_decimal.yaml` gives `dec(21,8)`:

    substrait-java, substrait-go, substrait-python, validator, Isthmus, Gluten   dec(21,8)
    Spark        dec(17,8)
    DataFusion   dec(15,6)
    DuckDB       fp64
    Acero        dec(16,7)

Every expectation is written by hand, from the spec text at v0.102.0, into `probe/expected.py`,
which reads no plan and no consumer output. [METHOD.md](METHOD.md) says where one comes from and
what a match proves.

## What the corpus says

The columns were taken 2026-09-09 against the versions in `probe/versions.env`; the weekly `drift`
run records what has moved since, in `results/DRIFT.txt`. They answer the 93 cases that carry an
expectation. The nine in the table are consumer paths rather than engines — the Java core, Isthmus
and Spark all go through substrait-java, DuckDB through its substrait extension — and Gluten, the
tenth, runs over the virtual-table variant in a cluster.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/matrix-dark.svg">
  <img src="docs/matrix.svg" width="838"
       alt="The corpus as a grid, cases down and implementations across: matched cells in a quiet
            grey, divergences in red, plans an implementation does not accept left as empty
            outlines, and limits of a type system hatched.">
</picture>

Matched in grey, differed in red, a plan the implementation does not accept as an outline, a limit
of its type system hatched.

| | matched | differed | unsupported |
| --- | ---: | ---: | ---: |
| substrait-java | 88 | 2 | 3 |
| substrait-python | 68 | 24 | 1 |
| substrait-go | 59 | 4 | 30 |
| substrait-validator | 47 | 28 | 18 |
| Isthmus/Calcite | 51 | 5 | 37 |
| DataFusion | 54 | 9 | 30 |
| DuckDB | 34 | 20 | 39 |
| Spark | 29 | 6 | 58 |
| Acero | 4 | 15 | 74 |

**The first row is calibration, not a result.** Most plans are built with substrait-java builders,
by the person who also wrote the generators and the expectations, so its 88 matches say that two
encodings of a spec rule agree. [METHOD.md](METHOD.md) has the experiment that swaps a declared
`output_type` for a false one and finds Java's answer following it, and
[the two `expand` cells](METHOD.md#the-two-expand-cases) where even this row differs.

*Unsupported* is a plan that came back without a comparable schema: refused, an error, a crash. So
read *differed* against *matched + differed*, not against 93. *Differed* means the answer disagrees
with this repository's reading of the spec, which is not the same as a defect:
`differed.json` carries a reason written by hand for all 113 of them, 17 marked as something other
than a divergence, and `probe/check_differed.py` tests every reason against the saved column. A
column is also compared only as far as its own type system reaches — DuckDB's logical types carry no
nullability, nor do Gluten's — and one that stops short says so in the head of its
`results/<NAME>.txt`.

## What would help

- **For a participant's maintainer: [`results/DIFFS.md`](results/DIFFS.md)** — the cases that differ
  for you, each with the expectation, the answer your build gave and what came of it; twenty of the
  twenty-four reasons already link an issue or PR. Running one needs nothing from this harness: the
  cases in `derived-schema-virtual-tables/` carry their own rows, so nothing has to be registered
  first.
- **A reading of `probe/expected.py` against the spec.** It is 93 expectations written by hand from
  the spec text, and nobody outside this repository has read them; a wrong one turns into a
  divergence reported against an implementation that was right. One rule's worth is enough: the
  join matrix, the five decimal cases, the set-operation table.
- **From the spec, one answer.** When a virtual table's rows disagree with the schema it declares —
  an i8 literal in an i32 column, a null in a required one — which wins? Four cases here go unscored
  pending one; the fifth case without an expectation is a plan invalid on purpose, where a refusal
  is the right answer.

## Running it

    bash probe/selfcheck.sh
    bash probe/replay_column.sh PYTHON|GO|DUCKDB|ACERO|VALIDATOR|JAVA|ISTHMUS|SPARK|DATAFUSION
    python3 probe/check_expected.py results/<NAME>.txt <format>

The first recomputes every number on this page from the committed files; it needs python3 and
nothing else and takes seconds. The second builds one participant at its pinned version and requires
the saved column back, answer for answer — CI does that for all nine, on a machine that is not this
one, though nobody outside this project has run the sweep. The third reproduces one row of the table
and names the cases behind it. If a number here is wrong, that is a bug worth an issue.
[`probe/README.md`](probe/README.md) has the prerequisites, how far each column is compared, the
Spark runtime profiles, the `LATEST=1` drift run and `reverify.sh`.

## What is here

| | |
| --- | --- |
| `derived-schema/` | the 98 plans, protobuf-JSON and binary, beside a `manifest.json` saying per case what it pins, the schema expected of it and the spec rule that expectation comes from. Read that rather than the plan |
| `derived-schema-virtual-tables/` | the same cases carrying their own rows |
| `results/<NAME>.txt` | one column per implementation; `probe/matrix.py`, `probe/diffs.py` and `probe/heatmap.py` draw `results/MATRIX.txt`, `results/DIFFS.md` and the pictures out of them |
| `expected.json` | the expectations, written by `probe/expected.py` |
| `differed.json` | a reason per differing cell |

Everything keys on a case's file name, and nothing generated is edited by hand.

Whether cases like these belong in the spec repository is under discussion in
[substrait#1164](https://github.com/substrait-io/substrait/issues/1164); this repository is where
they live meanwhile. The function test cases the spec ships check what a scalar function returns;
these compare schemas across relations. Adding one costs a JDK and a substrait-java checkout — the
generators build the plans with that library's builders, and [`gen/README.md`](gen/README.md) says
how. [METHOD.md](METHOD.md) is the method and what a match proves; [FINDINGS.md](FINDINGS.md) the
way from a report back to the cases that reproduce it.

## What it covers

The matrix above is depth. Breadth is the other half substrait#1164 asks for — which relations the
cases reach at all — and `probe/coverage.py` counts that from the plans themselves:

<!-- coverage: written by probe/coverage.py, checked by probe/selfcheck.sh -->
| relation | cases | | relation | cases |
| --- | ---: | --- | --- | ---: |
| `read` | 98 | | `cross` | 1 |
| `filter` | 1 | | `write` | 1 |
| `fetch` | 1 | | `hash_join` | 4 |
| `aggregate` | 7 | | `merge_join` | 4 |
| `sort` | 1 | | `nested_loop_join` | 4 |
| `join` | 26 | | `window` | 3 |
| `project` | 9 | | `expand` | 2 |
| `set` | 16 | | `top_n` | 1 |

16 of the 24 relations `algebra.proto` defines at spec 0.102.0 appear in these 98 plans; `filter`, `fetch` and `sort` only under an emit mapping, which needs something to sit on. No case reaches `lateral_join`, `extension_single`, `extension_multi`, `extension_leaf`, `reference`, `ddl`, `update`, `exchange`.
<!-- /coverage -->

Apache 2.0, the plans included, so a case can go straight into another project's tests.
