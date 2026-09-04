# Substrait conformance cases: declared type against derived type

A plan declares types and a consumer derives them again; when the two disagree, nothing in the format
notices. This repository holds 78 plans built to make such disagreements visible, an expected schema
for 73 of them computed from the spec rather than from any implementation, and the harness that puts
the corpus through ten implementations. The spec repo already ships function test cases, which check
what a scalar function returns; these are whole plans, and what they check is schema derivation
across relations.

It is a lab rather than a proposal: the corpus and the harness, kept reproducible.

Take `decimal_divide`, which divides `dec(10,2)` by `dec(5,1)`. The formula in
`functions_arithmetic_decimal.yaml` gives `dec(21,8)`, and so do six of the ten:

    substrait-java, substrait-go, substrait-python, validator, Isthmus, Gluten   dec(21,8)
    Spark        dec(17,8)
    DataFusion   dec(15,6)
    DuckDB       fp64
    Acero        dec(16,7)

(Types are shown in the corpus's own notation; `<NAME>.txt` keeps each implementation's spelling.)

## What the corpus says

The columns saved here, taken 2026-09-04 against the versions in `probe/versions.env`, answer the 73
cases that have an expectation like this:

| | matched | differed | unsupported |
| --- | ---: | ---: | ---: |
| substrait-java | 73 | 0 | 0 |
| substrait-python | 56 | 17 | 0 |
| substrait-go | 55 | 2 | 16 |
| substrait-validator | 45 | 28 | 0 |
| Isthmus/Calcite | 49 | 5 | 19 |
| DataFusion | 52 | 9 | 12 |
| DuckDB | 33 | 18 | 22 |
| Spark | 26 | 6 | 41 |
| Acero | 2 | 16 | 55 |

Nine rows for ten implementations: Gluten is missing because it repeats a function's declared type
instead of deriving one, so comparing it against a derived expectation would measure nothing.
*Unsupported* means the implementation rejected the plan, which is a fact about coverage rather than
a divergence in derivation. *Differed* means the answer disagrees with this repository's reading of
the spec — some of those have been filed against the implementations and some have not, and the
corpus does not record which. Not every *differed* cell is a defect either: `stringlen_declared`
differs for DataFusion and DuckDB because neither type system has a string with a length, and the
per-column boundaries below say where else that applies. `reverify.sh` reproduces the whole table,
and `probe/check_expected.py <NAME>.txt <format>` reproduces one row and names the cases behind it.

**One caveat.** The zero in the first row is worth less than it looks. On some cases the answer is
not derived at all: the implementation repeats the `output_type` the plan declares, and this
repository's own generator wrote that declaration from the same rule the expectation uses. There the
check compares the generator with itself.

Which cases those are is measured rather than guessed. `probe/lie_matrix.sh` swaps every declared
`output_type` for a false one, changes nothing else, and reports whose answer moves with it; an
answer that moves is an answer that depends on the declaration. `LIE.txt` is a saved run.

| | answers that move | of them with an expectation | expectations left |
| --- | ---: | ---: | ---: |
| substrait-java | 10 | 9 | 63, and one it cannot judge |
| substrait-python | 10 | 10 | 63 |
| substrait-validator | 10 | 10 | 63 |
| DuckDB | 0 | 0 | 73 |

For substrait-java the ten are the five decimal cases, the three `narrowing_*` predicates,
`phase_final` and `ctas_keeps_declared_schema` — the last of which carries no expectation. The case
it cannot judge is `phase_intermediate`: the swap turns a struct `output_type` into a scalar, which
leaves three names in `Plan.Root` above one column, and substrait-java then rejects the plan over the
names rather than over the type.

Two limits on reading that as *derived*. The swap perturbs `output_type` and nothing else, so an
answer that holds is proven not to be copied **from that field** — it is not thereby proven to be
derived, because a relation's schema also comes from `ReadRel.base_schema`, which the swap leaves
alone. And only these four participants were measured; for DataFusion, substrait-go, Acero, Spark,
Isthmus and Gluten the copy discount is simply not known.

## Where the expectations come from

`probe/expected.py` computes them from four sources and records which one it used per case: the
decimal formulas of `functions_arithmetic_decimal.yaml`, re-implemented; the Output Type Derivation
table printed in the spec; a function's declared return in its YAML; and the spec's rules for each
side's nullability by join type. `expected.json` is the result — a file to read and disagree with,
not a hidden oracle. Eight of the set-operation cases also carry an expected multiset of rows,
transcribed from the examples the spec prints; `probe/check_rows.py` compares those, and rows are the
one part of the corpus that does not depend on a participant's type system at all.

Five cases carry no expectation, and `expected.json` separates the two reasons why. Four are cases
the spec is silent on: three virtual-table rows that contradict the declared schema on nullability,
and one virtual-table literal whose type contradicts it. The fifth is a CTAS whose input schema does
not match its `table_schema`, which the spec does answer — the plan is invalid — so what is worth
measuring there is not a type but whether anyone reports the violation.

## Reading the matrix

`MATRIX.txt` is case by implementation, one truncated answer per cell; `<NAME>.txt` has the full
values. A cell starting with `-` is a refusal, `·` means the case was not run through that
implementation. Where an engine names types its own way, `probe/check_expected.py` maps the
vocabularies onto each other, so `Decimal128(38,10)` and `decimal<38,10>` do not count as a
difference.

The columns cannot all be read the same way, and the first line of each `<NAME>.txt` says how far
that one goes:

| | how far the column goes |
| --- | --- |
| DuckDB | carries no nullability in its logical types, so only types, arity and column order are compared. Comparing nullability would record the boundary of its type system as a divergence |
| DataFusion, DuckDB | have no string type with a length. Neither can represent `varchar<10>` or `fixedchar<5>`, which is why `stringlen_declared` differs there — not a defect |
| Acero, Spark | do carry nullability and are compared on it |
| Gluten | carries no nullability either, and repeats a function's declared type instead of deriving it |
| substrait-validator | also repeats the declared type of a function call. Its answer is independent only for relation schemas, where a plan has no declaration to repeat |

## What is here

| path | what it is |
| --- | --- |
| `derived-schema/` | the corpus: 78 cases, each as protobuf-JSON and as binary protobuf, plus `manifest.json` describing every one |
| `derived-schema-vt/` | the same cases with virtual tables at the leaves, for Gluten, which reads only `virtual_table` and `local_files` out of a `ReadRel` |
| `expected.json` | the expectations, generated by `probe/expected.py` |
| `<NAME>.txt` | the saved answers, one file per implementation |
| `MATRIX.txt` | those columns as one table, built by `probe/matrix.py` |
| `LIE.txt` | the saved run of `probe/lie_matrix.sh` |
| `gen/`, `probe/` | the generators and the probes; `probe/reverify.sh` runs everything, `probe/selfcheck.sh` checks the repository against itself |

The cases are plain `substrait.Plan` protobuf-JSON with no wrapper of any kind, and they declare spec
0.102. Most are the tests of bugs already fixed in substrait-java, rebuilt with the same builders so
that the expected schema is produced mechanically rather than retyped; the rest cover parts of the
spec — the set-operation derivation table, `ReadRel.projection`, aggregation phases, decimal
arithmetic — where the rule is written down and can be checked directly.

`derived-schema/manifest.json` has an entry per case: which generator writes it, the line that
generator prints for it, and its expectation with the wording of where that came from. It is built
by `gen/make_manifest.sh` from the generators themselves, so it cannot drift into saying something
the corpus does not; the only hand-written part is `gen/sources.json`, which records the issue a case
came from. Four cases have one so far — that is what is still thin here. A case is added by adding a
generator to `gen/`; `gen/README.md` says how the corpus is built.

## Running it

You need python3, a JDK (17 for the Spark probe), cargo and go, plus two checkouts:

    export SUBSTRAIT_JAVA_DIR=<a substrait-java checkout>
    export DF_DIR=<a DataFusion checkout, with no local modifications>
    bash probe/setup.sh          # builds .probe-env/ and the generator classpath, once
    bash probe/reverify.sh

`probe/setup.sh` installs the versions pinned in `probe/versions.env` — the ones the saved columns
were measured against, listed in `probe/README.md`, which also covers the validator and Gluten. Both
are built from source and neither is part of `setup.sh`.

`reverify.sh` regenerates the corpus, runs every participant whose environment is up, compares each
column against `expected.json` and prints all sides next to each other. It is fail-closed: any
harness failure gives a non-zero exit and a `FAILED` line, while a single case failing inside an
engine is not a harness failure but the finding. By default the run only reports; it rewrites the
saved corpus and columns only under `UPDATE_CORPUS=1` and `UPDATE_COLUMNS=1`.

Apache 2.0.
