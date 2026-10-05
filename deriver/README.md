# A second reading of the relation rules

The deriver computes output schemas from plans and the Substrait specification, separately
from `probe/expected.py`. It reads neither expectations, participant answers nor declared
`output_type` fields. [METHOD.md](../METHOD.md) explains the oracle and comparison boundaries.
Agreement is a cross-check between two encodings of the rules, not proof that either is correct.
The [authoring disclosure](#what-was-already-visible) records limits to that independence.

## Running it

```sh
SUBSTRAIT_DIR=<a substrait checkout> python3 -m deriver.run          # the report
SUBSTRAIT_DIR=<a substrait checkout> python3 -m deriver.run --column # what DERIVED.txt holds
python3 deriver/check.py                                            # the saved answers, no checkout
python3 -m deriver.derive derived-schema/<case>.json                 # one plan
```

Extension files are read with `git show` at `v0.102.0`, not from the checkout's working tree.
[spec.pins](spec.pins) pins their bytes; a mismatch stops derivation.
[DERIVED.txt](DERIVED.txt) saves per-case answers, allowing `deriver/check.py` and the repository
self-check to compare them with expectations without a Substrait checkout. Regeneration needs one.

## What came out

The saved schemas agree with every scored expectation. `python3 deriver/check.py` reports the
current tally and any disagreement. This corroborates the oracle's reading, not a claim that
every differing participant has a defect.

Unscored plans may still derive. Reads use `base_schema` without checking virtual-table rows,
and schema derivation does not validate CTAS input compatibility or root names. Updates and
out-of-order projection masks are declined because their output is unsettled.

Earlier declaration-swap and binding-rewrite experiments checked additional boundaries:

- Changing declared `output_type` fields did not move the derived answers.
- Compatible binding controls derived; `sum:i8` over an i64 argument was rejected, although
  the measured participants accepted it.
- Unknown names or signatures were rejected when their result reached the output schema.
  Rewritten join predicates could remain unbound because their types did not reach that output.
- Virtual-table variants derived the same schemas without consulting rows.

The scripts are `probe/make_lied_corpus.py` and `probe/make_unbound_corpus.py`. Those observations
do not make this a plan validator or establish row correctness.

## What the agreement is worth, rule by rule

`deriver/mutants.py` substitutes plausible alternative readings of spec sentences and rederives
scored cases. [COVERAGE.txt](COVERAGE.txt) records which alternatives a case distinguishes;
[PINNED.txt](PINNED.txt) identifies cases that are the sole check for a reading. Alternatives
not authored in the battery are absent from its coverage claim.

The first run exposed missing checks for grouping-before-measure output order, the grouping-set
index and MIRROR nullability. Added cases cover them: `aggregate_grouping_then_measure`,
`aggregate_grouping_set_index` and `mirror_argument_nullability`.

Three alternatives remain undistinguished:

- Set inputs must agree on field types, so valid plans cannot distinguish taking types from
  the primary input from taking them from another input.
- Write input must match `table_schema`, so those sources coincide in valid plans. The CTAS
  case violating that condition is intentionally invalid and unscored.
- The specification does not settle out-of-order projection masks. The case records observed
  behaviour, and the deriver declines it rather than choosing an expectation.

The first two are unobservable in valid plans, not uncovered valid behaviours.

## Where this shows up

`probe/heatmap.py` reads COVERAGE.txt and PINNED.txt for the matrix's rule-coverage summary and
*only check* markers. These describe cases, not participant verdicts. Saved files allow drawing
without a Substrait checkout; `deriver/check.py` checks their consistency with the corpus and
mutation definitions. The negative gate verifies that those checks can fail.

## Where the specification did not decide

The implementation records the following interpretation choices:

- **Index nullability.** Aggregate's grouping-set index and Expand's duplicate index are
  required here because every output row has one; the text specifies no nullability.
- **Index width.** Expand's documentation says i32 and `algebra.proto` says int64, tracked in
  [Substrait issue 714](https://github.com/substrait-io/substrait/issues/714). The documentation
  is followed. Aggregate's text specifies i32; its proto gives no competing width.
- **Aggregate phases.** Calls ending at the intermediate step use the decomposable function's
  intermediate type, combining the phase and return-type descriptions rather than quoting
  one explicit rule connecting them.
- **Projection masks.** The text permits removal, not structural reordering, but does not
  decide whether an out-of-order mask is invalid or selects in schema order. Such masks decline.
- **Right single and right mark joins.** Their "inputs switched" descriptions must be read
  with the signature table's output-order exceptions to determine order and nullability.
- **Updates.** "Number of modified records" defines no type, nullability or column count.
  Both root-name variants decline; no likely count type is guessed.
- **DDL.** "Outputs | 0" and "no output" are represented as `[]`. The deriver does not decide
  whether that means an empty result or no result, and does not check root names. A root naming
  view columns therefore still derives `[]`, though it violates the root-name count rule.
- **Lateral anchors.** Documentation requires an anchor only for an outer reference; the proto
  comment states it unconditionally. The documentation reading is taken, interpreting the
  comment's clause as the anchor's purpose.
- **Integer division.** Return-type expressions truncate towards zero. The spec declares an
  integer result without specifying remainder handling, and no reached derivation uses division.

## What was already visible

The initial rule-writing session opened neither `probe/expected.py` nor `expected.json` until
its rules existed. It did print manifest notes truncated to 70 characters, and 23 notes still
exposed all or part of an expected answer: two aggregate cases, four decimal cases, seven emits,
eight set operations, `phase_final` and `topn_keeps_the_input_schema`. The aggregate entries
were also read in full while examining the manifest layout.

Decimal and set-operation rules compute from their source formula or table; those notes repeat
that source. For emits, aggregates and top-n, the notes disclosed the answer directly, weakening
the independence claim. Reauthoring those rules without the manifest would resolve this limit.

The DDL rule was written later without that exposure, using the deriver, instructions, DDL
plans and spec v0.102.0. Expectations, generators, manifest, columns and pages were not opened.
Comparison ran only after the rule, its test and two alternative readings existed.

## What it does not do

This derives schemas, not rows, column names or general plan validity. It covers the relations
reached by the corpus except `update`; absent are `reference`, `exchange` and the three
extension relations. Supported expressions are field/outer references, literals, casts and
scalar, aggregate and window calls. Unsupported are `if_then`, `switch`, list predicates,
subqueries, lambdas, nested constructors, and enum/type arguments. Type variations are ignored;
variadic functions bind only in their consistent form.

Unsupported or unsettled derivations decline with a reason and are counted separately from
wrong answers. A successful schema derivation is not a validity verdict.
