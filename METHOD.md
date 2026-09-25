# Method: where an expectation comes from, and what a match proves

The [README](README.md) is the result: the matrix, the tallies and what would help. This file is
the part a reader checking the result needs — how a case and its expectation are made, what a
matching answer does and does not establish, and what in here has already been corrected.

## Where the expectations come from

`probe/expected.py` encodes case-specific expectations by hand and records their source per case:
decimal formulas reimplemented from `functions_arithmetic_decimal.yaml`, the spec's Output Type
Derivation table, function return declarations, and relation rules such as join nullability and
emit order. It reads neither spec files nor plans. `expected.json` is the result. Ten cases also carry
expected rows: eight set-operation cases whose multisets are transcribed from the spec's examples,
and the two window-bound cases, whose four rows are in the plan. `probe/check_rows.py` compares
those separately from schemas, for three participants, as a multiset of integers one column wide.
That is the whole reach of the row half: on the `emit_*` cases, where the expectation is two columns
in reverse order, a consumer can return the right column count filled with another column's data and
every schema comparison here still passes.

`probe/expected.py` opens by naming every spec file it cites and the release it cites them at —
[v0.102.0](https://github.com/substrait-io/substrait/tree/v0.102.0), which is what these plans
declare and what substrait-java pins through substrait-packaging — so a reader checking a rule knows
which text to open without guessing; the focused probes in [`probe/README.md`](probe/README.md) name
their own where it differs. A schema is written as
type-and-nullability pairs — `[str, i64?]` on these pages, `[["str", false], ["i64", true]]` in
`expected.json` — with `?` on a nullable field and nothing on a required one.

`expected.py` is not a deriver, and that is deliberate. A program that computed a schema from any
plan would be a second implementation of the spec. It would apply one reading of a rule to every
case that touches it, so a wrong reading would produce cases that agree with each other, and a run
of them would come back green. Written case by case, a wrong reading has the cases around it to
disagree with.

That is a difference of degree, not of kind, and two helpers here are where the degree runs out.
`dec_return` computes the five decimal cases and `join_expected` the whole join matrix. A mistake in
either is the same mistake across its group, exactly as it would be in a deriver. What holds for
every case without exception is narrower: no expectation here reads a plan, and none reads an
implementation's answer. Everything beyond that is worth what the reading behind it is worth, which
is why the first thing the README asks for is somebody else's reading of it.

Ten cases carry no expectation, for two different reasons that `expected.json` keeps apart. Seven of
them wait on the spec, under `spec_silent`. Three have virtual-table row types or nullability
different from the declared schema: no sentence settles whether such a row is valid, and the
producers that write rows under a declared schema, Isthmus and substrait-java's Spark module, never
write one, so they stay unscored. One is a projection mask listing its fields as [2, 0]:
`field_references.md` says that "right now, you can only mask things out", and not what a mask
listed out of schema order yields. Of the participants that apply the mask at all, all four put the
columns in the listed order and none keeps the schema's; four more ignore the mask and Acero does
not implement it.

One is a lateral join without a `rel_anchor`, whose right input references nothing. The spec answers
it twice: `logical_relations.md` requires the anchor only when the right input references the
current left row, and `algebra.proto` requires it on every lateral join. The participants split the
same way. substrait-python and DuckDB answer it exactly as they answer `lateral_join_uncorrelated`,
the same join with the anchor set, which is scored; substrait-java refuses it.

Two are the same `UpdateRel` of a two-column table, written for each reading of its output, which
the spec gives only as "number of modified records": one root names a single column, as a count
would have, and the other names the table's two. A root has to name every output column, so a
producer cannot write the plan without choosing. Only substrait-java answers either, and its core
and Isthmus disagree. The core derives the table's columns and refuses the one-name root; Isthmus
converts the two-name plan into a single `ROWCOUNT` column.

The other three, under `spec_says_invalid`, are plans the spec rules out, so what is worth measuring
is whether the violation is reported. One is a CTAS whose input schema does not match its
`table_schema`, which the spec requires it to match. One is a root that names two columns over a
`DdlRel`, a relation `logical_relations.md` gives no output at all. The third is a virtual table with
a null in a column its schema declares required. It needs no rule matching rows to the schema:
`type_system.md` makes null "a special value of a nullable type", so the table outputs a value its
own schema rules out. substrait-java's core, Isthmus and the Spark module refuse it over the null.
The validator refuses every virtual table written with `expressions`, this one included, for a reason
that has nothing to do with the null; the other participants that read a virtual table accept it.

## What the corpus is made of

The cases are plain `substrait.Plan` protobuf-JSON with no wrapper of any kind, and they declare spec
0.102. Most are the tests of bugs already fixed in substrait-java, rebuilt with the same builders
rather than retyped into JSON by hand; the rest cover parts of the spec — the set-operation
derivation table, `ReadRel.projection`, aggregation phases, decimal arithmetic — where the rule is
written down and can be checked directly.

Three things in a case come from three places, and the distinction is what the numbers rest on. The
plan is built by substrait-java's builders, so its shape comes from that library. The types the plan
declares come from there too, which is the whole reason the swap experiment below exists. The
expectation comes from `probe/expected.py`, written from the spec text: it is not read back from the
plan, from a generator, or from any implementation's answer.

Where an upstream test asserts the same thing, that is worth naming rather than leaving to be found.
substrait-java's `JoinRecordTypeTest`, added with substrait-java#1112, tabulates the record type of
each join type, and the rule it encodes is the rule `join_expected` encodes here — written by
somebody else, applied to different inputs, and agreeing. The two aggregate cases have no such
counterpart: `AggregateRelTest`, where they come from, asserts grouping counts and a round trip and
never an output schema.

`derived-schema/manifest.json` has an entry per case: which generator writes it, the line that
generator prints for it, and its expectation with the wording of where that came from. It is built
by `gen/make_manifest.sh` from the generators themselves, so it says what the generators
say rather than what someone remembered about them; the only hand-written part is `gen/sources.json`, which records the issue a case
came from. Five cases have one so far — that is what is still thin here, and thin on purpose: an
entry is added only when the case exercises what the change it names actually changed. A case is added by adding a
generator to `gen/`; `gen/README.md` says how the corpus is built.

## What moving these upstream would take

Three things here bear on the question substrait#1164 asks, and none of them is an argument either
way.

A case is a plain `substrait.Plan`, and its expectation lives beside it in `expected.json` under the
case's own name. The pairing therefore needs no wrapper message: a corpus can be a directory of
plans and one file of expectations. What that costs is that nothing in the format holds the two
together — `derived-schema/manifest.json` and `probe/selfcheck.sh` do it instead, and a plan copied
out of here without its entry loses its expectation silently.

The plans are built with substrait-java's builders. Here that is recorded as calibration, and the
first row of the matrix says what it is worth. In the spec repository the same fact would be a
dependency question: the tests of the spec generated by one of the implementations of the spec.
The cases themselves need nothing but a protobuf library once they are written; the generators need
that checkout.

The plans declare spec 0.102 rather than leaving `Plan.version` unset, so they are not the
version-agnostic fixtures substrait#1164 proposes for a spec-repository corpus.

## The two expand cases

These are the cells that broke the calibration row, and they are worth their own section, because
what they say about the spec and what they say about the two implementations are different things.

The spec's output order for `expand` is the expand fields followed by a column carrying the index of
the duplicate a row came from. That order is unconditional in the table that states it: unlike
Aggregate's own index column, which the same page marks "(if applicable)" and explains below the
table, Expand's carries no condition at all. substrait-java maps the fields and stops, so its answer
is a column short. substrait-python returns the third column and loses the nullability rule that
`ExpandRel.SwitchingField` states outright, which substrait-java gets right. Each implementation
carries one of the relation's two rules. The expectation was written from those sentences before
either was asked, and it is substrait-python — not this repository — that keeps the reading of the
first one from standing alone.

The width of that column is the part the spec leaves open. `physical_relations.md` calls it i32 and
`algebra.proto` calls it int64; [substrait#714](https://github.com/substrait-io/substrait/issues/714)
is open on which is meant. The expectation here follows the documentation table, and the comparison
is exact, so a participant answering `i64` would be recorded as differing on a reading the spec has
not ruled out. None does today. The day one does, the cell arrives needing a reason written by hand,
which is where that reading would be recorded rather than lost.

## What a match establishes

On some cases the consumer repeats the `output_type` the plan declares. The generator and
expectation script encode the same spec rule in separate code. A match then checks the generator's
declaration against that expectation, but does not demonstrate independent function return-type
inference by the consumer.

That is what the declaration swap measures. `probe/lie_matrix.sh` changes declared `output_type`
fields while preserving the rest of each plan and reports whose output schema moves;
`results/LIE.txt` is the saved run over all nine column participants.

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

Five of the nine answer with the declaration. For substrait-java the seventeen that move are the five
decimal cases, `aggregate_sum_i64`, `aggregate_grouping_then_measure`, `mirror_argument_nullability`,
`narrowing_count`, the two null predicates, the two aggregation phases and the three window cases,
plus `ctas_keeps_declared_schema`, which carries no expectation.
The twelve it holds are all `joineq_*`, where the swapped declaration belongs to a join predicate
whose type never reaches the output schema, so it can be copied without the join's output changing.

For Acero, DataFusion, DuckDB and Spark nothing moves. That on its own is not a derivation: reading
a held answer as one the consumer derived is the mistake recorded below. What settles those four is
`decimal_divide`, where the plan declares `dec(21,8)` and they answer `decimal128(16,7)`,
`Decimal128(15,6)`, `DOUBLE` and `decimal(17,8)`. An answer that differs from the declaration cannot
be the declaration repeated.

29 of the 108 cases carry an `output_type` and 28 of those have an expectation. The remaining 70
scored plans declare none, so the swap reaches nothing in them. These counts measure output
sensitivity; they do not count independently derived schemas.

The swap preserves struct arity. Replacing a struct with a scalar would also change the number of
fields in depth, making the plan disagree with `Plan.Root.names`. A refusal over that disagreement
would not establish that the function's return type had been checked.

What this experiment cannot reach: it perturbs `output_type` and nothing else, so it says nothing
about a schema that comes from `ReadRel.base_schema`, which is where the other 67 get theirs. That
field is a legitimate source of input types rather than a declaration to be repeated — a consumer
that returned it unchanged would still fail the emit, projection and join cases — so the missing
half is a mutation that reaches the expression itself, not another swap of a declared output. And
Gluten is not in the experiment at all, for the same reason it is not in `reverify.sh`.

## Whether the call is bound at all

The declaration swap asks whether an answer is the declared output type repeated. It does not ask
whether the participant looked at the function the call names, and the two are independent: a
consumer can resolve the name and still take the type from the plan. `probe/binding_matrix.sh`
rewrites `Plan.extensions[].extensionFunction.name` three ways and leaves everything else alone, so
a refusal cannot be about a shape the plan no longer has. [results/BINDING.txt](results/BINDING.txt)
is the saved run, over the same nine participants.

The rewrites are a control, a key declared under the same URN that the call does not match, a name
whose argument types no implementation declares, and a name no extension file declares at all. The
control exists because a refusal has to be attributable: a participant that objects to the rewrite
itself has not been asked the question, and its other columns cannot be read. It is clean for all
nine.

Nothing refuses the mismatched key. Every participant accepts `sum:i8` over an `i64` argument,
including the three that refuse a key they cannot find, and `sum:i8` returns what `sum:i64` returns,
so the declared output type still agrees and a refusal could only have been about the arguments.
Looking a key up and checking it against the call are different things, and only the first happens
anywhere here.

Four behaviours come out of it. substrait-java, Isthmus and Spark look the compound key up in the
loaded extension. DuckDB, DataFusion and Acero resolve the short name against their own registry
instead, so a name their engine knows binds whatever the declaration says. substrait-python resolves
nothing and prints no diagnostic saying so. The validator does not distinguish the rewrites either,
but it is not measured on this question so much as excused from it: with URN resolution off it warns
that it did not attempt to resolve the YAML, and with resolution on it warns that the declaration's
`name` and `impls` are not yet recognised.
substrait-go is not measured: it parses the name's suffix as a type string and fails there, before
any lookup, so its two counts describe that parse rather than binding.

Read beside the swap, that last group is the sharper result. Of the participants whose answer
follows a swapped output type, substrait-python never resolves the function either, so nothing in
its answer comes from the extension at all.

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
encoded rule matches the spec or that every interpretation of a result is correct. One of those
readings has since been doubled: [`deriver/`](deriver/README.md) computes an output schema from the
plan and the spec text, by rules written separately from `expected.py`, and the 96 cases carrying an
expectation all agree with it. That is the same sentences read twice and agreeing, which is not the
same as a reading by somebody else - still the first thing the README asks for. `differed.json`
names the divergences still under investigation.

## What a case is worth as a test

Everything above measures answers. None of it measures the cases, and the two come apart: a rule no
case reaches agrees with whatever is written about it, and a row of agreement over such a rule reads
exactly like a row of agreement over a rule three cases pin.

`deriver/mutants.py` measures that directly, because the deriver makes it cheap to. Each derivation
rule is replaced by another reading of the same specification sentence - not by a random error - and
the scored cases are derived again. A reading the corpus tells apart is a rule some case pins; a
reading it cannot tell apart is a rule this repository states and tests with nothing.
[`deriver/COVERAGE.txt`](deriver/COVERAGE.txt) is the saved run and
[`deriver/PINNED.txt`](deriver/PINNED.txt) its per-case half.

Its first run could not tell seven readings apart, and four of those were rules no case reached.
Two were not small: the column order of an aggregate that has both grouping expressions and
measures, which no case had at once, and the `MIRROR` nullability rule that every function in the
specification takes by default, whose only calls reaching an output schema read required decimal
columns. The grouping-set index column accounted for two more - both cases that had two grouping
sets cut it with an emit mapping, which `expected.py` had noticed in a comment and no case had
fixed. Three cases close all four, and seven differing cells appeared that the corpus could not
previously have seen, among them that index column coming back at three widths: `i32` from
substrait-java and substrait-python, `i64` from Isthmus and `UInt8` from DataFusion.

Three readings are still pinned by nothing, and the distinction between them matters more than the
count. Two cannot be reached by a valid plan at all: the spec requires a set operation's inputs to
agree on their field types and a write's input to match its `table_schema`, so no legal plan tells
the primary input from any other, or the input's schema from the declared one. Those rules are
unobservable rather than unchecked. The third - whether a projection mask selects fields or states
an order - is a question the spec leaves open, so a case asserting either reading would be asserting
this repository's choice; the deriver declines such a plan instead.

What this does not measure is the battery itself. It holds 37 readings, and a rule nobody wrote a
second reading for is absent from the count rather than reported as covered. What survives that gap
is the per-case half: a reading only one case tells apart stops being checked the day that case is
removed, however many readings the battery grows to.

## Acero input-schema correction

The Acero table provider now materializes each known synthetic table with the schema requested by the Substrait reader. This is the decoded `ReadRel.base_schema`, as described by the [Arrow callback contract](https://arrow.apache.org/docs/python/generated/pyarrow.substrait.run_query.html); it supplies input types, not an expected output schema.

The previous provider ignored that schema and registered `t_str` with plain string and binary fields. It therefore removed the lengths before Acero executed `stringlen_declared`. With the requested schema, Acero preserves `varchar(10)` and `fixed_char(5)` as Arrow extension types and `fixed_binary(4)` as fixed-size binary. The comparison normalizes those names while retaining widths and nullability.

Retaking the whole Acero column — 78 cases then — with the same pinned PyArrow version changed only `stringlen_declared`; it now matches. The former `acero-drops-a-fixed-size-binary` explanation has been removed. A match on this bare read establishes preservation of the supplied input schema, not independent derivation of a function return type. Each column retains its own measurement date when only one participant is rerun.

## Reports and generator sources

[FINDINGS.md](FINDINGS.md) maps the reported findings to their reproducers and related implementation PRs. The explanations in `differed.json` remain judgments about the saved cells: twenty-two of its twenty-seven reasons link an issue or PR. Of the seventeen cells it marks as something other than a divergence, six are limits of a type system, eleven a type the validator never resolved. The separate report map also covers rejected plans and producer diagnostics, which are outside those differing cells.

A refusal is not recorded that way, and mostly should not be: a participant that says it does not implement a relation has already said everything a reason could, and 201 of the cells are that. [refused.json](refused.json) holds the ones that are not. In eleven cells where a participant died rather than refused — ten in the DuckDB extension, one in Acero — what came back is a signal and not a message, and an engine that cannot do something is not in the condition of one that dies trying, whatever its support. Those carry a reason with a predicate and a triage, exactly as a divergence does, and `probe/check_differed.py` requires the file and the columns to name the same cells in both directions.

The general answer for the other 190 would be to compare a refusal against what the engine declares it supports, which needs no reasons written by hand at all. The spec ships no such declaration today: at v0.102.0 `dialects/` holds the schema and its fixtures and not one engine's file.

What came of a divergence is recorded beside it, and per participant rather than per reason, because one reason can cover four of them and no single report covers all four. Each entry says `reported`, `spec-question`, `ours` — the expectation or this harness is wrong — or `open`, and there are thirty-two of them; two of those thirty-two still need investigation and says what is missing. `open` includes an observation that has been examined but still needs a narrower reproducer or an ownership decision. A `reported` entry can link existing work, including a PR without a separate issue; its note states any coverage limits. It does not change the saved measurement or mean that a proposed fix has been rerun. What `probe/check_differed.py` requires is that every divergence carries an entry for every participant whose cells it covers, that only a divergence carries one, and that every link it names appears in FINDINGS.md.

## What the corpus covers

The matrix above is depth. Breadth is the other half substrait#1164 asks for — which relations the
cases reach at all — and `probe/coverage.py` counts that from the plans themselves:

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
