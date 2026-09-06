# Substrait conformance cases: declared type against derived type

[![selfcheck](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml/badge.svg)](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml)

A plan declares types and a consumer derives them again — or reuses what the plan declared. When
the two disagree, nothing in the format notices. This repository holds 78 plans built to make such
disagreements visible, an expected schema for 73 of them, and probes that put the corpus through ten
implementations. The expectations encode spec rules and examples separately from the generators and
consumers; they are not read from plans or consumer outputs. The spec repo already ships function
test cases, which check what a scalar function returns; these cases compare schemas across
relations.

It is a lab rather than a proposal: the corpus and the harness, kept reproducible. A case is added
by adding a generator to `gen/`; a column is retaken by running `probe/reverify.sh` with
`UPDATE_COLUMNS=1`, which is also what keeps the numbers on this page true, since
`probe/selfcheck.sh` compares them with the files. If a number here is wrong, that is a bug in this
repository and worth an issue.

Take `decimal_divide`, which divides `dec(10,2)` by `dec(5,1)`. The formula in
`functions_arithmetic_decimal.yaml` gives `dec(21,8)`, which six consumer paths report:

    substrait-java, substrait-go, substrait-python, validator, Isthmus, Gluten   dec(21,8)
    Spark        dec(17,8)
    DataFusion   dec(15,6)
    DuckDB       fp64
    Acero        dec(16,7)

(Types are shown in the corpus's own notation; `results/<NAME>.txt` keeps each implementation's spelling.)

## What the corpus says

The columns saved here were taken 2026-09-06 against the versions in `probe/versions.env`, which
each column's own first line names again. They answer the 73 cases that carry an expectation:

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

These are nine consumer paths. The Java core, Isthmus and Spark paths share substrait-java;
Isthmus adds Calcite conversion and Spark adds its Catalyst conversion. Gluten has a separate
cluster run over the virtual-table variant and is outside this normalized comparison.
*Unsupported* means the probe produced no comparable schema: it includes rejections, errors and
crashes. It does not establish that the plan lies outside a declared capability. Read *differed*
against *matched + differed* when comparing returned schemas; the unsupported count records the
rest of the cases. A returned schema may also have diagnostics, which are reported separately.

*Differed* means the answer disagrees with this repository's reading of the spec — some of those
have been filed against the implementations and some have not. Not every *differed* cell is a
defect either. `differed.json` gives all 101 of them a reason and marks 17 as something other than
a divergence: six are limits of a type system, eleven a type the validator never resolved. Each
reason has a property that `probe/check_differed.py` tests against the saved column or case inputs.
These checks verify the stated output properties; explanations of causes and type-system limits
still require review. Unknown or inactive checks are rejected. `reverify.sh` reproduces
the whole table, and `probe/check_expected.py results/<NAME>.txt <format>` reproduces one row and
names the cases behind it.

**What a match establishes.** On some cases the consumer repeats the `output_type` the plan
declares. The generator and expectation script encode the same spec rule in separate code. A match
then checks the generator's declaration against that expectation, but does not demonstrate
independent function return-type inference by the consumer.

`probe/lie_matrix.sh` changes declared `output_type` fields while preserving the rest of each plan
and reports whose output schema moves. `results/LIE.txt` is a saved run.

| | answers that move | of them with an expectation |
| --- | ---: | ---: |
| substrait-java | 11 | 10 |
| substrait-python | 10 | 10 |
| substrait-validator | 10 | 10 |
| DuckDB | 0 | 0 |

For substrait-java the eleven are the five decimal cases, `narrowing_count`, the two null
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

## What is not settled

This repository is three days old, and the claims on this page have been corrected seven times in
that span — the size of the circular set, a "fail-closed" summary that a validator environment with
nothing installed walked straight through, the date on the table above, the DataFusion commit the
columns were taken against, a reason in `expected.json` that pointed at its neighbour and, once the
file was sorted, at the wrong one, the count of differing cells that are a limit of a type system
rather than a divergence, and reading a held answer in the swap table as one the consumer derived —
the twelve that held are the `joineq_*` cases, where the swapped declaration is a join predicate
whose type never reaches the output schema. Each is a commit with the measurement that found it.

The self-checks verify relationships between committed artifacts. They do not establish that every
encoded rule matches the spec or that every interpretation of a result is correct.

What is open, as against corrected:

- The rules encoded in `probe/expected.py` need independent review against the spec.
- Five of the 78 cases link to the issue they came from. The other 73 record their generator and
  expected rule without an originating issue link.
- `differed.json` says why each cell differs but not which divergences were reported upstream: six
  of its twenty-one reasons name an issue and the rest name none. Reasons here get rewritten: ten
  were corrected after the answers behind them were read one by one, and a second reader then found
  seven more that held for most of their cells and described the rest wrongly. That is why a reason
  there has to carry a test.
- Rows are compared for three participants and eight cases; schemas for nine and 73.
- The Gluten column is taken in a cluster and reproducible only in one.
- The full sweep has run on Linux, in a container on clean Ubuntu 24.04 with every cache empty,
  cloning this repository anonymously and following this page and nothing else: nine columns, every
  tally matching the ones above. It has not run on hardware that is not this machine's, and nobody
  outside this project has run it. CI runs only the self-check, which is the repository read against
  itself and says nothing about any implementation.
- Getting there took five attempts, and each failure was a requirement recorded by the name of a
  tool rather than by what it had to be: go, where the version was never stated and the check for it
  could not fail; protoc, where the imports it needs ship in a separate package on Debian; and the
  JDK, where the probe that wants a 17 finds one by itself only on macOS. Two more were defects in
  the checks rather than in the harness, and are why `probe/selfcheck-negative.sh` exists.

## Where the expectations come from

`probe/expected.py` encodes case-specific expectations by hand and records their source per case:
decimal formulas reimplemented from `functions_arithmetic_decimal.yaml`, the spec's Output Type
Derivation table, function return declarations, and relation rules such as join nullability and
emit order. It reads neither spec files nor plans. `expected.json` is the result. Eight set-operation
cases also carry expected multisets of rows transcribed from the spec's examples;
`probe/check_rows.py` compares those separately from schemas.

Five cases carry no expectation, and `expected.json` separates the two reasons why. Four have
virtual-table row types or nullability different from the declared schema. They remain unscored
pending clarification of exact type equality versus compatibility between a row and its schema;
the `spec_silent` category records this unresolved question. The fifth is a CTAS whose input schema
does not match its `table_schema`. The spec requires them to match, so this plan is invalid and
what is worth measuring is whether the violation is reported.

## Reading the matrix

`results/MATRIX.txt` is case by implementation, one truncated answer per cell; `results/<NAME>.txt` has the full
values. A cell starting with `-` is a refusal, `·` means the case was not run through that
implementation. Where an engine names types its own way, `probe/check_expected.py` maps the
vocabularies onto each other, so `Decimal128(38,10)` and `decimal<38,10>` do not count as a
difference.

The columns cannot all be read the same way, and the first line of each `results/<NAME>.txt` says how far
that one goes:

| | how far the column goes |
| --- | --- |
| DuckDB | carries no nullability in its logical types, so only types, arity and column order are compared. Comparing nullability would record the boundary of its type system as a divergence |
| DataFusion, DuckDB | have no string type with a length. Neither can represent `varchar<10>` or `fixedchar<5>`, which is why `stringlen_declared` differs there — not a defect |
| Acero, Spark | do carry nullability and are compared on it |
| Gluten | carries no nullability either, and repeats a function's declared type instead of deriving it |
| substrait-validator | the pinned revision retains declared function return types; schema output must be read alongside diagnostics. The mutation checks final output schemas, not every expression's type |

## What is here

| path | what it is |
| --- | --- |
| `derived-schema/` | the corpus: 78 cases, each as protobuf-JSON and as binary protobuf, plus `manifest.json` describing every one |
| `derived-schema-virtual-tables/` | the same cases with virtual tables at the leaves, for Gluten, which reads only `virtual_table` and `local_files` out of a `ReadRel` |
| `expected.json` | the expectations, generated by `probe/expected.py` |
| `differed.json` | why each differing answer differs: a limit of a type system, a type left unresolved, or a divergence |
| `results/<NAME>.txt` | the saved answers, one file per implementation |
| `results/MATRIX.txt` | those columns as one table, built by `probe/matrix.py` |
| `results/LIE.txt` | the saved run of `probe/lie_matrix.sh` |
| `results/ISTHMUS-OBSERVE.txt`, `results/GLUTEN-ROWS.txt` | two saved measurements outside the matrix: what Isthmus's type observer sees, and Gluten over the corpus variant that gives empty tables a synthetic row |
| `probe/phase-cases/` | three plans showing that DataFusion does not read `AggregateFunction.phase`, with a README of their own |
| `gen/`, `probe/` | the generators and the probes; `probe/reverify.sh` runs everything, `probe/selfcheck.sh` checks the repository against itself, and `probe/README.md` covers what else is in there — the producer probes and the one-off diagnostics |

The cases are plain `substrait.Plan` protobuf-JSON with no wrapper of any kind, and they declare spec
0.102. Most are the tests of bugs already fixed in substrait-java, rebuilt with the same builders so
that the expected schema is produced mechanically rather than retyped; the rest cover parts of the
spec — the set-operation derivation table, `ReadRel.projection`, aggregation phases, decimal
arithmetic — where the rule is written down and can be checked directly.

`derived-schema/manifest.json` has an entry per case: which generator writes it, the line that
generator prints for it, and its expectation with the wording of where that came from. It is built
by `gen/make_manifest.sh` from the generators themselves, so it cannot drift into saying something
the corpus does not; the only hand-written part is `gen/sources.json`, which records the issue a case
came from. Five cases have one so far — that is what is still thin here, and thin on purpose: an
entry is added only when the case exercises what the change it names actually changed. A case is added by adding a
generator to `gen/`; `gen/README.md` says how the corpus is built.

## Running it

You need python3, go 1.23 or newer, a JDK, and cargo with protoc — protoc and the well-known type
definitions it imports, which some distributions package apart from it (`protobuf-compiler` and
`libprotobuf-dev` on Debian and Ubuntu). Two of those are more particular than they look.
The Spark probe wants JDK 17 specifically, and finds it by itself only on macOS; anywhere else set
`JAVA17_HOME` to one, or that probe is skipped and the run then fails, since a skipped participant
needs `ALLOW_SKIPPED=1` to be counted as intended. And the DataFusion probe builds that checkout with
the Rust toolchain it pins in its own `rust-toolchain.toml`, which rustup will fetch for you and an
unmanaged cargo will not. Then two checkouts, at the commits `probe/versions.env` names:

    export JAVA17_HOME=/usr/lib/jvm/java-17-openjdk-arm64   # or wherever a 17 is, outside macOS

    export SUBSTRAIT_JAVA_DIR=<a substrait-java checkout>
    export DF_DIR=<a DataFusion checkout, with no local modifications>
    bash probe/setup.sh          # builds .probe-env/, once
    bash probe/reverify.sh

`probe/setup.sh` installs the versions pinned in `probe/versions.env` — the ones the saved columns
were measured against — and builds the validator from source when cargo and protoc are there, saying
so when it skips. It does not build Gluten: that column is taken in a cluster, and `probe/README.md`
says what it takes.

`reverify.sh` requires both checkouts to be at the pinned commits and refuses to run otherwise;
`SJ_EXPECT=` or `DF_EXPECT=` left empty says you meant something else. The pin records what was
measured rather than what is necessary: the same nine columns came out of substrait-java at
`81120b91`, twelve commits earlier, with every number unchanged. A participant whose
environment is missing is skipped with a line saying so, and the run then fails unless
`ALLOW_SKIPPED=1` says a partial run was intended.

`reverify.sh` regenerates the corpus, runs every participant, compares each column against
`expected.json` and prints all sides next to each other. A single case failing inside an engine is
not a harness failure; that is the finding. What does fail the run, each with a `FAILED` line and a
non-zero exit: a checkout at the wrong commit, a missing environment, a generator that will not
build, a corpus or manifest or expectation file that no longer matches its source, fewer answers
coming back than there are cases, a participant that answered nothing at all, a column the
normalization could not make whole, and a participant skipped without `ALLOW_SKIPPED=1`.

That list is written out rather than summarised as "fail-closed", because the summary was false once
and read as true: a validator environment with nothing installed produced 78 crashes and a clean run,
the guard having compared the refusals against the number of cases while the check only ever counts
the 73 that carry an expectation.

By default the run only reports: it rebuilds the corpus, the manifest and `expected.json` into
temporary files and tells you what differs. `UPDATE_CORPUS=1` lets it replace those three,
`UPDATE_COLUMNS=1` the saved columns and `results/MATRIX.txt`, and nothing else writes to the repository.

Apache 2.0.
