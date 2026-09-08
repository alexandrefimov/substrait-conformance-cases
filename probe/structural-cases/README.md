# Minimal consumer and text round-trip cases

These 32 plans isolate relation metadata, nullability, virtual-table row typing,
unsupported-operation errors, function-extension resolution, type text round-trips
and decimal result types.
They are separate from the 78-plan matrix. The Spark plans declare spec v0.103.0;
the Acero plans declare v0.102.0, except for the three legacy URI controls in
`acero-functions`, which declare v0.44.0. The other plans declare v0.87.0.
Each uses only the fields needed for its case.

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

SETUP_ONLY=Acero bash probe/setup.sh
python3 probe/structural_cases.py acero
python3 probe/structural_cases.py acero-functions

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
| Acero | 4 | An identity or reordered emit preserves the selected fields' types and nullability. A bare read and an emit selecting only the nullable field are controls. Native Acero and `Table.select` apply the same mappings to the same nonempty table; every path must preserve rows. |
| Acero functions | 5 | A function from an unregistered extension is rejected; standard decimal division either preserves the specified result or is unsupported. Legacy URI controls reject the unregistered extension and decimal extension, and accept integer addition. All input fields and function outputs are nullable. |

The DuckDB worker registers `t(x INTEGER NOT NULL)` with rows 1 and 2. Go and the
validator infer schemas without registering a database table. The Go and Acero
directories include binary equivalents of their JSON plans because their probes
read binary protobuf. To regenerate those files with the Python environment:

```sh
SP="${SUBSTRAIT_PROBE_ENV:-$PWD/.probe-env}"
"$SP/pysub/bin/python" - <<'PY'
from pathlib import Path
import json
from google.protobuf.json_format import Parse
from substrait import proto

for group in ("go", "acero", "acero-functions"):
    for path in Path("probe/structural-cases", group).glob("*.json"):
        if "extensionUris" in json.loads(path.read_text()):
            continue  # Legacy controls use Arrow's older protobuf bindings below.
        plan = Parse(path.read_text(), proto.Plan())
        path.with_suffix(".bin").write_bytes(plan.SerializeToString())
PY

"$SP/venv/bin/python" - <<'PY'
from pathlib import Path
import json
from pyarrow._substrait import _parse_json_plan

for path in Path("probe/structural-cases/acero-functions").glob("*.json"):
    if "extensionUris" in json.loads(path.read_text()):
        path.with_suffix(".bin").write_bytes(_parse_json_plan(path.read_bytes()))
PY
```

The second encoder uses a private helper in the pinned PyArrow 25.0.1 only for
legacy URI controls. Do not use it for modern URN fixtures: its older protobuf
bindings silently drop the URN fields. Running the diagnostics uses the committed
binaries and does not require either encoder.

## Interpretation

The Acero input is `r: int64 required, n: int64 nullable`, with rows `(1, null)`
and `(2, 3)`. The table provider verifies the requested input schema and returns
the table with that schema intact. Under the
[emit rule in spec v0.102.0](https://github.com/substrait-io/substrait/blob/v0.102.0/site/docs/relations/common_fields.md#emit),
the expected outputs select the same fields;
there are no scalar functions or casts. In PyArrow 25.0.1, bare reads preserve
requiredness, but both identity and reordered emits make `r` nullable. Direct
Acero field-reference projections produce the same change without Substrait.
`Table.select` preserves the selected fields' nullability in all four cases.
All paths retain the expected values, including the actual null in `n`.

The JSON Lines report Substrait, native Acero and `Table.select` results for each
case. A schema difference in either Acero path is a mismatch; a row difference,
failed input-schema check or failing `Table.select` control stops the run.
PyArrow 25.0.1 reports two differing cases and zero failed controls. Normal mode
exits 0 for this result; `--check` exits 1.

The Arrow implementation turns a Substrait emit into a
[field-reference project](https://github.com/apache/arrow/blob/apache-arrow-25.0.1/cpp/src/arrow/engine/substrait/relation_internal.cc#L136).
[ProjectNode](https://github.com/apache/arrow/blob/apache-arrow-25.0.1/cpp/src/arrow/acero/project_node.cc#L70)
creates new fields from expression names and types without carrying input
nullability. This explains the focused projection cases. It does not establish
the cause of the corpus's join or function-result nullability differences.
Arrow also documents incomplete support for
[non-nullable inputs](https://github.com/apache/arrow/blob/apache-arrow-25.0.1/docs/source/cpp/acero/substrait.rst#types);
these inputs obey their declared nullability, and this check concerns the output
schema rather than validation of invalid input rows.

The `acero-functions` group compares modern extension URNs with legacy URI
controls. In PyArrow 25.0.1, an integer `add` from the synthetic, unregistered
`extension:example.com:unregistered_arithmetic` executes as ordinary addition.
Its legacy URI counterpart is rejected. A registered legacy arithmetic URI
returns the expected `5`, `-5` and nulls, checking the execution path independently.

The standard decimal URN also reaches native arithmetic: `decimal(10,2)` divided
by `decimal(5,1)` returns `decimal(16,7)`, whereas the
[v0.102.0 extension formula](https://github.com/substrait-io/substrait/blob/v0.102.0/extensions/functions_arithmetic_decimal.yaml#L67)
specifies `decimal(21,8)`. The exact value `1.00 / 256.0 = 0.00390625` fits that
scale, but the observed result is `0.0039062`; the negative value loses the same
digit. Both left-null and right-null rows remain null. The legacy decimal URI
is rejected because Arrow has no registered conversion for that extension.

Arrow's [extension decoder](https://github.com/apache/arrow/blob/apache-arrow-25.0.1/cpp/src/arrow/engine/substrait/util_internal.h#L43)
reads legacy URI fields. Modern URN fields therefore leave an empty URI, which
activates the [name-only fallback](https://github.com/apache/arrow/blob/apache-arrow-25.0.1/cpp/src/arrow/engine/substrait/expression_internal.cc#L363).
This explains why accepting the decimal plan does not demonstrate support for
its extension. The diagnostic allows unsupported decimal functionality to be
rejected; an accepted result must match the standard type and exact values.
The unregistered extension must be rejected. Native Arrow arithmetic is included
as a diagnostic comparison, not as the Substrait expectation.

PyArrow 25.0.1 reports two differing cases and three passing controls in this
group. Normal mode exits 0 and `--check` exits 1. These observations do not require
Arrow to implement every extension or adopt Substrait's formula in its native
arithmetic API; they concern resolution of the function named by the plan.

The Go union expectations follow the [set-operation rules in v0.87.0](https://github.com/substrait-io/substrait/blob/v0.87.0/site/docs/relations/logical_relations.md#set-operation-types). The mixed inputs are exercised in both orders. The existing eight `derived-schema/setop_*` plans cover the wider operation table.

The explain runner calls the formatter and feeds its exact output to the parser. It compares the returned read schema and root names, including widths, precision, scale and nullability. `SUBSTRAIT_EXPLAIN` can select an executable; otherwise it is found on `PATH`. A parser panic is reported as a difference. A formatter failure, other parser failure or malformed JSON stops the diagnostic rather than being counted as a successful observation. The four parameterized cases reproduce the numeric-parameter panic in 0.9.0; they contain no functions, literals, map or struct field types.

The Spark expectations are calculated from [functions_arithmetic_decimal.yaml in v0.103.0](https://github.com/substrait-io/substrait/blob/v0.103.0/extensions/functions_arithmetic_decimal.yaml). For divide, `scale = max(6, 2 + 5 + 1) = 8` and `precision = 10 - 2 + 5 + 8 = 21`. The probe registers the declared input schema and asks the Spark converter for the resulting schema. Nullable operands keep the precision comparison separate from required-output and ANSI-mode questions. This is a schema check; the probe does not execute rows or establish a numerical error.

The other consumer cases check relation schemas and rows, or safe rejection of an unsupported operation. The virtual-table cases do not depend on unresolved rules for rows that disagree with `base_schema`.

The existing `derived-schema/emit_fetch.json` intentionally omits offset and uses `countExpr`. Both are valid in its declared spec version, but the old Go decoder requires legacy literal offset/count fields. [Go PR #295](https://github.com/substrait-io/substrait-go/pull/295) covers both parts; the offset error alone does not isolate the expression-encoding gap.
