# What shape a producer writes

Four producers compile the SQL in `queries.tsv`, and their plans are passed to consumers.
This checks whether shapes exposing corpus divergences occur in plans produced from real SQL.

    DF_VENV=<venv> bash probe/producer-shapes/run_all.sh [out] [queries.tsv]
    PLANS=<out> DF_VENV=<venv> bash probe/producer-shapes/cross_consume.sh duckdb/mask_reorder ...

`run_all.sh` writes `<out>/<producer>/<query>.pb` beside a `.json` of the same plan, or a `.err`
holding the refusal, and prints one line per plan: the relation kinds, which relations carry `emit`,
every read projection mask, the Fetch and VirtualTable encodings, grouping sets, aggregate phases
and declared output types, timestamp-literal precisions, scalar-function options and whether
extensions are declared by URN. Fields the spec has removed are read as unknown fields and named, so
a producer still writing one is visible rather than absent. `cross_consume.sh` prints what
substrait-go, substrait-python, the validator, substrait-java, DuckDB and DataFusion make of a
chosen plan, each in one process, to isolate crashes.

The tables are the corpus's shared ones — `t_rn (c0 required, c1 nullable)`, `t_nr` the other way
round, `t_mix (i64, string, bool)` — plus `t_ts` and `t_dec`; `consume_engines.py` fills them with
rows, and `duckdb_shapes.py` gives its producer the same rows, because DuckDB optimizes with the
statistics of the tables it holds and over empty ones writes an empty virtual table instead of the
plan.

DuckDB, Isthmus and Spark come from the probe environment and `SUBSTRAIT_JAVA_DIR`, at the versions
in `probe/versions.env`. DataFusion is the one participant with no producer there, so `DF_VENV`
points at a virtualenv holding its package (`pip install datafusion==54.0.0` is what these notes
were taken with). None of this is a column: it records what a producer writes, not how a participant
answers the corpus, and nothing it produces is tracked.
