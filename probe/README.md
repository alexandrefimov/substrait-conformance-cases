# Probes

`<name>_one.py` / `<name>_all.sh` are one participant each; `probe/reverify.sh` runs them all.
The shared environment, including the validator, is built by `setup.sh` (see the top-level README).
The validator build prerequisites and manual alternative are described below.

`selfcheck-negative.sh` checks that `selfcheck.sh` can fail: it breaks each invariant in a copy of
the repository and requires the check to notice that one, not merely to go red. A check nobody
checks is a comment the interpreter happens to run, and three guards here were written, committed
and could never fire.

`replay_column.sh` is the probe CI can run. It builds one participant's environment from nothing
through `setup.sh` (`SETUP_ONLY=<key>`, which builds one piece instead of all of them), puts the
corpus through it and requires the answers to be identical to the saved column:

    bash probe/replay_column.sh PYTHON|GO|DUCKDB|ACERO|VALIDATOR|JAVA|ISTHMUS|SPARK|DATAFUSION

All nine columns, retaken on a machine that is not the author's. Four are a pip install or a go
get; the validator and DataFusion are a clone and a cargo build, wanting protoc and its
well-known types from `protobuf-compiler` and `libprotobuf-dev`; the three that come out of
substrait-java are a clone at the pinned commit and a Gradle build, wanting the JDK
`versions.env` names, and Spark additionally wants that JDK named in `JAVA17_HOME`, which it
finds by itself only on a Mac. Each clones what it needs, so none of them requires a checkout
to exist first, and DataFusion's is fetched without blobs — a quarter of a gigabyte of history
for one commit is time spent on nothing. Gluten is outside this: it runs in a cluster.

`LATEST=1` is the same run against today's release rather than the pinned one, through
`versions-latest.env`. There a difference is the finding rather than the failure — the participant
moved since the column was taken — and only a broken harness fails the run. That is what
`.github/workflows/drift.yml` does weekly; `selfcheck.yml` does the pinned direction on every push.

A drift run that finds something prepares a block for
[`results/DRIFT.txt`](../results/DRIFT.txt): the day, the participant, the revision it was actually
built from, the revision of this repository and the fingerprint of its inputs, and the cases that
moved. A quiet week leaves nothing there. The jobs run in parallel in separate checkouts, so each
leaves its block in its artifact and one later job collects them into a proposed file and patch.
Those outputs are artifacts for a normal reviewed PR; the workflow does not write to a Git branch.
`selfcheck.sh` checks the shape of the saved log.

`OUT=<dir>` keeps the run: the normalized column, the runner's raw output, the report of what moved,
and a record naming the versions actually installed, the revision this repository was at, and one
fingerprint over the corpus, `expected.json` and `normalize.py`. Without that record a difference
between two runs cannot be attributed — a moved answer, a regenerated corpus and an edited
expectation all look the same in a column.

Two things the pinned run checks besides the answers. The installed version has to be the one
`versions.env` asked for, because a comparison against another version of the participant says
nothing about either. And DuckDB's substrait support is a community extension, where `INSTALL` takes
no version and whatever that repository serves is what arrives: the version is read back out of
`duckdb_extensions()` and compared with `DUCKDB_SUBSTRAIT_EXTENSION`. That pin cannot be honoured,
only noticed — but a run that got a different extension is not a reproduction, whatever the answers
turn out to be.

`selfcheck.sh` is the other direction: it runs no participant at all and checks this repository
against itself — that `expected.json`, `results/MATRIX.txt` and `results/DIFFS.md` are what their
generators produce, that the numbers the pages state in prose are the numbers the files hold, that every
saved column is complete and agrees with the expectations, that the numbers in the README match what
`check_expected.py` says, that the corpus is whole, and that no absolute path or untranslated text
has come back. `check_differed.py`, which it calls, is the one part that reads judgements rather
than generated files: every differing answer has a reason in `differed.json`, every reason
carries a test of an output property, and every divergence carries a record of what came of
it — per participant, since one reason can cover four of them. These checks do not prove the
stated cause of a difference.
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
counts the ones that carry an expectation.

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

A column is compared only as far as the participant's type system reaches. The head of each
`results/<NAME>.txt` repeats its own limit:

| | how far the column goes |
| --- | --- |
| DuckDB | carries no nullability in its logical types, so only types, arity and column order are compared. Comparing nullability would record the boundary of its type system as a divergence |
| DataFusion, DuckDB | have no string type with a length. Neither can represent `varchar<10>` or `fixedchar<5>`, which is why `stringlen_declared` differs there — not a defect |
| Acero, Spark | do carry nullability and are compared on it |
| Gluten | carries no nullability either, and repeats a function's declared type instead of deriving it |
| substrait-validator | the pinned revision retains declared function return types; schema output must be read alongside diagnostics. The mutation checks final output schemas, not every expression's type |

These pins describe the saved measurements, not a promise to use every participant's newest release. Update a pin together with a reproduced column and its provenance. Package versions and Substrait spec versions are also distinct: a binding can depend on older packaged definitions even when the binding itself is the latest release.

The Spark runner selects `:spark:spark-3.5_2.12`; its Spark version comes from that module's Gradle build. `SPARK_35` records the expected version but does not override the dependency. `SPARK_34` and `SPARK_40` record the other library variants and do not add corpus runs for them. The saved Spark column and automated replay therefore cover Spark 3.5 only. Focused diagnostics use the same default classpath selection.

`LATEST=1` selects package releases or repository heads through `versions-latest.env`. For Spark it follows the current substrait-java checkout's 3.5 variant; it does not independently select the newest Apache Spark patch release. The separate runtime profiles below cover explicitly selected Spark 3.5 and 4.x releases.

### Separate Spark runtime profiles

[`spark-runtimes.json`](spark-runtimes.json) selects Spark 3.5.9, 4.0.4, 4.1.3 and 4.2.0. The 3.5 profile compiles the Scala 2.12 consumer; all 4.x profiles compile the Scala 2.13 consumer from the library's 4.0 module against the requested runtime. This measures compatibility; it does not claim that upstream supports a dedicated 4.1 or 4.2 module. The versions are explicit and require a reviewed configuration update when new Spark releases arrive.

```sh
export JAVA_HOME=/path/to/jdk-17
python3 probe/spark_runtime.py --list
python3 probe/spark_runtime.py 3.5.9 --out run/spark-3.5.9
python3 probe/spark_runtime.py 4.2.0 --out run/spark-4.2.0
python3 probe/spark_runtime.py 4.2.0 --latest --out run/spark-4.2.0-main
```

Each run uses a fresh environment, consumer build directory and resolved classpath. By default it clones the Java revision in `versions.env`; `--java-dir /path/to/checkout` reuses a clean checkout at that exact revision. `--latest` instead clones current Java `main` and records its resolved SHA. It still uses the explicitly selected Spark release. Both `JAVA_HOME` and the probe's `JAVA17_HOME` are set to the selected JDK 17. A supplied checkout gets build outputs but its source and revision are not changed; use a separate checkout if another process is building it.

The runner sends every current corpus plan through Spark with ANSI explicitly disabled and enabled, compares both columns with the saved Spark column and `expected.json`, evaluates the eight overflow expressions, and runs the three decimal schema cases with ANSI disabled. It records actual Spark, Scala, JDK and packaged spec versions, the native ANSI default, resolved dependencies, source revisions and input hashes. `--out` must be new or empty. It retains logs on failure and writes `summary.json` and `summary.txt` only after the complete run succeeds.

Build failures, incorrect runtime identity, incomplete or malformed output, and failed safe-value/schema controls fail the command. Schema or option differences are reported as observations, so a successful run does not mean full Substrait conformance. The existing saved matrix and version pins are not replaced by these profiles.

The [`Spark runtimes` workflow](../.github/workflows/spark-runtimes.yml) runs every profile on pushes and pull requests against the pinned Java revision. Its weekly run uses current Java `main`; manual runs can select either. Every runtime has its own job and uploaded result artifact, including failures. The workflow publishes observations in the job summary and does not commit results back to the repository.

## What else is in here

`reverify.sh` runs the consumer side: it hands each implementation a plan and records the schema it
derives. The diagnostics below are separate from that path. The Spark runtime workflow also runs
the Spark decimal and overflow diagnostics; the other engine diagnostics remain manual.

### Focused schema diagnostics

These commands run from the corpus root after setting up the relevant participant.
They report additional observations separately from the saved matrix.

**Minimal consumer and text cases.** [32 plans with controls](structural-cases/README.md)
cover Go relation metadata and union nullability, validator virtual tables, DuckDB
unsupported-operation errors, Acero projection nullability and function-extension
resolution, explain type round-trips, and Spark decimal result types. Run
`python3 probe/structural_cases.py duckdb`, `go`, `validator`, `explain`, `spark`,
`acero` or `acero-functions` after setting up that participant. Each plan runs in its own process;
errors remain visible beside schema observations. `--check` makes differences fail
the command. These diagnostics do not update the saved matrix.

**Spark decimal overflow options.** `spark_function_options.py` evaluates eight
expressions through `ToSparkExpression`: add and multiply with ANSI disabled and
enabled, each with a safe-value control and an overflowing invocation carrying
`overflow=ERROR`. It uses literal inputs and does not start a Spark session.

```sh
export SUBSTRAIT_JAVA_DIR=/path/to/substrait-java
export JAVA17_HOME=/path/to/jdk-17
export JAVA_HOME="$JAVA17_HOME"
python3 probe/spark_function_options.py
python3 probe/spark_function_options.py --check
```

The JSON Lines include the options passed to the importer, the returned type and
nullability, and the value or error. Safe controls must return `4.00` and `3.000`
with their expected decimal types. An overflowing invocation with explicit ERROR
must raise an arithmetic error or be rejected during conversion, as required by
the [option contract in spec v0.103.0](https://github.com/substrait-io/substrait/blob/v0.103.0/site/docs/expressions/scalar_functions.md#options).
Nullability is reported separately and does not determine the verdict.

With substrait-java `fff639064df794840db36fffcd881c09100e23df` and Spark 3.5.4,
both explicit-ERROR cases return null when ANSI is disabled and raise an error
when it is enabled. All four safe controls pass: normal diagnostic mode exits 0
with two differences, while `--check` exits 1. Missing or malformed observations
and failed controls always fail the command. These evaluated expressions are
separate from the 32 structural plans and the saved 98-plan matrix.

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
`ReadRel.base_schema`. These 29 checks are separate from the 98 plans in the main corpus. They reproduce
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

### Impala type-factory comparison

`impala_types.py` runs all canonical plans through Isthmus twice, with its default
provider and with a provider using `ImpalaTypeFactoryImpl`. Both runs use the same
combined Java classpath, with Isthmus dependencies first. This measures relation
schemas at the Isthmus boundary. It does not invoke Impala's optimizer, catalog,
authorization or execution, and does not add an Impala
consumer column to the saved matrix.

[The saved paired measurement](../results/impala-types/README.md) records the
first run, its source revisions, changed cases and interpretation limits.

Use a JDK 17 and already built Isthmus and Impala artifacts. Resolve a fresh
Isthmus classpath with `probe/cp.sh isthmus` against the desired substrait-java
checkout. The Impala classpath must include its built planner classes, frontend
classes or jar, and their dependencies. Classpath files contain one line of
explicit absolute paths, separated by the platform's classpath separator;
wildcards are not expanded. The probe does not download or build dependencies.

```sh
python3 probe/impala_types.py \
  --isthmus-classpath <isthmus-classpath.txt> \
  --impala-classpath <impala-classpath.txt> \
  --substrait-java-revision <source-revision-from-build> \
  --impala-revision <source-revision-from-build> \
  --out run/impala-types
```

The output directory must be new. It keeps both raw and normalized columns,
comparisons against `expected.json`, a pairwise `comparison.txt`, and a local
`record.json` with input fingerprints. Revision labels come from the supplied
build records; hashing bytecode does not establish which source built it. The
per-run logs record loaded factory locations, Calcite and Java versions, and
both the provider and `RelBuilder` factories. This distinction matters: the
pinned Isthmus provider passes its type system to `RelBuilder`, which constructs
its own factory rather than reusing the provider's factory instance.

Schema differences are measurements. Missing classes, process failures,
incomplete columns, wholly refused columns or unparseable schema answers fail
the harness. `COMPLETE` is written only after both columns pass these checks.
The existing Calcite schema normalizer compares types, order and nullability;
pairwise comparison also shows name and refusal-message changes, so those need
to be distinguished from type differences. Keep run artifacts local: their
provenance logs contain machine paths.

### Other probes

**Focused producer checks.** These extend the existing producer probes and do not
update the saved consumer matrix:

```sh
SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
"$SP/venv/bin/python" probe/duckdb_producer.py --load-only --decimal-roundtrip
```

This compares bound types before and after DuckDB's own export/import for three
decimal additions and a read control. The input table contains one row so the
producer cannot replace it with an empty result. Target queries are described,
not executed. It prints versions, types and a JSON summary; `--check` fails when
the types differ.

To check required output types on DataFusion-produced aggregates, from a
DataFusion checkout with its pinned Rust toolchain available:

```sh
mkdir -p datafusion/substrait/examples
cp /path/to/substrait-conformance-cases/probe/datafusion_producer_probe.rs \
  datafusion/substrait/examples/corpus_producer.rs
cargo run --locked -p datafusion-substrait --example corpus_producer -- --aggregate-output-types
```

Choose an unused example filename if `corpus_producer.rs` already exists. The mode
checks `count`, `sum`, `avg` and `min` over an empty named table and reports whether
each exported call carries `output_type`. It does not infer a missing type or pass
the plan through a consumer. `--check` fails if a declaration is missing. This
mode was verified against DataFusion main at `8a9228164`; the matrix's separate
version pin continues to describe its saved measurements.

**Where each implementation differs.** `diffs.py` writes `results/DIFFS.md`, which is `differed.json`
joined to the columns and the expectations: per participant, the cases that differ, the expectation,
the answer, the reason and what came of it. It is built from the same model `heatmap.py` draws, so
the page and the file cannot disagree, and `selfcheck.sh` compares it with its generator.

**What the corpus covers.** `coverage.py` counts which relations of `algebra.proto` the plans reach
and writes the block the README carries; `selfcheck.sh` compares that block with this output, and a
plan using a relation the script's transcribed list does not name fails rather than being counted as
something else.

**The numbers in the prose.** `check_pages.py` holds every number the pages state about the corpus
next to the file it comes from. A number gone stale fails; so does a sentence reworded past the
pattern that watches it, because a guard that quietly stops matching is the failure this repository
has already had three times.

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

## Finding index

[FINDINGS.md](../FINDINGS.md) links each reported contract to the relevant matrix cases or focused probe, with controls and related implementation PRs. It keeps producer checks separate from static consumer plans.
