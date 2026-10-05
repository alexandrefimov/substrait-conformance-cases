# Probes

This directory measures the generated schema corpus. The [relation corpus](relations/README.md)
has separate runners; [producer shapes](producer-shapes/README.md) passes SQL-generated plans
between implementations. The [producer corpus](../producers/README.md) saves broader SQL-produced
plan sets and their declaration and consumer checks. Commands below run from the repository root.

| Task | Command |
| --- | --- |
| Check committed artifacts without running a participant | `bash probe/selfcheck.sh` |
| Verify that every self-check can fail | `bash probe/selfcheck-negative.sh` |
| Reproduce one saved schema column | `bash probe/replay_column.sh <NAME>` |
| Observe changes since the pin | `LATEST=1 bash probe/replay_column.sh <NAME>` |
| Regenerate and measure the schema corpus | `bash probe/reverify.sh` |

`<NAME>` is `PYTHON`, `GO`, `DUCKDB`, `ACERO`, `VALIDATOR`, `JAVA`, `ISTHMUS`, `SPARK` or
`DATAFUSION`. Gluten uses a [separate path](#glutenvelox).

`replay_column.sh` builds one environment through `setup.sh` and compares every answer with
the saved column. The installed version must match `versions.env`; DuckDB's extension version
is read back because community `INSTALL` cannot request a specific revision.

`LATEST=1` uses `versions-latest.env`. Changed answers are observations; a broken harness still
fails. The weekly drift workflow collects proposed [DRIFT.txt](../results/DRIFT.txt) changes
as artifacts for review and writes no Git refs. Pinned CI runs self-checks and replays columns.

`OUT=<dir>` retains the normalized column, raw output, changes and a provenance record: actual
versions, repository revision and an input fingerprint over the corpus, expectations and
normalizer. `selfcheck.sh` checks saved-artifact consistency and tested reasons; it needs python3
and no network. It proves neither the spec reading nor a difference's cause. The negative gate
breaks invariants in a temporary copy and requires each failure to name the broken invariant.

## What a run needs, and what fails it

The full local sweep needs python3, Go 1.23 or newer, JDK 17, Rust with cargo, and protoc.
Protoc must find its well-known types (`protobuf-compiler` and `libprotobuf-dev` on Debian/Ubuntu).
DataFusion uses its checkout's pinned `rust-toolchain.toml`; rustup can fetch it. Spark discovers
JDK 17 automatically only on macOS; set `JAVA17_HOME` elsewhere.

`setup.sh` builds dependencies under `SUBSTRAIT_PROBE_ENV` (default `<repo>/.probe-env`). The
external checkouts are `SUBSTRAIT_JAVA_DIR` and `DF_DIR`. `SUBSTRAIT_PYTHON_ENV`,
`SUBSTRAIT_VALIDATOR_ENV` and `PROBE_CACHE` override individual environment/cache paths.
`SETUP_ONLY=<key>` builds one component instead of all of them.

`reverify.sh` requires the Java and DataFusion commits in `versions.env`; empty `SJ_EXPECT=` or
`DF_EXPECT=` deliberately disables the corresponding check. By default it regenerates the corpus,
manifest and expectations into temporary files and reports differences without replacing them.
`UPDATE_CORPUS=1` replaces those inputs; `UPDATE_COLUMNS=1` replaces saved columns, MATRIX.txt
and the generated pages. Use these flags only for an intended update and inspect the full diff.

`normalize.py` requires one answer per case before a column can be compared. Full answers are in
`results/<NAME>.txt`; MATRIX.txt truncates them. `-` marks a refusal and `·` a case not run.
A schema can coexist with diagnostics, particularly in the validator column.

A refused plan is a measured result. Harness failures exit non-zero with a `FAILED` line:
wrong checkout revision, missing environment, failed generation, source/artifact drift,
incomplete or unnormalizable output, a participant answering nothing, or a skipped participant
without `ALLOW_SKIPPED=1`. That flag permits an intentional partial run, not a complete sweep.

## The participants and their versions

[versions.env](versions.env) is the authoritative pin set. Update a pin together with its
column and provenance. Runner entry points are:

| Participant | Runner |
| --- | --- |
| substrait-java, Isthmus/Calcite | `SchemaOf.java`, `CalciteSchemaOf.java` |
| substrait-python | `python_one.py` |
| substrait-validator | `validator_one.py` |
| substrait-go | `go/main.go` |
| DataFusion | `datafusion_corpus_probe.rs` |
| DuckDB | `duckdb_one.py` |
| Acero | `acero_one.py` |
| Spark | `SparkSchemaOf.java` |
| Gluten/Velox | `SubstraitCorpusProbeTest.cc`, separate cluster run |

Spark and Isthmus need `:spark:spark-3.5_2.12` and `:isthmus` built in the Java checkout.
`cp.sh` resolves Gradle classpaths and caches them under the probe environment.

A column is compared only as far as the participant's type system reaches. The head of each
`results/<NAME>.txt` repeats its own limit:

| | how far the column goes |
| --- | --- |
| DuckDB | carries no nullability in its logical types, so only types, arity and column order are compared. Comparing nullability would record the boundary of its type system as a divergence |
| DataFusion, DuckDB | have no string type with a length. Neither can represent `varchar<10>` or `fixedchar<5>`, so `stringlen_declared` differs at a type-system boundary |
| Acero, Spark | do carry nullability and are compared on it |
| Gluten | carries no nullability either, and repeats a function's declared type instead of deriving it |
| substrait-validator | the pinned revision retains declared function return types; schema output must be read alongside diagnostics. The mutation checks final output schemas, not every expression's type |

Package and specification versions are distinct: a binding may use older packaged definitions.
Pins identify saved measurements; `versions-latest.env` identifies drift targets.

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

The following diagnostics are separate from the saved-column sweep. The Spark runtime workflow
also runs its decimal and overflow checks; the other engine diagnostics are manual.

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
separate from the 32 structural plans and the saved 108-plan matrix.

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
`ReadRel.base_schema`. These 29 checks are separate from the 108 plans in the main corpus. They reproduce
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
mode was verified at `c922f8811`: all four calls carry `output_type`. This checks
producer declarations only; aggregation phases and the declared AVG contract are separate checks.

**Reports and generated pages.** `diffs.py` joins expectations, columns and reasons into
`results/DIFFS.md`. `heatmap.py` uses the same model for the matrix SVGs and `docs/index.html`.
`coverage.py` writes the relation-coverage block in METHOD.md and rejects unknown relation kinds.
`check_pages.py` checks registered prose counts and requires pattern updates when those sentences
are reworded. `selfcheck.sh` checks generated output and cell verdicts against their sources.

**Producers: what an implementation declares.** A consumer's answer is only half the question; the
other half is what a producer writes into `output_type` in the first place. `ProducerIsthmus.java`
and `ProducerSpark.java` print what those two declare when they turn SQL into a plan,
`duckdb_producer.py` does the same for DuckDB and additionally compares the type it reports directly
against the type after a `get_substrait_json` / `from_substrait_json` round trip, and
`datafusion_producer_probe.rs` does it for DataFusion and writes the plans it produced to
`$SUBSTRAIT_PLANS_OUT`. `SchemaOfBin.java` reads those written plans back through substrait-java, so
one implementation's declaration can be handed to another. `go-producer/` prints
what substrait-go computes as a function's return type from the extension declaration. `producer-shapes/` is the
wider version of the same question: it turns one list of SQL into plans from DuckDB, DataFusion,
Isthmus and Spark, prints what each plan contains, and hands a chosen plan to every consumer, which
is how a divergence in the corpus is checked against what producers actually write. It requires
Go 1.24 or newer, separately from the consumer probe's Go 1.23 minimum:

    (cd probe/go-producer && GOTOOLCHAIN=local go run .)

After setup and a successful `reverify.sh`, `bash probe/lie_matrix.sh` reruns the declaration
swap across the nine local participants. The sweep compiles its `SchemaOf` helper. Keep cargo
on PATH for this script and `binding_matrix.sh`, or DataFusion is skipped.

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

The full sweep has run in a clean Ubuntu 24.04 container. To test cold-build reproducibility,
use isolated empty Gradle/build, cargo-target, pip and Go-module caches; do not clear shared
caches. Set `JAVA17_HOME` explicitly outside macOS and use the checkouts pinned by `versions.env`.
`setup.sh` builds the remaining environments. Pinned CI replays individual columns; a full
`reverify.sh` run also checks regeneration across the complete local sweep.

## substrait-validator

`setup.sh` builds the pinned source revision with cargo and protoc. Protoc must find
`google/protobuf/any.proto` (`libprotobuf-dev` on Debian/Ubuntu). The old PyPI release targets
spec 0.57.1 and cannot load these cases. Manual setup:

    SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
    git clone https://github.com/substrait-io/substrait-validator "$SP/substrait-validator"
    git -C "$SP/substrait-validator" checkout "$SUBSTRAIT_VALIDATOR_COMMIT"
    python3 -m venv "$SP/val"
    PATH="$HOME/.cargo/bin:$PATH" PROTOC=$(which protoc) \
      "$SP/val/bin/pip" install "$SP/substrait-validator/py"
    "$SP/val/bin/pip" install -U 'protobuf==7.36.1'

Load the commit variable first with `. probe/versions.env`. The protobuf 7.x runtime override
is required by generated bindings despite the package's `<7` constraint. Override the venv
location with `SUBSTRAIT_VALIDATOR_ENV`.

The default validator probe reports that YAML resolution was not attempted. At the pinned validator
revision, `FunctionBinding::new` also leaves function matching and return-type checking unimplemented
and retains the supplied return type. Its schema output must be read alongside the diagnostics;
returning a schema is not an assertion that the plan passed validation.

## Gluten/Velox

Gluten is outside `reverify.sh`; its column is taken separately in a cluster. Each column
retains its own measurement date. `gluten_column.py` normalizes probe output, removing the
stack after ` Retriable:` while preserving the message.

Build the Gluten revision in `versions.env` with `dev/builddeps-veloxbe.sh --build_tests=ON`.
Add `SubstraitCorpusProbeTest.cc` to `cpp/velox/tests` and its CMake target, then point
`SUBSTRAIT_CORPUS_DIR` at `derived-schema-virtual-tables`, generated by `to_virtual_tables.py`.
The test build supplies `JsonToProtoConverter`. This reader supports `virtual_table` and
`local_files`, not the canonical corpus's named tables.

The separate [relation diagnostic](relations/gluten/README.md) records native schemas and
executed rows without scoring or updating the relation matrix.

## Decimal return types

[decimal-rules/](decimal-rules/) is outside the corpus: it does not read a plan. It compares the
`functions_arithmetic_decimal` return expressions against five other rule sets; the reference they
came from, two engines that implement it and one that does not; over every decimal operand type
pair, and runs the cases of
[substrait-io/substrait#1213](https://github.com/substrait-io/substrait/pull/1213) on Spark and Hive
in Docker. Its README says what agrees with what and what was not measured.

## Whether a call is bound

`binding_matrix.sh` asks the nine participants a question the declaration swap does not: whether the
function a call names is resolved at all. `make_unbound_corpus.py` rewrites only the name in the
extension declaration - a control with the same signature and return, a name whose argument types no
implementation declares, and a name no extension file declares - and `binding_report.py` reads the
three columns against the original. [results/BINDING.txt](../results/BINDING.txt) is the saved run;
`METHOD.md` says what each answer establishes.

## Finding index

[FINDINGS.md](../FINDINGS.md) links reports to corpus cases and focused reproducers, separating
producer checks from static consumer plans.
