# Substrait conformance cases: declared type against derived type

[![selfcheck](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml/badge.svg)](https://github.com/alexandrefimov/substrait-conformance-cases/actions/workflows/selfcheck.yml)

A plan declares types and a consumer derives them again; when the two disagree, nothing in the format
notices. This repository holds 78 plans built to make such disagreements visible, an expected schema
for 73 of them computed from the spec rather than from any implementation, and the harness that puts
the corpus through ten implementations. The spec repo already ships function test cases, which check
what a scalar function returns; these are whole plans, and what they check is schema derivation
across relations.

It is a lab rather than a proposal: the corpus and the harness, kept reproducible. A case is added
by adding a generator to `gen/`; a column is retaken by running `probe/reverify.sh` with
`UPDATE_COLUMNS=1`, which is also what keeps the numbers on this page true, since
`probe/selfcheck.sh` compares them with the files. If a number here is wrong, that is a bug in this
repository and worth an issue.

Take `decimal_divide`, which divides `dec(10,2)` by `dec(5,1)`. The formula in
`functions_arithmetic_decimal.yaml` gives `dec(21,8)`, and so do six of the ten:

    substrait-java, substrait-go, substrait-python, validator, Isthmus, Gluten   dec(21,8)
    Spark        dec(17,8)
    DataFusion   dec(15,6)
    DuckDB       fp64
    Acero        dec(16,7)

(Types are shown in the corpus's own notation; `results/<NAME>.txt` keeps each implementation's spelling.)

## What the corpus says

The columns saved here, taken 2026-09-06 against the versions in `probe/versions.env` and named in
each column's own first line, answer the 73
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
a divergence in derivation. Read *differed* against *matched + differed* rather than against 73: a
participant that refuses most of the corpus is reporting its coverage, and the few answers it does
give are a thin base for anything else.

*Differed* means the answer disagrees with this repository's reading of the spec — some of those
have been filed against the implementations and some have not. Not every *differed* cell is a
defect either. `differed.json` gives all 101 of them a reason and marks 17 as something other than
a divergence: six are limits of a type system, eleven a type the validator never resolved. Each
reason states something about the answer that `probe/check_differed.py` tests against the saved
column, so a reason that describes a participant wrongly fails the check. `reverify.sh` reproduces
the whole table, and `probe/check_expected.py results/<NAME>.txt <format>` reproduces one row and
names the cases behind it.

**One caveat.** The zero in the first row is worth less than it looks. On some cases the answer is
not derived at all: the implementation repeats the `output_type` the plan declares, and this
repository's own generator wrote that declaration from the same rule the expectation uses. There the
check compares the generator with itself.

Which cases those are is measured rather than guessed. `probe/lie_matrix.sh` swaps every declared
`output_type` for a false one, changes nothing else, and reports whose answer moves with it; an
answer that moves is an answer that depends on the declaration. `results/LIE.txt` is a saved run.

| | answers that move | of them with an expectation | expectations not copied from `output_type` |
| --- | ---: | ---: | ---: |
| substrait-java | 11 | 10 | 63 |
| substrait-python | 10 | 10 | 63 |
| substrait-validator | 10 | 10 | 63 |
| DuckDB | 0 | 0 | 73 |

For substrait-java the eleven are the five decimal cases, `narrowing_count`, the two null
predicates and the two aggregation phases, plus `ctas_keeps_declared_schema`, which carries no
expectation.

How far that last column reaches is worth being exact about. Only 23 of the 78 cases carry an
`output_type` at all, and the swap touches those and nothing else; 22 of the 23 have an expectation.
So the experiment examined 22 of the 73 expectations and found ten copied and twelve held. The other
51 carry no `output_type` for a consumer to copy, which is why they are counted in that column —
not because this experiment cleared them.

The swap has to preserve arity, and finding that out cost a wrong answer. Swapping a struct
`output_type` for a scalar changed the number of fields in depth; the plan then disagreed with
`Plan.Root.names`, the participant refused over the count of names, and the measurement recorded
that as having noticed the type. `phase_intermediate` read as caught rather than copied, and the
number above was 63 by a different route.

Two limits on reading a held answer as *derived*. The swap perturbs `output_type` and nothing else, so an
answer that holds is proven not to be copied **from that field** — it is not thereby proven to be
derived, because a relation's schema also comes from `ReadRel.base_schema`, which the swap leaves
alone, and which is what those 51 declare — an implementation that simply returned the declared
schema would pass all 51 without deriving anything, and this experiment would not notice. Swapping
`base_schema` for a neighbouring type is the missing half; it would split those 51 into deriving and
repeating. And only these four participants were measured; for DataFusion, substrait-go, Acero,
Spark, Isthmus and Gluten the copy discount is simply not known.

## What is not settled

This repository is three days old, and the claims on this page have been corrected five times in
that span — the size of the circular set, a "fail-closed" summary that a validator environment with
nothing installed walked straight through, the date on the table above, the DataFusion commit the
columns were taken against, and a reason in `expected.json` that pointed at its neighbour and, once
the file was sorted, at the wrong one. Each is a commit with the measurement that found it. None was
an error in the harness's logic; all five were statements *about* the measurement, which no run
contradicts, and each is now checked by one file being read against another.

What is open, as against corrected:

- The expectations are computed by `probe/expected.py`, in this repository. Nobody outside it has
  reviewed them. The candour above is not a second opinion.
- Five of the 78 cases record the issue they came from. For the other 73 the generator that builds a
  case is the only record of what it asserts.
- `differed.json` says why each cell differs but not which divergences were reported upstream: six
  of its twenty-one reasons name an issue and the rest name none.
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
| substrait-validator | also repeats the declared type of a function call. Its answer is independent only for relation schemas, where a plan has no declaration to repeat |

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
