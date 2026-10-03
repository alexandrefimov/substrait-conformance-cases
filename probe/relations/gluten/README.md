# Gluten relation diagnostics

This diagnostic is separate from the four saved relation columns. It reads compiled
bundles, binds input tables independently, converts the plan through Gluten and
executes the Velox plan. Its JSON Lines records native schemas and rows without
scoring cases or updating the matrix. `native_relations` records the relation
message names Gluten decoded, which can differ when its fork uses different wire
field numbers from the corpus.

## Build and run

Use Gluten at the revision in `probe/versions.env`, built with
`dev/builddeps-veloxbe.sh --build_tests=ON`. From this repository's root, with
`GLUTEN_DIR` and `GLUTEN_BUILD` pointing to that checkout and its configured build:

```sh
cmake -S "$GLUTEN_DIR/cpp" -B "$GLUTEN_BUILD" \
  -DCMAKE_PROJECT_gluten_INCLUDE="$PWD/probe/relations/gluten/inject.cmake"
cmake --build "$GLUTEN_BUILD" --target gluten_relations_probe -j 2

bash tests/relations/bootstrap.sh
python3 probe/relations/gluten/run.py \
  --binary "$GLUTEN_BUILD/relations-probe/gluten_relations_probe" \
  --gluten-revision <revision-from-build-record> > observations.jsonl

python3 -m unittest discover -s probe/relations/gluten -p test_run.py
python3 probe/relations/gluten/check_native.py \
  --binary "$GLUTEN_BUILD/relations-probe/gluten_relations_probe"
```

The hook needs CMake 3.19 or newer. It adds one target without editing Gluten's
sources. Its path remains in the build cache, so keep this checkout available
while using that configuration. Do not replace another task's
`CMAKE_PROJECT_gluten_INCLUDE` hook. The case protobuf uses Gluten's own
Substrait protos and compiler; no second copy of its C++ bindings is linked.

The driver needs bootstrap bindings and a compatible Python protobuf runtime.
`bootstrap.sh` uses the authoring path resolver; execution imports neither YAML
nor the case compiler. Optional positional arguments select particular `.pb`
bundles. Each case runs in a separate process with a timeout and a private
temporary directory for writes. That directory is removed afterwards.

The revision label comes from the supplied build record, not from inspecting the
executable. The provenance record hashes the executable; each observation hashes
its original bundle. Keep the native build record with the observations.

## What is measured

The driver removes the expectation before calling the consumer. The plan,
extensions, declared outputs and fixtures remain unchanged. The consumer replaces
only a named read's source with `iterator:<index>`. Each read occurrence gets its
own iterator, including repeated reads of one table. Independent fixture vectors
avoid Gluten's Substrait type and literal parser. Its query-trace input path
materializes these batches as `ValuesNode`s. Leaf columns receive unique stream
aliases so self-joins do not collide on field names. Those aliases can remain in
the output: this path does not measure the consumer's naming of table columns.

Fixture support is limited to `i64`, `string` and `bool`. Read filters, projections,
emit mappings and other metadata are refused because that input path would bypass
them. Missing fixtures, duplicate names, schema mismatches and unsupported fixture
kinds are `HARNESS-ERROR`, not evidence of a Gluten refusal.

`OK` means conversion and execution completed. `schema` is native Velox type text
and `arity` is the returned column count. Each cell in `rows` is native text, or
JSON null for a null cell. Rows retain execution order and duplicates. Empty
results are empty arrays. Expected rows and root names are never substituted.
Velox carries no nullability; these are not normalized or scored agreements.

`ERROR` records a consumer decoding, conversion or execution refusal.
`CRASH` records a nonzero native exit; `TIMEOUT` records a killed process. `HARNESS-ERROR`, `CRASH` and `TIMEOUT` make
the driver exit nonzero after recording the selected cases. A successful gtest
exit with no record also fails. Inspect native messages before sharing and do
not commit raw logs.

A participant column still needs normalization, complete fixture support, reviewed
divergences and integration with replay and CI. This runner does not add Gluten
to that matrix.
