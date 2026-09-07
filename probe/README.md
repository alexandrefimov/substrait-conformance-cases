# Probes

`<name>_one.py` / `<name>_all.sh` are one participant each; `probe/reverify.sh` runs them all.
The shared environment, including the validator, is built by `setup.sh` (see the top-level README).
The validator build prerequisites and manual alternative are described below.

`selfcheck-negative.sh` checks that `selfcheck.sh` can fail: it breaks each invariant in a copy of
the repository and requires the check to notice that one, not merely to go red. A check nobody
checks is a comment the interpreter happens to run, and three guards here were written, committed
and could never fire.

`replay_python.sh` is the one probe CI can run: it builds the substrait-python environment from the
pinned version through `setup.sh` (`SETUP_ONLY=substrait-python`, which builds one piece instead of
all of them), puts the corpus through it and requires the result to be identical to
`results/PYTHON.txt`. One column out of nine, retaken on a machine that is not the author's.

`selfcheck.sh` is the other direction: it runs no participant at all and checks this repository
against itself — that `expected.json` and `results/MATRIX.txt` are what their generators produce, that every
saved column is complete and agrees with the expectations, that the numbers in the README match what
`check_expected.py` says, that the corpus is whole, and that no absolute path or untranslated text
has come back. `check_differed.py`, which it calls, is the one part that reads judgements rather
than generated files: every differing answer has a reason in `differed.json`, and every reason
carries a test of an output property. These checks do not prove the stated cause of a difference.
Unknown or inactive checks are rejected. The self-check needs python3 and nothing else, takes
seconds, and is what CI runs.

Every script finds the corpus relative to the repository, and its environment through
`SUBSTRAIT_PROBE_ENV` (default `<repo>/.probe-env`). The two external checkouts are named by
`SUBSTRAIT_JAVA_DIR` and `DF_DIR`. `SUBSTRAIT_PYTHON_ENV`, `SUBSTRAIT_VALIDATOR_ENV` and
`PROBE_CACHE` override individual pieces; each defaults to something under the probe environment.
`JAVA17_HOME` is the one to set by hand outside macOS: the Spark probe needs JDK 17 (on 18+ Hadoop
dies in `Subject.getSubject`), and it is found through `/usr/libexec/java_home` only on a Mac.
Without it the Spark column is skipped with a line saying so.

## What a run needs, and what fails it

python3, go 1.23 or newer, a JDK, and cargo with protoc — protoc and the well-known type definitions
it imports, which some distributions package apart from it (`protobuf-compiler` and
`libprotobuf-dev` on Debian and Ubuntu). Two of those are more particular than they look. The Spark
probe wants JDK 17 specifically and finds it by itself only on macOS; anywhere else set
`JAVA17_HOME`, or that probe is skipped and the run then fails, since a skipped participant needs
`ALLOW_SKIPPED=1` to count as intended. And the DataFusion probe builds that checkout with the Rust
toolchain it pins in its own `rust-toolchain.toml`, which rustup will fetch for you and an unmanaged
cargo will not.

A column is written through `normalize.py`, which puts every participant's answer into one line per
case and refuses a column it cannot make whole, so the comparison never runs on a half-read file.
`results/MATRIX.txt` is case by implementation with one truncated answer per cell, and
`results/<NAME>.txt` has the full values: a cell starting with `-` is a refusal and `·` means the
case was not run through that implementation. A returned schema can still carry diagnostics — for
the validator, `bash probe/validator_all.sh` prints them, and `results/VALIDATOR.txt` keeps the
schema when there is one.

`reverify.sh` regenerates the corpus, runs every participant, compares each column against
`expected.json` and prints all sides next to each other. By default it only reports: the corpus, the
manifest and `expected.json` are rebuilt into temporary files and it tells you what differs, and a
participant whose environment is missing is skipped with a line saying so. `UPDATE_COLUMNS=1`
replaces the saved columns, `results/MATRIX.txt` and `docs/`; `UPDATE_CORPUS=1` replaces the corpus,
the manifest and `expected.json`; nothing else in the repository is written by a run.

`reverify.sh` requires both checkouts to be at the commits `versions.env` names and refuses to run
otherwise; `SJ_EXPECT=` or `DF_EXPECT=` left empty says the mismatch is deliberate. The pin records
what was measured rather than what is necessary: the same nine columns came out of substrait-java at
`81120b91`, twelve commits earlier, with every number unchanged.

A single case failing inside an engine is not a harness failure; that is the finding. What does fail
the run, each with a `FAILED` line and a non-zero exit: a checkout at the wrong commit, a missing
environment, a generator that will not build, a corpus or manifest or expectation file that no
longer matches its source, fewer answers coming back than there are cases, a participant that
answered nothing at all, a column the normalization could not make whole, and a participant skipped
without `ALLOW_SKIPPED=1`.

That list is written out rather than summarised as "fail-closed", because the summary was false once
and read as true: a validator environment with nothing installed produced 78 crashes and a clean
run, the guard having compared the refusals against the number of cases while the check only ever
counts the 73 that carry an expectation.

## The participants and their versions

`versions.env` is the single place these are pinned, and `setup.sh` installs exactly them. The two
commits are required by `reverify.sh` itself: a run against a different substrait-java or DataFusion
fails at the preflight, and `SJ_EXPECT=` or `DF_EXPECT=` left empty is how you say you meant it.

| | version | taken by |
| --- | --- | --- |
| substrait-java, Isthmus/Calcite | `fff6390` in the checkout `SUBSTRAIT_JAVA_DIR` points at | `SchemaOf.java`, `CalciteSchemaOf.java` |
| substrait-python | 0.31.0 | `python_one.py` |
| substrait-validator | built from `main` at `2a10470` | `validator_one.py` |
| substrait-go | v9 at `cb2d6e648bc0` | `go/main.go` |
| DataFusion | `cc29ea12a` | `datafusion_corpus_probe.rs` |
| DuckDB | 1.5.5, substrait community extension | `duckdb_one.py` |
| Acero | pyarrow 25.0.1 | `acero_one.py` |
| Spark | 3.5.4 | `SparkSchemaOf.java` |
| Gluten/Velox | `f7f5f04` | `SubstraitCorpusProbeTest.cc`, in a cluster |

Spark and Isthmus need a built `:spark:spark-3.5_2.12` and `:isthmus` in that checkout; `cp.sh`
resolves their classpaths from Gradle and caches them under the probe environment.

## What else is in here

`reverify.sh` runs the consumer side: it hands each implementation a plan and records the schema it
derives. The rest of this directory is not on that path, and none of it is run by CI.

### Focused schema diagnostics

These commands run from the corpus root after setting up the relevant participant.
They report additional observations separately from the saved matrix.

**Python join and grouping nullability.** `python_nullability.py` checks six logical join kinds
against all four combinations of input nullability, plus five grouping-set layouts. Its
expectations follow the [join and aggregate rules in spec v0.99.0](https://github.com/substrait-io/substrait/blob/v0.99.0/site/docs/relations/logical_relations.md).
The plans use named reads and field references, with no measures or declared function return types.

```sh
SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
SETUP_ONLY=substrait-python bash probe/setup.sh
"$SP/pysub/bin/python" probe/python_nullability.py
"$SP/pysub/bin/python" probe/python_nullability.py --area grouping --write-plans "$SP/nullability-plans"
```

The output is JSON Lines: installed package versions, expected and actual nullabilities for each
case, then the number of cases and mismatches. `--area join` selects only the join cases. Differences
are reported without a failing exit status; an inference error or mutation of the input does fail
the run. `--write-plans` exports protobuf-JSON plans with named tables and no data. A consumer that
resolves those names through its own catalog needs each table registered with the schema from its
`ReadRel.base_schema`. These 29 checks are separate from the 78 plans in the main corpus. They reproduce
[Python #267](https://github.com/substrait-io/substrait-python/issues/267) and
[#268](https://github.com/substrait-io/substrait-python/issues/268).

**Spark before root naming.** `SparkSchemaOf --relation` converts the first root's input relation
directly, so its schema can be compared with the normal full-plan conversion. This helps isolate
read projection from the later application of `RelRoot.names`, as in
[Java/Spark #1290](https://github.com/substrait-io/substrait-java/issues/1290).

```sh
export SUBSTRAIT_JAVA_DIR=/path/to/substrait-java
export JAVA17_HOME=/path/to/jdk-17
export JAVA_HOME="$JAVA17_HOME"
bash probe/spark_run.sh SparkSchemaOf derived-schema/read_projection_mask.json
bash probe/spark_run.sh SparkSchemaOf --relation derived-schema/read_projection_mask.json
```

Set both paths to existing installations. The Spark probe only discovers JDK 17 automatically on
macOS; set `JAVA17_HOME` explicitly on other systems.

**DuckDB bound types.** `duckdb_one.py --describe` prints the DuckDB and extension versions, then
uses `DESCRIBE` to report column names and types without executing the plan. This separates decimal
return typing from execution overflow, as in
[DuckDB #276](https://github.com/substrait-io/duckdb-substrait-extension/issues/276).

```sh
SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
"$SP/venv/bin/python" probe/duckdb_one.py --load-only --describe derived-schema/decimal_multiply_overflow.json
```

`--load-only` uses an already installed Substrait extension and skips installation. Omit that flag
to use the probe's normal installation path. The diagnostic prints `DUCKDB BOUND`; normal execution
prints `DUCKDB ACCEPTED` or `DUCKDB REJECTED`. Column nullability is not compared for DuckDB.

### Other probes

**The matrix drawn.** `heatmap.py` turns the saved columns into `docs/matrix.svg` and
`docs/matrix-dark.svg`, which the README shows, and `docs/index.html`, which the site serves with
the expectation and the answer under the cursor. It does not decide anything of its own: the
parsers and the expectations come out of `check_expected.py`, `reverify.sh` redraws all three under
`UPDATE_COLUMNS=1`, and `selfcheck.sh` compares the files with the generator and the drawn cells
with the check, participant by participant.

**Producers — what an implementation declares.** A consumer's answer is only half the question; the
other half is what a producer writes into `output_type` in the first place. `ProducerIsthmus.java`
and `ProducerSpark.java` print what those two declare when they turn SQL into a plan,
`duckdb_producer.py` does the same for DuckDB and additionally compares the type it reports directly
against the type after a `get_substrait_json` / `from_substrait_json` round trip, and
`datafusion_producer_probe.rs` does it for DataFusion and writes the plans it produced to
`$SUBSTRAIT_PLANS_OUT`. `SchemaOfBin.java` reads those written plans back through substrait-java, so
one implementation's declaration can be handed to another. `go-producer/` prints
what substrait-go computes as a function's return type from the extension declaration. It requires
Go 1.24 or newer, separately from the consumer probe's Go 1.23 minimum:

    (cd probe/go-producer && GOTOOLCHAIN=local go run .)

After setup and a successful `reverify.sh`, `bash probe/lie_matrix.sh` reruns the output-schema
mutation experiment on Java, Python, validator and DuckDB. `reverify.sh` compiles the `SchemaOf`
helper that the mutation script uses.

**The declared type against the derived one.** `ObserveOf.java` attaches substrait-java's
`TypeObserver` to a conversion and reports, per case, how many types Isthmus saw declared, how many
Calcite derived differently, and how often derivation failed. `observe_all.sh` takes that over the
whole corpus into `results/ISTHMUS-OBSERVE.txt` - one JVM per case, because Isthmus throws on the
cases it cannot convert and a single JVM would stop at the first of them; a case it refuses is
absent from the file rather than recorded as zero.
`decl_vs_derived_lie.py` establishes the same thing for the validator by handing it one case twice,
once with a false declaration. `results/GLUTEN-ROWS.txt` is the other measurement kept outside the
matrix: Gluten over the corpus variant that gives an empty table a synthetic row, which is how a
schema it would otherwise refuse to produce becomes visible. `IsthmusRoundTrip.java` goes Substrait to Calcite and back, so what
Isthmus writes into someone else's plan can be compared with what it read.

**One-off diagnostics**, each kept because it is the reproduction behind a filed issue or a decided
question: `DiagnoseSelfJoin.java` and `ViewVsTable.java` with `min_self_join.json` for a self-join
through a temporary view; `agg_old_encoding.py`, which rewrites an aggregate into the retired
`Grouping.grouping_expressions` encoding; `setdata.py`, which collects the `setdata_*` results out of
a saved `reverify.sh` log; and `phase-cases/`, three plans with a README of their own.

**Helpers.** `isthmus_run.sh` and `spark_run.sh` compile and run one Java probe from this directory
against the right classpath; `cp.sh` is where those classpaths come from.

## Running this on another machine

The nine-consumer sweep has also run in a clean Ubuntu 24.04 container with empty caches. A run on
another machine is still useful for finding dependencies on the original workstation. The
self-check in CI checks saved artifacts; it does not repeat the consumer measurements.

For such a run to measure the harness rather than someone's paths, these have to start empty:

| | why it matters cold |
| --- | --- |
| the Gradle cache and both build directories | `:core`, `:isthmus` and `:spark:spark-3.5_2.12` are built through `cp.sh`, and a warm tree hides whether the task graph asks for what the classpath names |
| the cargo target directory | the DataFusion example takes tens of minutes cold and seconds warm, and the toolchain that checkout pins has to be fetched |
| the pip cache | `setup.sh` installs duckdb, pyarrow, substrait-python and the validator, and their wheels are large |
| `JAVA17_HOME` | the Spark probe needs JDK 17 and finds it through `/usr/libexec/java_home` only on macOS; elsewhere it is set by hand or the probe is skipped |
| the Go module cache | `probe_go9` is built from a pinned commit |

The two checkouts have to be at the commits `versions.env` names, which `reverify.sh` requires
anyway. Everything else `setup.sh` builds.

## substrait-validator

`setup.sh` builds this when cargo and protoc are on PATH and `google/protobuf/any.proto` is where
protoc can find it - the build compiles .proto files that import it, and Debian and Ubuntu ship that
file in `libprotobuf-dev`, apart from the compiler. Without it the failure lands deep inside maturin
and names neither package, so `setup.sh` checks first and says so when it skips. By hand, the
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

The default validator probe reports that YAML resolution was not attempted. At the pinned validator
revision, `FunctionBinding::new` also leaves function matching and return-type checking unimplemented
and retains the supplied return type. Its schema output must be read alongside the diagnostics;
returning a schema is not an assertion that the plan passed validation.

## Gluten/Velox

Not run by `reverify.sh`: it needs a built Gluten, which takes hours, and the saved
`results/GLUTEN.txt` column is taken in a cluster, by hand, whenever the other nine are retaken.
`gluten_column.py` turns the probe's output into the column - it drops everything from
` Retriable:` onwards, which is where a Velox exception stops being the message and becomes a
forty-frame stack - so the one step that used to happen in someone's terminal is now in the
repository. `results/MATRIX.txt` reads each column's date out of its own header, so a run that
leaves Gluten behind says so rather than presenting one date for all ten. To reproduce it: build Gluten at the commit in `versions.env` with
`dev/builddeps-veloxbe.sh --build_tests=ON` - the `JsonToProtoConverter` harness that reads
protobuf-JSON is only built with the tests - then put `SubstraitCorpusProbeTest.cc` into
`cpp/velox/tests`, register it in the `CMakeLists.txt` there, and point `SUBSTRAIT_CORPUS_DIR` at
the virtual-table variant of the corpus (`derived-schema-virtual-tables`, built by `to_virtual_tables.py`).
Gluten reads only `virtual_table` and `local_files` out of a `ReadRel`, so the canonical corpus
with its named tables will not do.
