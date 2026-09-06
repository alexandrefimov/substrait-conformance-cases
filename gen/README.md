# Case generators: plan -> derived schema

The cases are built with the same builders as the tests of the merged substrait-java fixes they come
from, so the expected schema is produced mechanically rather than retyped by hand.

Running them:

    SUBSTRAIT_JAVA_DIR=<substrait-java checkout> bash make_classpath.sh
    javac -cp "$(cat classpath.txt)" -d out *.java
    java  -cp "out:$(cat classpath.txt)" GenCases ../derived-schema

`classpath.txt` is generated, not checked in: every entry is an absolute path into one machine's
checkout and Gradle cache. `make_classpath.sh` writes it and `cp.init.gradle` explains which extras
it adds to `:core`'s runtime classpath and why.

Every case is read back from disk after it is written and its schema derived again: a case is a
file, not an object in memory.

The leaves are named tables with schemas shared by every case (`Tables.java`), and every engine probe
creates the same tables with the same rows. A leaf has to be a control: put a virtual table there and
the run is also measuring support for virtual tables, at which point a divergence in derivation can
no longer be told apart from a lack of support. The exception is `GenSetData`, whose cases carry
their rows inside the plan because the spec's set-operation examples are about the rows.
`../derived-schema-virtual-tables/` is a whole-corpus rewrite into virtual tables, built by
`probe/to_virtual_tables.py`, and exists only because Gluten does not read `named_table` at all;
`probe/vt_equivalence.sh` checks that it derives the same schemas as the canonical corpus.

`probe/reverify.sh` runs all of the generators; `GenCases` alone covers only its own part of the
corpus. `Repro186.java` is not one of them: it reproduces a known substrait-java issue about
converting a `SetRel` whose inputs differ in nullability, and is kept here because it is built from
the same tables.

`make_manifest.sh` runs each generator into a directory of its own and turns the result into
`../derived-schema/manifest.json`: per case, the generator that writes it, the line that generator
prints for it, and its expectation. The pairing of a printed line to a case is spelled out in
`make_manifest.py` rather than guessed, and the script fails if one case is left without a line. The
only hand-written input is `sources.json`, the issue a case came from.

A case earns an entry there only when it exercises what that change actually changed, checked against
the change itself rather than against its title. Of eight merged substrait-java fixes read for this,
one produced a new entry. One of the seven is worth naming: `stringlen_declared` looked like a match
for the fix that stopped character lengths being capped, and is not one, because that cap sat at
65536 and the case declares `varchar(10)`. A wrong attribution here is worse than a missing one.
