# What producers write

The other two corpora measure consumers on plans this repository wrote. Whether a divergence there
reaches anyone depends on whether a producer writes a plan of that shape. This directory asks the
producers: the queries in [queries.tsv](queries.tsv) go to DuckDB, Isthmus, Spark 3.5, Spark 4.0 and
DataFusion, at the versions [probe/versions.env](../probe/versions.env) pins, and the plans they
write are kept in [plans/](plans), one directory per producer.

Each plan is then checked against the specification at v0.102.0, the release the other corpora
use. The columns are [results/producers/](../results/producers).

## What is checked

**Declared call types.** Every scalar, aggregate and window call declares an `output_type`, and
algebra.proto says what it has to be: "the return type of the function, exactly as derived using
the declaration in the extension". [deriver/calls.py](../deriver/calls.py) derives that type from
the extension files and the plan, without reading any declared type, and
[check.py](check.py) puts the declaration beside it. A call is counted as

- `differ` when the declared type is not the derived one, nullability included;
- `missing` when it declares no `output_type` at all;
- `unbound` when the plan's name, URN and argument types bind to no implementation of the extension;
- `declined` when the deriver has no rule for something the call needs; not scored.

**Root names.** RelRoot.names: "Field names in depth-first order. The number of names must match
the number of named fields in the output type." The output type is the deriver's; a plan whose
schema it declines is marked so and not scored.

**Observed, not scored.** A refusal is the producer's answer and is shown as its first line.
Fields the release no longer defines are listed after the summary, since a plan may declare an
older release; which relation a producer chose for a SQL construct is left to the consumer and row
checks still to come.

## One reading, not two

In `derived-schema/` an expectation is read twice, by `probe/expected.py` and by the deriver, and a
disagreement between the two readings is itself a finding. Here the deriver is the only reading. A
disagreement with a producer is triaged by hand against the sentence it rests on, but a wrong
reading the producer happens to share passes unseen. The deriver's call rules were written by a
session that had not seen any producer's declarations, and `python3 -m deriver.calls --lied` shows
that swapping every declared type changes none of its answers.

## Running

```sh
SUBSTRAIT_JAVA_DIR=<checkout> DF_DIR=<checkout> bash producers/run.sh         # report
UPDATE_PLANS=1 SUBSTRAIT_JAVA_DIR=<checkout> DF_DIR=<checkout> bash producers/run.sh
SUBSTRAIT_DIR=<substrait checkout> python3 producers/check.py --derive      # producers/DERIVED.txt
python3 producers/check.py --write                                          # the columns
```

`run.sh` needs the probe environment (`probe/setup.sh`), the relations one
(`probe/relations/setup.sh`) for protobuf, `protoc`, JDK 17 for Spark and cargo for DataFusion, and
stops when a checkout is not at its pin. It replaces a committed plan only when the plan moved
beyond anchor numbering, because DataFusion numbers function anchors in hash-map order; the bytes
kept are still the producer's own. The deriver reads the extension files from a Substrait
checkout, so what it derives for these plans is saved in [DERIVED.txt](DERIVED.txt), and
`probe/selfcheck.sh` checks the columns against the plans and the saved derivations with python3
alone.

A change of a producer's pin in `probe/versions.env` means retaking its plans in the same change.
