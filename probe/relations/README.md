# Measuring the relation corpus

The 39 cases in `tests/relations/` are compiled to bundles. This directory puts them through
implementations and saves one column per participant under `results/relations/`. The 98-plan
corpus is measured separately, and its columns are `results/<NAME>.txt`, one directory up.

## Running one participant

```sh
bash probe/relations/setup.sh GO                        # build it at the pinned versions
bash probe/relations/go_all.sh > results/relations/GO.txt
python3 probe/relations/check_column.py results/relations/GO.txt --cases
bash probe/relations/replay.sh GO                       # from nothing, and the saved answers back
```

From the repository root. The participants are `DUCKDB`, `GO` and `JAVA`; `setup.sh` with no
argument builds all three. Each needs `python3` and `protoc`; `GO` also the Go toolchain
`probe/versions.env` names, and `JAVA` a JDK 17 and `SUBSTRAIT_JAVA_DIR` pointed at a substrait-java
checkout — `probe/setup.sh`, which builds the other corpus's environment, clones one at the pinned
commit if you have none. `JAVA` resolves its classpath through Gradle, which is the slow part of a
first run; the other two are a `go build` and a `pip install`.

`replay.sh` is the one to trust: it builds the participant from nothing and requires the saved
column back answer for answer, refusing first if what it measured is not what that column names.
`LATEST=1` asks the other question, whether the participant has moved since: it builds today's
release through `probe/versions-latest.env`, in an environment of its own, and names the cases that
moved without failing on them. `.github/workflows/drift.yml` runs that weekly for all three and
writes what it finds into `results/DRIFT.txt` under `relations/<NAME>`.

## Reading a column

```
score   join/left/output-nullability     [a0:i64, a1:i64?, b0:i64?, b1:i64?] rows (1, null, null, null) (2, 2, 2, 20)
observe read/projection/mask-reorders    [first:bool, second:i64]
score   set/union_distinct/output-nullability   CRASH: the probe process died, exit 139
```

A mark, the case id, and the answer: a schema in the notation the cases are written in, the rows
after it for the 26 cases that declare rows when the participant executes, `ERROR:` when the plan
was refused, `CRASH:` when it took the process down — which four of the eight set operations do to
DuckDB at 1.5.5.

`score` is a `KIND_POSITIVE` case, the only kind carrying an expectation. `observe` is
`KIND_INVALID_PLAN` or `KIND_UNRESOLVED` — 4 of the 39 — which ship without one on purpose and are
recorded, never scored. Without the mark a column reads as 39 answers all of which could be right.

The head names the day, the versions, and how far this participant can be read, and that last part
is load-bearing. DuckDB's logical types carry no nullability, so both sides are compared with the
markers dropped, and **a divergence only about nullability cannot appear in the DuckDB column at
all**. substrait-go and substrait-java derive schemas without executing, so their columns answer no
rows — and `join_physical/hash_right_semi` and `hash_right_anti` emit the same columns with the same
nullability, so those two are one case to them. `check_column.py` says that rather than counting two
agreements which rest on one answer.

## When the corpus changes

Every saved column carries a fingerprint over the corpus it answered, so a case added or edited
makes `check_column.py` refuse to score any of them rather than compare one set of cases against
another. Retaking is one command:

```sh
bash probe/relations/retake.sh          # or: retake.sh GO JAVA
```

It regenerates the extract, runs each participant, redraws the pictures and the page, and ends by
naming what a script cannot write: the reasons that no longer describe their cells, and the
sentences whose numbers have moved. Nothing it writes is committed for you.

## When something does not match

`check_column.py` prints the counts, and with `--cases` every case under `matched`, `differed`,
`unsupported` and `observed`. A `differed` case is a finding about the participant, not a broken
run — and it needs a reason in `results/relations/differed.json` before the self-check will pass.
`replay.sh` failing on a different build means the pin in `probe/versions.env` and the saved column
have come apart: the new column is what gets committed, with its pin updated beside it. Failing on
the same build with different answers is this harness having changed, and the cases it names are
where.

Each reason carries a test of an output property, so a judgement that has stopped describing the
answer fails rather than sitting there. Where the cause is one the 98-case corpus already records,
the reason keeps that file's id under `same_as` instead of restating it: one engine should not get
two stories. Five of the nine do, which is the relation cases reaching the same defects along
different plans — the emit mapping on four relations that corpus does not reach, among them.

## Adding a participant

An entry in `participants.py` saying how far it can be read, a runner printing
`<case id><TAB><answer>` for one bundle, an `<name>_all.sh` that finds its version and calls
`drive.sh`, and a case in `setup.sh` and `replay.sh`.

Two rules the runner is held to. It opens `bundles/*.pb` and never `cases/*.yaml` or
`tests/relations/lib/` — a bundle is a serialized `substrait.test.RelationTestCase`, reading one
takes protobuf bindings and nothing else, and that claim of the corpus stops being tested the moment
a runner needs the authoring parser. And it translates into the notation the cases use before its
answers become a column, since substrait-go prints `boolean?` where a case says `bool?`.

## The pieces

| | |
| --- | --- |
| `corpus.py` | reads a bundle and renders types, schemas and rows in the corpus's notation |
| `expected.py` | writes `results/relations/expected.json`, the extract: what each bundle asks for, as text, with the SHA-256 of the file it came from |
| `participants.py` | who is measured and how far each can be read |
| `duckdb_one.py`, `go/main.go`, `java/RelationCase.java` | one participant, answering for one bundle |
| `drive.sh` | runs a participant over every bundle, one process per case |
| `column.py` | assembles a column and refuses one that is not whole |
| `check_column.py` | scores a saved column |
| `check_differed.py` | checks that every differing cell has a reason and that the reason still describes it |
| `retake.sh` | the whole measurement again, after the corpus has changed |

The extract exists because a bundle is protobuf and `probe/selfcheck.sh` needs python3 and nothing
else. That gate ties the two by hash only; `expected.py --check` re-renders the bundles, which is
what would catch `corpus.py` and the authoring side spelling a type differently, and `replay.sh`
runs it whenever the Python environment is there.

One thing about substrait-java is worth knowing before its build fails: the generated bindings need
a protobuf runtime at least as new as the protoc that wrote them, and substrait-java resolves one a
release older. `setup.sh` resolves the runtime `versions.env` names through Gradle, into the same
cache the rest of that classpath comes from, and puts it ahead on this runner's classpath alone.
