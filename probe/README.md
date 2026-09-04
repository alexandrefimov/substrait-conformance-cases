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

`versions.env` is the single place these are pinned, and `setup.sh` installs exactly them.

| | version | taken by |
| --- | --- | --- |
| substrait-java, Isthmus/Calcite | the checkout `SUBSTRAIT_JAVA_DIR` points at | `SchemaOf.java`, `CalciteSchemaOf.java` |
| substrait-python | 0.31.0 | `python_one.py` |
| substrait-validator | built from `main` at `2a10470` | `validator_one.py` |
| substrait-go | v9 at `cb2d6e648bc0` | `go/main.go` |
| DataFusion | `4a93adee0` | `datafusion_corpus_probe.rs` |
| DuckDB | 1.5.5, substrait community extension | `duckdb_one.py` |
| Acero | pyarrow 25.0.1 | `acero_one.py` |
| Spark | 3.5.4 | `SparkSchemaOf.java` |
| Gluten/Velox | `f7f5f04` | `SubstraitCorpusProbeTest.cc`, in a cluster |

Spark and Isthmus need a built `:spark:spark-3.5_2.12` and `:isthmus` in that checkout; `cp.sh`
resolves their classpaths from Gradle and caches them under the probe environment.

## substrait-validator

The release on PyPI is no use: it is on spec 0.57.1 and does not load these cases. A build from
`main` is needed - cargo, protoc, python >= 3.10:

    SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
    git clone --depth 1 https://github.com/substrait-io/substrait-validator "$SP/substrait-validator"
    python3 -m venv "$SP/val314"
    PATH="$HOME/.cargo/bin:$PATH" PROTOC=$(which protoc) \
      "$SP/val314/bin/pip" install "$SP/substrait-validator/py"
    "$SP/val314/bin/pip" install -U 'protobuf==7.36.1'

The last line is required: the generated code needs a 7.x runtime while the package pins
`protobuf<7`. The commit the saved column was taken at is in `versions.env`. The path to the venv is
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
