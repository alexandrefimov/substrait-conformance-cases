"""The tables every producer plans against, with their rows, written once and rendered per producer.

They are the corpus's shared tables, as the engine probes in probe/ register them for the consumers
(t_ts is registered there for these plans alone), so a plan written here can be read there.

    python3 producers/tables.py duckdb|isthmus|spark|datafusion

prints one SQL statement per line. The rows matter even to a producer that never executes: DuckDB
optimizes with the statistics of the tables it holds, and over an empty table it proves a filter
empty and writes an empty virtual table instead of the plan. Isthmus plans against a catalog and
takes no rows, so it gets the CREATE statements alone.
"""
import sys

# name, [(column, type, nullable)], rows as SQL literals
TABLES = [
    ("t_rn", [("c0", "BIGINT", False), ("c1", "BIGINT", True)],
     ["(1, 10)", "(2, NULL)", "(3, 30)"]),
    ("t_nr", [("c0", "BIGINT", True), ("c1", "BIGINT", False)],
     ["(NULL, 1)", "(2, 2)", "(3, 30)"]),
    ("t_mix", [("c0", "BIGINT", False), ("c1", "VARCHAR", False), ("c2", "BOOLEAN", False)],
     ["(10, 'x', true)", "(20, 'y', false)"]),
    ("t_ts", [("ts", "TIMESTAMP_NS", False)],
     ["(TIMESTAMP_NS '2021-01-01 00:00:00.123456789')"]),
    ("t_dec", [("c0", "DECIMAL(10,2)", False), ("c1", "DECIMAL(5,1)", False),
               ("c2", "DECIMAL(38,10)", False), ("c3", "DECIMAL(38,10)", False)],
     ["(1.00, 3.0, 9999999999999999999999999999.9999999999, 9999999999999999999999999999.9999999999)"]),
]

# A nanosecond timestamp without a time zone, in each dialect. Spark has no nanoseconds, and its
# plain TIMESTAMP carries a session time zone, so the closest it has is TIMESTAMP_NTZ.
TYPES = {
    "duckdb": {"TIMESTAMP_NS": "TIMESTAMP_NS"},
    "isthmus": {"TIMESTAMP_NS": "TIMESTAMP(9)"},
    "spark": {"TIMESTAMP_NS": "TIMESTAMP_NTZ", "VARCHAR": "STRING"},
    "datafusion": {"TIMESTAMP_NS": "TIMESTAMP"},
}
LITERALS = {
    "duckdb": {"TIMESTAMP_NS '": "TIMESTAMP_NS '"},
    "isthmus": {},
    "spark": {"TIMESTAMP_NS '": "TIMESTAMP_NTZ '"},
    "datafusion": {"TIMESTAMP_NS '": "TIMESTAMP '"},
}


def render(dialect):
    types, literals = TYPES[dialect], LITERALS[dialect]
    out = []
    for name, cols, rows in TABLES:
        defs = ", ".join("%s %s%s" % (c, types.get(t, t), "" if n else " NOT NULL") for c, t, n in cols)
        values = ", ".join(rows)
        for old, new in literals.items():
            values = values.replace(old, new)
        if dialect == "isthmus":
            out.append("CREATE TABLE %s (%s)" % (name, defs))
        elif dialect == "spark":
            out.append("CREATE TABLE %s (%s) USING parquet" % (name, defs))
            out.append("INSERT INTO %s VALUES %s" % (name, values))
        elif dialect == "datafusion":
            out.append("CREATE TABLE %s (%s) AS VALUES %s" % (name, defs, values))
        else:
            out.append("CREATE TABLE %s (%s)" % (name, defs))
            out.append("INSERT INTO %s VALUES %s" % (name, values))
    return out


if __name__ == "__main__":
    print("\n".join(render(sys.argv[1])))
