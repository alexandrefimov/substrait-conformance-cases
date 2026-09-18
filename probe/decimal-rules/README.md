# Where the decimal return formula comes from

Review of [substrait-io/substrait#1213](https://github.com/substrait-io/substrait/pull/1213) asked
what engine the `functions_arithmetic_decimal` return expressions model, and whether more than one
engine agrees with them. This directory answers that with the YAML set against five rule sets over
every operand type pair, and with five engines run on the cases of the pull request.

## The family

The expressions arrived with the first version of the file,
[d602e95](https://github.com/substrait-io/substrait/commit/d602e95732030b69e5985466cbca9e41453526a1),
and the only change since is
[substrait-io/substrait#151](https://github.com/substrait-io/substrait/pull/151), which names the
reference it was fixed against: Gandiva's
[`DecimalTypeUtil`](https://github.com/apache/arrow/blob/apache-arrow-7.0.0/java/gandiva/src/main/java/org/apache/arrow/gandiva/evaluator/DecimalTypeUtil.java#L38-L90).
Hive's rules cite SQL Server in a comment above each one, and Spark's
[`adjustPrecisionScale`](https://github.com/apache/spark/blob/v4.0.1/sql/api/src/main/scala/org/apache/spark/sql/types/DecimalType.scala#L166-L174)
says it is based on Hive's. The shape is the same in all of them: compute a precision and scale as
if unbounded, then, if the precision exceeds 38, cap it there and take the surplus out of the scale,
keeping at least six fractional digits where the operands asked for that many.

The 38 is not a taste. A decimal literal in `algebra.proto` is sixteen bytes, and 38 digits is what
fits in 128 bits; Gandiva's adjustment ends in `new Decimal(precision, scale, 128)` for the same
reason.

## What agrees with what

`rules.py` transcribes those five, each from its own source rather than through a shared helper —
otherwise `0 / 606841 differ` would be true by construction — and compares them against the YAML
over every operand type pair
`type_classes.md` allows. That page bounds a decimal by `P <= 38` and `0 <= S <= P` and leaves `P`
unbounded below, which is read here as `P >= 1`: 779 types, so 606841 pairs.

    python3 probe/decimal-rules/rules.py --op divide --examples 3

`add`, `subtract`, `multiply` and `modulus` return the same type as Gandiva, Hive 4.0.1 and Spark
4.0.1 under its default `spark.sql.decimalOperations.allowPrecisionLoss` on all 606841 pairs.

`divide` matches none of the three. Its scale is theirs, `max(6, S1 + P2 + 1)`, but its precision
writes `P2` where
[Gandiva](https://github.com/apache/arrow/blob/apache-arrow-7.0.0/java/gandiva/src/main/java/org/apache/arrow/gandiva/evaluator/DecimalTypeUtil.java#L62-L69),
[Hive](https://github.com/apache/hive/blob/rel/release-4.0.1/ql/src/java/org/apache/hadoop/hive/ql/udf/generic/GenericUDFOPDivide.java#L117-L126)
and
[Spark](https://github.com/apache/spark/blob/v4.0.1/sql/catalyst/src/main/scala/org/apache/spark/sql/catalyst/expressions/arithmetic.scala#L779-L785)
write `S2`, and the two answers differ on 402584 pairs.
[substrait-io/substrait#1216](https://github.com/substrait-io/substrait/issues/1216) carries that
one, and the same divergence reaches a consumer in
[substrait-java#1292](https://github.com/substrait-io/substrait-java/issues/1292).

Whether the three agree with each other is the separate question, and the one that says what a
disagreement means. They do, on every function including `divide`: 0 of 606841. So the `divide` row
above is the formula standing apart from its own reference, not an operation the engines each define
their own way.

For `add`, `subtract` and `multiply` there is a second split, and that one is only above precision
38: arrow-rs, which DataFusion evaluates through, caps the precision and keeps the scale
([`decimal_op`](https://github.com/apache/arrow-rs/blob/59.3.0/arrow-arith/src/numeric.rs#L860-L870)),
where the rest borrow from the scale. It is the same choice Spark exposes as
`allowPrecisionLoss`, and it is why `dec<38,10> + dec<38,10>` comes back as `dec<38,9>` from the
runs below and as `dec<38,10>` from the DataFusion query in the review thread. `rules.py` counts
how many disagreements fall below precision 38, and there it is none: none of the 234832 for `add`
and `subtract`, none of the 485478 for `multiply`.

`divide` against arrow-rs is not that. Its scale there comes from postgres and MySQL as `S1 + 4`,
a different rule and not a different clamp, and 23827 of its 592191 disagreements are below
precision 38.

## What the engines answered

`engines.py` runs the cases of that pull request in Docker and prints the type the formula derives
beside the one the engine derived:

    python3 probe/decimal-rules/engines.py spark|hive|trino|mysql|clickhouse
    python3 probe/decimal-rules/engines.py spark --stop     # remove what is left running

The review of the pull request reported, from a separate investigation, that Trino, MySQL and
ClickHouse differ. They do, and the rows say how. For `dec(10,2)` against `dec(5,1)`, and for the
`dec<38,10>` pair the review asked about:

| | add | multiply | divide | `dec<38,10>` + `dec<38,10>` |
| --- | --- | --- | --- | --- |
| the YAML | `dec(11,2)` | `dec(16,3)` | `dec(21,8)` | `dec(38,9)` |
| Spark 4.0.1, Hive 4.0.1 | `dec(11,2)` | `dec(16,3)` | `dec(17,8)` | `dec(38,9)` |
| Trino 483 | `dec(11,2)` | `dec(15,3)` | `dec(17,8)` | `dec(38,10)` |
| MySQL 8.4.11 | `dec(11,2)` | `dec(15,3)` | `dec(15,6)` | `dec(39,10)` |
| ClickHouse 26.8.6.5 | `Decimal(18,2)` | `Decimal(18,3)` | `Decimal(18,2)` | `Decimal(38,10)` |

Three things separate those rows, and only one of them is arithmetic. MySQL has no bound at 38 —
it answers `dec(65,20)` where the formula gives `dec(38,6)` — and ClickHouse's precision is a
storage width, so `Decimal(18,·)` is Decimal64 holding a result that needs 11 digits. Those two
differ about the type and not about the rule. Trino's decimal is the same as Substrait's, bounded
at 38, and it differs twice: `p1 + p2` rather than `p1 + p2 + 1` for multiply, and keeping the
scale rather than borrowing from it above 38.

That last one is the split the review found between Spark and DataFusion, and it is not a Spark
setting on one side and an engine on the other: Spark and Hive borrow, Trino and DataFusion keep.
The formula takes the Hive side. `divide` is the only row where it is alone, and Trino answers
`dec(17,8)` there like the rest. The `divide_rule/wide_divisor` case separates the two forms
further: `dec(10,2) / dec(9,0)` is `dec(29,12)` by the formula and `dec(20,12)` in Spark, Hive and
Trino alike, nine digits of precision apart with neither operand near the cap.

The expected column is `rules.substrait`, so a case where the formula and the engine part is marked
`differ` in the output instead of being left to the reader, and a run that lost a case fails rather
than print a short table. The images are pinned in `probe/versions.env` beside the other
participants.

[RUN.txt](RUN.txt) is that output, taken 2026-09-17. Spark and Hive answer the formula's type for
every case except the two that go through `divide`.

The `overflow` option has engines behind both of its values. Spark under its default
`spark.sql.ansi.enabled` raises, and so does Trino; Spark with it off and Hive return NULL; MySQL
raises out of range where a result will not fit a column, and otherwise has room for it. ClickHouse
does neither: `dec<38,0>` plus `dec<38,10>` comes back as
`1896011491092736564947192744.6130393088`, a wrapped value with no diagnostic, which is what SILENT
describes.

The run adds a group the pull request has no cases for. The formula discards fractional digits
whenever the unbounded precision passes 38, and neither the YAML nor `type_classes.md` says how;
the cases there lose only zeros, so they pin the type and not the rounding. Spark 4.0.1 and Hive
4.0.1 and Trino 483 all round the tie away from zero, on both signs: `1.2345685 * 1` at `dec<38,10>`
reduces to `dec<38,6>` and comes back `1.234569` in all three, where rounding to even would keep
`1.234568`. The tie is chosen so that the two differ — the digit before it is even, and Trino has to
be asked through multiply, because its `add` never reduces at all.
`functions_arithmetic_decimal.yaml` carries no `rounding` option, where `functions_arithmetic.yaml`
gives one to the fp32 and fp64 overloads. The reduction cannot arise for `modulus`: its unbounded
precision never exceeds 38, against 77 for the other three and 115 for `divide`.

## What the overflow option's three values are worth

`overflow: [ SILENT, SATURATE, ERROR ]` is declared in five extension files, and the specification
defines none of the three: the only prose that names them, on the options page, is an example
spelling the option `OVERFLOW_BEHAVIOR` and its first value `OVERFLOW`, which has read that way
since [substrait-io/substrait#49](https://github.com/substrait-io/substrait/pull/49) in October
2021. `engines.py --overflow` asks the five engines what they do at a type boundary, on integers,
where clamping is far more plausible than it is on decimals:

    python3 probe/decimal-rules/engines.py spark --overflow

Nothing clamps. Spark 4.0.1 under its default ANSI and Trino 483 raise; Hive 4.0.1 and Spark with
ANSI off wrap, `127 + 1` giving `-128`; MySQL 8.4.11 and ClickHouse 26.8.6.5 widen the result type
instead, MySQL to `bigint` and ClickHouse from `Int32` to `Int64`, and each raises or wraps only
where it has nothing wider — MySQL raises at `bigint`, ClickHouse wraps `UInt64` round to `0`. Only
MySQL and ClickHouse have an unsigned type, so the `u64` row is theirs alone.

So two of the three values have engines behind them and `SATURATE` has none, here or among the
decimal cases above.

## Whether the consumers derive this or repeat it

The corpus already carries the same pair: `decimal_add_overflow` is `dec<38,10>` plus `dec<38,10>`,
and [results](../../results) give `dec(38,9)` from substrait-go, substrait-java, substrait-python,
substrait-validator, Isthmus, Gluten and Spark, `Decimal128(38,10)` from DataFusion, and an error
from Acero and DuckDB. That is not seven implementations of the borrow rule.
[results/LIE.txt](../../results/LIE.txt) swaps each plan's declared output type for a false one, and
on this case substrait-java, substrait-python and substrait-validator all `follows`: their answer
goes with the declaration. So their `dec(38,9)` is the plan's own type read back, not a derivation,
and the rest are untested here. Nothing in this repository shows an implementation deriving the
rule above 38 for itself.

## Who writes these functions

A consumer that derives a type other than the formula's only matters if some producer sends it a
plan calling these functions. `producers.py` reads the plans four producers wrote for the same four
statements over one table, `a + b`, `c + d`, `c * d` and `a / b`, where `a` is `dec(10,2)`, `b` is
`dec(5,1)`, and `c` and `d` are both `dec(38,10)`. Each producer probe keeps its plans when
`SUBSTRAIT_PLANS_OUT` names a directory; the commands are in the docstring of `producers.py`, and
then

    python3 probe/decimal-rules/producers.py <dir>/spark <dir>/isthmus <dir>/duckdb <dir>/datafusion

Spark (converted by substrait-java's Spark module), Isthmus and DuckDB all write `add:dec_dec` and
`multiply:dec_dec` from `extension:io.substrait:functions_arithmetic_decimal`. None of them reads the
type it declares from that file. On `a / b` all three part from the formula: Spark and Isthmus
declare `dec(17,8)` where the formula gives `dec(21,8)`, the precision difference
[substrait-io/substrait#1216](https://github.com/substrait-io/substrait/issues/1216) is about, and
DuckDB turns the division into `divide:fp64_fp64` from `functions_arithmetic`.

On `a + b` all three declare `dec(11,2)`, as the formula does. Above precision 38 they split along
the same line as the engines. On `c + d` Spark declares `dec(38,9)`, the formula's type, and Isthmus
and DuckDB declare `dec(38,10)`. On `c * d` Spark declares `dec(38,6)` and the other two
`dec(38,20)`. So the three producers that name these functions already declare both answers for
them.

DataFusion's plans for these statements name no extension file. Each function is a bare `add`,
`multiply` or `divide` whose URN reference is 4294967295, and the plan carries neither
`extension_urns` nor the older `extension_uris`. It declares `dec(38,10)` and `dec(38,20)` like
DuckDB, and `dec(15,6)` on `a / b`.

[PRODUCERS.txt](PRODUCERS.txt) is that output, taken 2026-09-18 at the pinned versions.

## What this does not cover

Gandiva and arrow-rs are read rather than executed. DataFusion publishes no CLI image, and a cargo
build from a clone for a handful of types was not worth the half hour; its answer quoted above is
the one in the review thread, not one taken here. Trino, MySQL and ClickHouse were not looked at in either form. Decimal32, Decimal64 and
Decimal256 are outside it — the comparison is Decimal128, which is the only width Substrait has.
`SATURATE` is declared by the function and exercised by nothing here.
