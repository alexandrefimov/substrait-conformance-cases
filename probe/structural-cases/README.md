# Minimal consumer and text round-trip cases

These 23 plans isolate relation metadata, nullability, virtual-table row typing,
unsupported-operation errors, type text round-trips and decimal result types.
They are separate from the 78-plan matrix. The Spark plans declare spec v0.103.0;
the other plans declare v0.87.0. Each uses only the fields needed for its case.

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

# Optional text-format diagnostic; this tool is not a scored matrix participant.
cargo install substrait-explain --version 0.9.0 --locked
python3 probe/structural_cases.py explain

# Requires a substrait-java checkout and JDK 17; see the probe setup notes.
export SUBSTRAIT_JAVA_DIR=/path/to/substrait-java
export JAVA17_HOME=/path/to/jdk17
python3 probe/structural_cases.py spark
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
| Go | 6 | Three inner joins retain the same two required i32 fields with absent, empty or direct `RelCommon`. UNION ALL of required i64 inputs returns required i64; making either input nullable returns nullable i64. |
| Validator | 4 | Empty, one-column and two-column virtual tables retain their declared struct schema. Emitting the second column yields one required string field. All nonempty rows exactly match their base schema. |
| Explain | 5 | A named read with i64, varchar(10), fixed-char(5), fixed-binary(4) or decimal(10,2) survives JSON → text → JSON with its schema and root names preserved. The i64 case is the control. |
| Spark | 3 | Nullable decimal(10,2) and decimal(5,1) produce decimal(11,2) for add, decimal(16,3) for multiply, and decimal(21,8) for divide under the standard extension contract. Add and multiply are controls. |

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

## Interpretation

The Go union expectations follow the [set-operation rules in v0.87.0](https://github.com/substrait-io/substrait/blob/v0.87.0/site/docs/relations/logical_relations.md#set-operation-types). The mixed inputs are exercised in both orders. The existing eight `derived-schema/setop_*` plans cover the wider operation table.

The explain runner calls the formatter and feeds its exact output to the parser. It compares the returned read schema and root names, including widths, precision, scale and nullability. `SUBSTRAIT_EXPLAIN` can select an executable; otherwise it is found on `PATH`. A parser panic is reported as a difference. A formatter failure, other parser failure or malformed JSON stops the diagnostic rather than being counted as a successful observation. The four parameterized cases reproduce the numeric-parameter panic in 0.9.0; they contain no functions, literals, map or struct field types.

The Spark expectations are calculated from [functions_arithmetic_decimal.yaml in v0.103.0](https://github.com/substrait-io/substrait/blob/v0.103.0/extensions/functions_arithmetic_decimal.yaml). For divide, `scale = max(6, 2 + 5 + 1) = 8` and `precision = 10 - 2 + 5 + 8 = 21`. The probe registers the declared input schema and asks the Spark converter for the resulting schema. Nullable operands keep the precision comparison separate from required-output and ANSI-mode questions. This is a schema check; the probe does not execute rows or establish a numerical error.

The other consumer cases check relation schemas and rows, or safe rejection of an unsupported operation. The virtual-table cases do not depend on unresolved rules for rows that disagree with `base_schema`.

The existing `derived-schema/emit_fetch.json` intentionally omits offset and uses `countExpr`. Both are valid in its declared spec version, but the old Go decoder requires legacy literal offset/count fields. [Go PR #295](https://github.com/substrait-io/substrait-go/pull/295) covers both parts; the offset error alone does not isolate the expression-encoding gap.
