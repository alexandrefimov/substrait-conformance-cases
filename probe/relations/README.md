# Measuring the relation corpus

The cases in `tests/relations/` are compiled to bundles. This directory puts them through
implementations and saves one column per participant under `results/relations/`. The generated
schema corpus is measured separately, and its columns are `results/<NAME>.txt`, one directory up.

## Saved results

substrait-java answers 58 of the 63 scored cases and refuses 5. substrait-go
refuses 21, eight of them the set operations, whose inputs it requires to agree on a nullability
these cases deliberately vary. DuckDB and DataFusion execute, so they are the two measured against
the rows that 47 of the cases assert. DuckDB's 11 divergences all show in the schema, five of them
in the rows as well, and so do DataFusion's 3, two of them in the rows: so far the rows have
confirmed an answer rather than caught one. Both reach the rows of 31 cases and return the same rows
on 26. The other five are the emit cases, where DataFusion returns the rows the case asserts and
DuckDB does not. The hatched cells are substrait-java and substrait-go agreeing about a schema and
never seeing the rows. Eight cases carry no expectation on purpose and are never scored.

## Running one participant

From the repository root:

```sh
bash probe/relations/setup.sh GO                        # build it at the pinned versions
bash probe/relations/go_all.sh > results/relations/GO.txt
python3 probe/relations/check_column.py results/relations/GO.txt --cases
bash probe/relations/replay.sh GO                       # from nothing, and the saved answers back
```

Participants are `DUCKDB`, `GO`, `JAVA` and `DATAFUSION`; setup without an argument builds all.
Each needs python3 and protoc. Go needs the pinned toolchain, Java JDK 17 and
`SUBSTRAIT_JAVA_DIR`, and DataFusion cargo and `DF_DIR`. `probe/setup.sh` clones missing Java
and DataFusion checkouts at their pins; Gradle resolution and the Rust build dominate setup.

`replay.sh` builds a fresh pinned environment, checks its identity and compares every saved
answer. `LATEST=1` uses `versions-latest.env` in a separate environment and reports changed
answers without failing on differences. Weekly drift jobs prepare observations for
`results/DRIFT.txt` under `relations/<NAME>`.

The [Gluten diagnostic](gluten/README.md) observes native schemas and executed rows separately;
it is not a saved column and does not update this matrix.

## Reading a column

```
score   join/left/output-nullability     [a0:i64, a1:i64?, b0:i64?, b1:i64?] rows (1, null, null, null) (2, 2, 2, 20)
observe read/projection/mask-reorders    [first:bool, second:i64]
score   set/union_distinct/output-nullability   CRASH: the probe process died, exit 139
```

Each line has a mark, case id and answer. `score` is a positive case with an expectation;
`observe` is invalid or unresolved and unscored. Executing participants include asserted rows.
`ERROR:` is a refusal; `CRASH:` is a terminated probe process. The header records date, versions
and comparison limits.

DuckDB types lack nullability, so comparisons drop those markers. Java and Go derive schemas
without rows and cannot distinguish the identical schemas of physical right semi and right anti.
DataFusion compares types, nullability and rows but, like DuckDB, refuses physical join messages
in these measurements. None of these columns therefore distinguishes that pair yet.

Rows are multisets unless a sort/fetch case declares `ORDER_SEQUENCE`, where order is checked.

## When the corpus changes

Columns fingerprint the corpus they answered. Editing a case makes `check_column.py` refuse
those stale measurements. Retake explicitly:

```sh
bash probe/relations/retake.sh          # or: retake.sh GO JAVA
```

This regenerates the extract, runs participants and redraws pages and pictures. It also names
stale reasons and prose counts requiring manual edits. Review the generated diff before committing.

## When something does not match

`check_column.py --cases` lists matched, differing, unsupported and observed cases. A differing
answer is a measurement, not a broken run, and needs a tested reason in
`results/relations/differed.json`. Shared causes link the schema corpus's reason id with `same_as`.

A replay against a different build is not reproduction: retake its column together with the
pin. Changed answers at the same build require investigation of harness changes.

## Adding a participant

Add capabilities to `participants.py`, a runner producing `<case id><TAB><answer>` per bundle,
an `<name>_all.sh` that calls `drive.sh`, and entries in setup, replay and retake. Add the column
to `picture.py`, both workflows' relation matrices and the drift-artifact collection loop.
Self-check compares workflow participants with replay and the page with capabilities; it does
not check the retake participant list.

Runners must read `bundles/*.pb`, not YAML sources or `tests/relations/lib/`. Translate native
types into corpus notation before assembling the column, including `boolean?` to `bool?`.

## The pieces

| | |
| --- | --- |
| `corpus.py` | reads a bundle and renders types, schemas and rows in the corpus's notation |
| `expected.py` | writes `results/relations/expected.json`, the extract: what each bundle asks for, as text, with the SHA-256 of the file it came from |
| `participants.py` | who is measured and how far each can be read |
| `duckdb_one.py`, `go/main.go`, `java/RelationCase.java`, `datafusion/main.rs` | one participant, answering for one bundle |
| `drive.sh` | runs a participant over every bundle, one process per case |
| `column.py` | assembles a column and refuses one that is not whole |
| `check_column.py` | scores a saved column |
| `check_differed.py` | checks that every differing cell has a reason and that the reason still describes it |
| `retake.sh` | the whole measurement again, after the corpus has changed |

The extract lets self-check run with python3 alone; hashes tie it to bundles. `expected.py --check`
re-renders bundles to check notation as well, and replay runs it when the Python environment exists.

Java's generated bindings need a runtime at least as new as protoc. Setup puts the pinned
protobuf runtime ahead on this runner's classpath without changing Java's own build.
DataFusion's standalone runner needs its own binding build script and uses the checkout's
lockfile/toolchain. Setup reads the matching prost version from that checkout.
