# A second reading of the relation rules

`probe/expected.py` writes what each case should answer, case by case, from the specification text.
This program computes the same thing from the plan, from the same specification, by rules written
separately. Nothing here reads `expected.py`, `expected.json` or any implementation's answer, and
nothing here reads a declared `output_type` out of a plan.

That is the whole design. [METHOD.md](../METHOD.md) explains why `expected.py` is deliberately not
a deriver: one program applying one reading of a rule to every case that touches it produces cases
that agree with each other, so a wrong reading comes back green. Written case by case, a wrong
reading has its neighbours to disagree with. A deriver has the opposite shape and the opposite
failure, which is exactly why it is worth having a second one beside the first — two codings of the
same sentences, and a disagreement between them is either a mistake in one of them or a sentence
that does not decide the question.

It is worth having only as long as it stays independent. Written with the expectations open, it
would agree by construction and nobody afterwards could tell that from agreement on the merits.

## Running it

```sh
SUBSTRAIT_DIR=<a substrait checkout> python3 -m deriver.run          # the report
SUBSTRAIT_DIR=<a substrait checkout> python3 -m deriver.run --column # what DERIVED.txt holds
python3 deriver/check.py                                            # the saved answers, no checkout
python3 -m deriver.derive derived-schema/<case>.json                 # one plan
```

The extension files are read out of that checkout at `v0.102.0` — the release the plans declare —
with `git show`, not out of its working tree, so a checkout sitting on a branch cannot quietly
change what a rule says. Their bytes are pinned in [spec.pins](spec.pins), and a file serving
anything else stops the run instead of being derived from.

`DERIVED.txt` is the saved answer for each of the 101 cases. It exists so that the comparison can run
without a checkout: `deriver/check.py` compares it against `expected.json` and is what
`probe/selfcheck.sh` calls. Regenerating it needs the checkout; comparing it does not.

## What came out

All 96 cases that carry an expectation agree with it. None differs. The five without one — the CTAS
whose input does not match its `table_schema`, and the four virtual tables whose row literals differ
from their declared schema — get an answer here anyway, because the rules below take a read's
schema from `base_schema` and never look at a virtual table's rows. That is a position on where a
read's schema comes from, not an answer to the question those cases hold open, which is whether a
row may disagree with the schema above it at all.

On 62 of those 96 cases at least one participant is recorded in `differed.json` as diverging — not
a limit of its type system and not an unresolved type, but an answer the spec rule says should have
been something else. The deriver gives the expectation's schema on all 62. That says nothing new
about the participants; what it says is that the expectation each of them is recorded against was
read twice rather than once, which is the part a reader had no way to check before.

Two experiments the corpus already runs against its nine participants were run against this program:

*The declaration swap.* `probe/make_lied_corpus.py` replaces every declared `output_type` with a
wrong one. It reaches 29 of the 101 plans, five of the nine participants follow it, and not one of
the 101 answers here moves. That is what "never reads `output_type`" means as a fact rather than as
an intention, and it is the check to run first on any change to this code.

*The binding rewrite.* `probe/make_unbound_corpus.py` rewrites the name a call is declared under.
On the control corpus, where the rewritten name is another function with the same signature and
return, all 17 plans still derive — so a refusal below is about binding and not about the rewrite.
On `mismatch`, where the compound key exists but names argument types the call does not pass, all
six refuse: `sum:i8` over an `i64` argument binds nowhere here. No participant in the matrix refuses
that. On `signature` and `unknown` — a key no impl declares, and a name no file declares — the 15
plans whose call reaches the output schema refuse, and the other 24 derive: those are the `joineq_*`
and `physjoin_*` cases, where the rewritten call is a join predicate. This program derives schemas
and does not validate plans, so an expression whose type never reaches the output is never bound at
all. It is not a validator, and that is the clearest place to see it.

`derived-schema-virtual-tables/` carries the same 101 cases with their data embedded as virtual
table literals instead of read from a named table. Every answer is identical to the one from the
plain corpus, which is what "the rows are never consulted" means as a fact rather than as an
intention.

## What the agreement is worth, rule by rule

Agreement says the two readings match. It does not say the corpus would have caught them if they had
not: a rule no case reaches agrees with anything. `deriver/mutants.py` measures that directly. Each
rule is replaced by another reading of the same sentence — not by a random error — and the scored
cases are rederived. [COVERAGE.txt](COVERAGE.txt) is the saved run.

Of 37 alternative readings the corpus tells 34 apart. The first run of this probe, over a narrower battery, told only 25 apart, and the
four it could not were rules no case reached:

| the rule | why nothing reached it | what closed it |
| --- | --- | --- |
| Aggregate emits grouping expressions, then measures | no case had both at once — four had only measures, three only groupings | `aggregate_grouping_then_measure` |
| an aggregate with more than one grouping set gets an `i32` index | both multi-set cases cut column 2 with `emit: [0, 1]` | `aggregate_grouping_set_index` |
| the same, read as unconditional | the same emit | the same case |
| `MIRROR` makes the return nullable if any argument is | every `MIRROR` call whose type reaches the output read required decimal columns | `mirror_argument_nullability` |

The three still not told apart are not gaps, and each for its own reason:

- **A set operation takes its field types from the primary input.** The spec requires every input to
  agree on types, so no valid plan can distinguish the primary from any other input.
- **Write outputs its input's schema rather than `table_schema`.** The spec requires the input to
  match `table_schema`, so the two readings coincide in every valid plan. The one case where they
  differ, `ctas_keeps_declared_schema`, is invalid on purpose and carries no expectation for exactly
  that reason.
- **A projection mask selects, keeping schema order, rather than listing an order.** Here the
  specification itself does not decide, so a case asserting a reading would be asserting this
  repository's choice. `read_projection_mask_reordered` measures what the participants do instead,
  with no expectation, and the deriver declines such a mask; the question is one of the open ones
  below.

Two of those are the corpus reporting a property of the format rather than a hole in itself: a rule
that no legal plan can exercise is unobservable, not unchecked. That distinction is the reason this
probe reports readings rather than a coverage percentage.

## Where this shows up

`probe/heatmap.py` reads [PINNED.txt](PINNED.txt) and [COVERAGE.txt](COVERAGE.txt) when it draws.
The picture gains one line under its tallies — how many cases pin a rule nothing else pins, and how
many rules nothing pins — and the page gains an *only check* column between the case names and the
participants, marking those cases, and a section saying which three readings are pinned by nothing
and why. Neither is a verdict about a participant, so neither carries a state colour, and the column
is drawn unlike a participant's so that it does not read as a tenth one: a case can be load-bearing
and still be one most implementations refuse.

Both files are saved artifacts, because regenerating them needs a Substrait checkout and drawing
does not. `deriver/check.py` keeps them honest against the corpus and against `mutants.py`, and
`probe/selfcheck-negative.sh` breaks that check in two ways.

## Where the specification did not decide

These are the places where writing a rule meant choosing, and the choice is in the code at the
point where it was made rather than only here.

The **`i32` column** Aggregate appends for a second grouping set and Expand appends always: neither
page gives its nullability. It is written required, on the grounds that the value is an index every
output row has. Nothing contradicts it and nothing confirms it.

The width of the two columns is a different matter, and they differ from each other in it. For
Expand it is a known open question: `physical_relations.md` calls the column i32, and the comment
above `message ExpandRel` in `algebra.proto` calls it int64, which
[substrait#714](https://github.com/substrait-io/substrait/issues/714) is open on; the documentation
table is followed here, as in `expected.py`. For Aggregate there is no such question —
`logical_relations.md` says i32 twice and `algebra.proto` says nothing about the column at all — so
an implementation returning another width is simply differing from the one text there is.

The **phase of an aggregate call**. The spec names an intermediate output type for a decomposable
function and lists the phases as "what portion of the operation is required". It nowhere says in one
sentence that a call ending at the intermediate step outputs that type. Reading the two together is
the only way the phases have a type at all, so that reading is applied; it is a reading, not a
quotation.

A **projection mask listing its fields out of order**. `field_references.md` says, among its
discussion points, "Right now, you can only mask things out", and `algebra.proto` that a mask "does
not fundamentally alter the structure of data beyond the elimination of unnecessary elements". That
rules out a mask reordering columns, but not whether a mask listed out of schema order selects in
schema order or is invalid. `read_projection_mask_reordered` puts the question to the participants
without asserting an answer, and the deriver declines such a mask rather than pick one.

**Right single and right mark joins**. The Join Types table describes each as its left counterpart
"with the right and left inputs switched", while the direct output order in the signature table
names semi, anti and mark as the exceptions and puts everything else in input order. The two have
to be read together to get either a column order or a nullability; separately, each is short of an
answer.

**What an update outputs.** The page gives `UpdateRel` one output and describes it only as "Output
is number of modified records". There is no Direct Output Order row, which every other relation
with an output has, and neither the page nor `algebra.proto` gives that number a type, a
nullability or a column count. The deriver declines the relation rather than answer `i64`, which
would be the likeliest guess and still a guess.

**When a lateral join must carry a `rel_anchor`.** The page makes it conditional: "When the right
input references the current left row, `LateralJoinRel` must set `RelCommon.rel_anchor`". The
comment on the message in `algebra.proto` makes it unconditional: "LateralJoinRel must set
RelCommon.rel_anchor so the right input can reference fields of the current left row." The schema
comes out the same either way, so this decides only whether a lateral join with no anchor and no
outer reference is valid. The page's reading is taken, on the grounds that the proto's clause states
the anchor's purpose rather than a second requirement.

**Integer division** in a return type expression. The spec declares `divide(integer, integer) =>
integer` and does not say how a remainder is handled. No derivation this corpus reaches divides, so
the choice is unexercised; truncation toward zero is what is implemented.

## What was already visible

Independence is a claim about what was read, so here is what had been read before the rules were
written. `probe/expected.py` and `expected.json` were not opened until every rule below existed —
that is the part that matters, and it held. But `derived-schema/manifest.json` carries each case's
expectation beside its note, and the case list was printed from it with the note truncated to 70
characters. In 23 of those notes the truncated text still named the answer or part of it: the two
aggregate cases (whose entries were read in full while working out the manifest's shape), four of
the five decimal cases, the seven `emit_*` cases, the eight `setop_*` cases, `phase_final` and
`topn_keeps_the_input_schema`.

For the set operations and the decimals that is softer than it sounds: what the note names is the
same table and the same YAML formula the rule reads anyway, and the rule computes rather than
enumerates — `decimal_multiply_overflow`, whose note was cut before the answer, comes out of the
same evaluator as the four whose notes were not. For `emit_*`, the aggregates and `topn` the note
named the answer outright, and independence on those six is weaker than on the other 75. Somebody
writing these rules again without the manifest in front of them is what would settle it.

## What it does not do

Schemas only: no rows, no column names, no validation beyond what deriving a schema happens to
require. Of the relations `algebra.proto` defines it implements the sixteen the corpus reaches and
`lateral_join`, which no case reaches and only `deriver/test_derive.py` checks; it declines `update`
for the reason given below; `reference`, `ddl`, `exchange` and the three extension relations are
absent. Of the expressions it reads field references — rooted in the input, or an outer reference
by `rel_reference` to the row a lateral join binds — literals, casts and scalar, aggregate and
window function calls; not `if_then`, `switch`, `singular_or_list`, `multi_or_list`, subqueries,
lambdas, nested constructors, or enum and type arguments. Type variations are ignored. A variadic
function binds only in its consistent form.

Every one of those is a stop rather than a guess: the case is reported as not derived, with the
reason, and counted apart from a case answered wrongly. An answer that might be a guess would be
indistinguishable from a derivation in the comparison, which is the one thing this program exists
to keep apart.
