# Minimal consumer cases

These 12 plans isolate optional relation metadata, virtual-table row typing, and
unsupported-operation error handling. They are separate from the 78-plan matrix.
All plans declare spec v0.87.0 and use only the fields needed for the case.

Run from the repository root after installing the relevant participant:

```sh
SETUP_ONLY=DuckDB bash probe/setup.sh
SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
"$SP/venv/bin/python" -c "import duckdb; duckdb.sql('INSTALL substrait FROM community')"
python3 probe/structural_cases.py duckdb

SETUP_ONLY=substrait-go bash probe/setup.sh
python3 probe/structural_cases.py go

SETUP_ONLY=substrait-validator bash probe/setup.sh
python3 probe/structural_cases.py validator
```

The environments default to `.probe-env`; `SUBSTRAIT_PROBE_ENV` selects another
location. The validator also accepts `SUBSTRAIT_VALIDATOR_ENV`. Go needs Go 1.23
or newer on `PATH`. Building the validator needs Rust, protoc and its well-known
type definitions, as described in the [probe setup notes](../README.md).

The runner starts a separate process for each plan. It reports JSON Lines with
the observation and whether it satisfies `expected.json`, followed by a summary.
Normal diagnostic mode exits successfully when controls pass, even when a case
differs. Add `--check` to require every case to satisfy its expectation. Missing
tools, malformed output and failing controls always fail the command.

| Group | Cases | Contract |
| --- | ---: | --- |
| DuckDB | 5 | Read, inner join and union-all controls must return the stated columns and rows. Union-distinct and right-mark may return a normal unsupported error; they must not crash. If supported, their rows and columns must match too. |
| Go | 3 | An inner join has the same two required i32 fields with absent, empty or explicitly direct `RelCommon`. All three must be accepted. |
| Validator | 4 | Empty, one-column and two-column virtual tables retain their declared struct schema. Emitting the second column yields one required string field. All nonempty rows exactly match their base schema. |

The DuckDB worker registers `t(x INTEGER NOT NULL)` with rows 1 and 2. Go and the
validator infer schemas without registering a database table. The Go directory
includes binary equivalents of its JSON plans because the existing Go probe
reads binary protobuf. To regenerate those files with the Python environment:

```sh
SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
"$SP/pysub/bin/python" - <<'PY'
from pathlib import Path
from google.protobuf.json_format import Parse
from substrait import proto

for path in Path("probe/structural-cases/go").glob("*.json"):
    plan = Parse(path.read_text(), proto.Plan())
    path.with_suffix(".bin").write_bytes(plan.SerializeToString())
PY
```

The oracle checks relation schemas and rows, or safe rejection of an unsupported
operation. It does not copy a function's declared output type. These virtual-table
cases do not depend on unresolved rules for rows that disagree with `base_schema`.
