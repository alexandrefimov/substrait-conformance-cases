# Case generators: plan -> derived schema

Generators build plans with substrait-java and print its derived schemas as diagnostics.
Corpus expectations come separately from `probe/expected.py`, authored from the spec without
reading generators or their output. [METHOD.md](../METHOD.md#where-the-expectations-come-from)
explains that boundary. The [relation corpus](../tests/relations/README.md) has a separate YAML
authoring and protobuf compilation path.

Run from this directory:

    SUBSTRAIT_JAVA_DIR=<substrait-java checkout> bash make_classpath.sh
    javac -cp "$(cat classpath.txt)" -d out *.java
    java  -cp "out:$(cat classpath.txt)" GenCases ../derived-schema

`make_classpath.sh` writes an untracked `classpath.txt` containing local checkout/cache paths;
`cp.init.gradle` supplies extra runtime dependencies. Each written plan is read back and its
schema derived again. `probe/reverify.sh` runs all generators; `GenCases` covers only its subset.
`Repro186.java` is a separate set-nullability reproducer, not a corpus generator.

`Tables.java` defines shared named-table schemas; engine probes register the same tables and
rows. This keeps schema cases separate from virtual-table support. `GenSetData` and the two
window-bound cases instead embed rows because those rows are what they test.

`probe/to_virtual_tables.py` writes `derived-schema-virtual-tables/` for Gluten, which does not
read named tables. `probe/vt_equivalence.sh` checks its schemas against the canonical corpus.

`make_manifest.sh` runs generators separately and builds `derived-schema/manifest.json`, joining
generator identity, notes and expectations. `make_manifest.py` explicitly pairs printed labels
with filenames and rejects an unpaired case. `sources.json` is the hand-written issue attribution;
add an entry only when the case exercises the behaviour changed by that issue.
