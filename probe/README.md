# Probes

`<name>_one.py` / `<name>_all.sh` are one participant each; `probe/reverify.sh` runs them all.
The shared environment is built by `setup.sh` (see the top-level README). The validator is not part
of it and is installed separately, below.

`selfcheck.sh` is the other direction: it runs no participant at all and checks this repository
against itself — that `expected.json` and `MATRIX.txt` are what their generators produce, that every
saved column is complete and agrees with the expectations, that the numbers in the README match what
`check_expected.py` says, that the corpus is whole, and that no absolute path or untranslated text
has come back. It needs python3 and nothing else, takes seconds, and is what CI runs.

Every script finds the corpus relative to the repository, and its environment through
`SUBSTRAIT_PROBE_ENV` (default `<repo>/.probe-env`). The two external checkouts are named by
`SUBSTRAIT_JAVA_DIR` and `DF_DIR`. `SUBSTRAIT_PYTHON_ENV`, `SUBSTRAIT_VALIDATOR_ENV` and
`PROBE_CACHE` override individual pieces; each defaults to something under the probe environment.
`JAVA17_HOME` is the one to set by hand outside macOS: the Spark probe needs JDK 17 (on 18+ Hadoop
dies in `Subject.getSubject`), and it is found through `/usr/libexec/java_home` only on a Mac.
Without it the Spark column is skipped with a line saying so.

## The participants and their versions

`versions.env` is the single place these are pinned, and `setup.sh` installs exactly them. The two
commits are required by `reverify.sh` itself: a run against a different substrait-java or DataFusion
fails at the preflight, and `SJ_EXPECT=` or `DF_EXPECT=` left empty is how you say you meant it.

| | version | taken by |
| --- | --- | --- |
| substrait-java, Isthmus/Calcite | `81120b91` in the checkout `SUBSTRAIT_JAVA_DIR` points at | `SchemaOf.java`, `CalciteSchemaOf.java` |
| substrait-python | 0.31.0 | `python_one.py` |
| substrait-validator | built from `main` at `2a10470` | `validator_one.py` |
| substrait-go | v9 at `cb2d6e648bc0` | `go/main.go` |
| DataFusion | `f96892a9b` | `datafusion_corpus_probe.rs` |
| DuckDB | 1.5.5, substrait community extension | `duckdb_one.py` |
| Acero | pyarrow 25.0.1 | `acero_one.py` |
| Spark | 3.5.4 | `SparkSchemaOf.java` |
| Gluten/Velox | `f7f5f04` | `SubstraitCorpusProbeTest.cc`, in a cluster |

Spark and Isthmus need a built `:spark:spark-3.5_2.12` and `:isthmus` in that checkout; `cp.sh`
resolves their classpaths from Gradle and caches them under the probe environment.

## What else is in here

`reverify.sh` runs the consumer side: it hands each implementation a plan and records the schema it
derives. The rest of this directory is not on that path, and none of it is run by CI.

**Producers — what an implementation declares.** A consumer's answer is only half the question; the
other half is what a producer writes into `output_type` in the first place. `ProducerIsthmus.java`
and `ProducerSpark.java` print what those two declare when they turn SQL into a plan,
`duckdb_producer.py` does the same for DuckDB and additionally compares the type it reports directly
against the type after a `get_substrait_json` / `from_substrait_json` round trip, and
`datafusion_producer_probe.rs` does it for DataFusion and writes the plans it produced to
`$SUBSTRAIT_PLANS_OUT`. `SchemaOfBin.java` reads those written plans back through substrait-java, so
one implementation's declaration can be handed to another. `go-producer/` is a small module printing
what substrait-go computes as a function's return type from the extension declaration.

**The declared type against the derived one.** `ObserveOf.java` attaches substrait-java's
`TypeObserver` to a conversion and reports, per case, how many types Isthmus saw declared, how many
Calcite derived differently, and how often derivation failed; `ISTHMUS-OBSERVE.txt` is a saved run.
`decl_vs_derived_lie.py` establishes the same thing for the validator by handing it one case twice,
once with a false declaration. `IsthmusRoundTrip.java` goes Substrait to Calcite and back, so what
Isthmus writes into someone else's plan can be compared with what it read.

**One-off diagnostics**, each kept because it is the reproduction behind a filed issue or a decided
question: `DiagnoseSelfJoin.java` and `ViewVsTable.java` with `min_self_join.json` for a self-join
through a temporary view; `agg_old_encoding.py`, which rewrites an aggregate into the retired
`Grouping.grouping_expressions` encoding; `setdata.py`, which collects the `setdata_*` results out of
a saved `reverify.sh` log; and `phase-cases/`, three plans with a README of their own.

**Helpers.** `isthmus_run.sh` and `spark_run.sh` compile and run one Java probe from this directory
against the right classpath; `cp.sh` is where those classpaths come from.

## substrait-validator

`setup.sh` builds this when cargo and protoc are on PATH, and says so when it skips. By hand, the
same thing - the release on PyPI is no use, being on spec 0.57.1 and unable to load these cases:

    SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
    git clone https://github.com/substrait-io/substrait-validator "$SP/substrait-validator"
    git -C "$SP/substrait-validator" checkout "$SUBSTRAIT_VALIDATOR_COMMIT"
    python3 -m venv "$SP/val"
    PATH="$HOME/.cargo/bin:$PATH" PROTOC=$(which protoc) \
      "$SP/val/bin/pip" install "$SP/substrait-validator/py"
    "$SP/val/bin/pip" install -U 'protobuf==7.36.1'

`$SUBSTRAIT_VALIDATOR_COMMIT` comes from `versions.env`, so read that file first (`. probe/versions.env`);
a shallow clone of `main` gets whatever `main` is today, which is not what the saved column was taken
against. The last `pip install` is required too: the generated code needs a 7.x runtime while the
package pins `protobuf<7`. The path to the venv is
overridden with `SUBSTRAIT_VALIDATOR_ENV`.

The validator's boundary is in `validator_one.py`: it does not derive the type a function call
returns, it repeats the declared one, so its answer is independent only for relation schemas.

## Gluten/Velox

Not run by `reverify.sh`: it needs a built Gluten, which takes hours, and the saved `GLUTEN.txt`
column was taken in a cluster. To reproduce it: build Gluten at the commit in `versions.env` with
`dev/builddeps-veloxbe.sh --build_tests=ON` - the `JsonToProtoConverter` harness that reads
protobuf-JSON is only built with the tests - then put `SubstraitCorpusProbeTest.cc` into
`cpp/velox/tests`, register it in the `CMakeLists.txt` there, and point `SUBSTRAIT_CORPUS_DIR` at
the virtual-table variant of the corpus (`derived-schema-vt`, built by `to_virtual_tables.py`).
Gluten reads only `virtual_table` and `local_files` out of a `ReadRel`, so the canonical corpus
with its named tables will not do.
