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
`../derived-schema-vt/` is a whole-corpus rewrite into virtual tables, built by
`probe/to_virtual_tables.py`, and exists only because Gluten does not read `named_table` at all;
`probe/vt_equivalence.sh` checks that it derives the same schemas as the canonical corpus.

`probe/reverify.sh` runs all of the generators; `GenCases` alone covers only its own part of the
corpus.
