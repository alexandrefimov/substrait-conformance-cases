"""One relation case through DuckDB's Substrait extension.

    .probe-env/relvenv/bin/python probe/relations/duckdb_one.py <bundle.pb>

Prints one line, `<case id><TAB><answer>`, which probe/relations/column.py turns into a column.
One case per process because the extension takes a signal on some plans - four of the eight set
operations segfault at 1.5.5 - and a case that kills the process must be that case's answer rather
than the end of the run.

DuckDB executes, so it answers with rows as well as with types, and it is so far the only
participant that can tell join_physical/hash_right_semi from hash_right_anti: the two emit the same
columns with the same nullability and differ only in which rows come out. Against that, its logical
types carry no nullability at all, so the schema it reports is silent about it rather than asserting
required - probe/relations/column.py writes that boundary into the head of the column.

The case's own fixtures are created as real tables with exactly the declared types, and a plan whose
base_schema disagrees with the fixture is refused here rather than run: an engine answering about a
different input schema is not answering this case.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus  # noqa: E402

import duckdb  # noqa: E402
from google.protobuf import json_format  # noqa: E402

# The corpus notation on the left, DuckDB's SQL spelling on the right. Only the types the cases
# actually use are here: an unmapped one stops the case rather than being approximated, because a
# fixture created as a wider type would make the answer be about a plan nobody wrote.
SQL = {"i8": "TINYINT", "i16": "SMALLINT", "i32": "INTEGER", "i64": "BIGINT",
       "bool": "BOOLEAN", "string": "VARCHAR", "fp32": "FLOAT", "fp64": "DOUBLE",
       "date": "DATE", "binary": "BLOB"}
# Back the other way, for what DESCRIBE reports.
CORPUS = {"TINYINT": "i8", "SMALLINT": "i16", "INTEGER": "i32", "BIGINT": "i64",
          "BOOLEAN": "bool", "VARCHAR": "string", "FLOAT": "fp32", "DOUBLE": "fp64",
          "DATE": "date", "BLOB": "binary", "HUGEINT": "i128"}


class Unbindable(Exception):
    """The harness cannot put this case to DuckDB at all. Not a finding about DuckDB."""


def sql_type(t):
    kind = t.WhichOneof("kind")
    if kind == "decimal":
        return "DECIMAL(%d,%d)" % (t.decimal.precision, t.decimal.scale)
    if kind not in SQL:
        raise Unbindable("no DuckDB type for %s" % corpus.render_type(t))
    return SQL[kind]


def corpus_type(sql):
    """DuckDB's reported type in the corpus's notation. An unknown one is passed through lowercased
    rather than dropped, so a column that meets a type this table has never seen still shows it."""
    name = str(sql).upper()
    if name.startswith("DECIMAL"):
        return name.lower().replace(" ", "").replace("(", "<").replace(")", ">")
    return CORPUS.get(name, name.lower())


def bind(con, case):
    """Create the case's fixtures, and refuse a plan that declares a different input schema."""
    declared = {}
    for table in case.tables:
        name = ".".join(table.name)
        declared[name] = table.schema
        cols = ", ".join(
            "%s %s%s" % (n, sql_type(t), "" if t_nullable(t) else " NOT NULL")
            for n, t in zip(table.schema.names, table.schema.struct.types))
        con.execute('CREATE TABLE "%s" (%s)' % (name, cols))
        for row in table.rows:
            values = [corpus.literal_value(f) for f in row.fields]
            con.execute('INSERT INTO "%s" VALUES (%s)' % (name, ", ".join("?" * len(values))), values)

    def walk(rel):
        which = rel.WhichOneof("rel_type")
        if which is None:
            return
        if which == "read" and rel.read.HasField("named_table"):
            key = ".".join(rel.read.named_table.names)
            if key not in declared:
                raise Unbindable('plan reads table "%s", which the case does not bind' % key)
            want = declared[key].SerializeToString(deterministic=True)
            if want != rel.read.base_schema.SerializeToString(deterministic=True):
                raise Unbindable('table "%s": the fixture schema is not the plan\'s base_schema' % key)
        for field, value in getattr(rel, which).ListFields():
            if field.message_type is not None and field.message_type.full_name == "substrait.Rel":
                for item in (value if field.is_repeated else [value]):
                    walk(item)

    for pr in case.plan.relations:
        walk(pr.root.input if pr.HasField("root") else pr.rel)


def t_nullable(t):
    kind = t.WhichOneof("kind")
    return kind is not None and getattr(t, kind).nullability == 1  # NULLABILITY_NULLABLE


def answer(case):
    con = duckdb.connect()
    con.execute("LOAD substrait")
    bind(con, case)
    plan_json = json_format.MessageToJson(case.plan)
    try:
        described = con.execute("DESCRIBE SELECT * FROM from_substrait_json(?)", [plan_json]).fetchall()
        rows = con.execute("SELECT * FROM from_substrait_json(?)", [plan_json]).fetchall()
    except Exception as exc:
        return "ERROR: " + str(exc).splitlines()[0].strip()
    # DESCRIBE hands back a name and a type together, so the schema is assembled here rather than
    # through corpus.render_schema, which pairs names with substrait Type messages this side has
    # none of. No `?` ever appears: DuckDB's logical types carry no nullability.
    schema = "[%s]" % ", ".join("%s:%s" % (d[0], corpus_type(d[1])) for d in described)
    if case.expect.HasField("rows"):
        return "%s rows %s" % (schema, corpus.render_rows(rows))
    return schema


def main():
    path = sys.argv[1]
    case = corpus.read(path)
    try:
        line = answer(case)
    except Unbindable as exc:
        line = "HARNESS-ERROR: %s" % exc
    except Exception as exc:                      # a harness fault is not a case result either
        line = "HARNESS-ERROR: %s: %s" % (type(exc).__name__, str(exc).splitlines()[0])
    sys.stdout.write("%s\t%s\n" % (case.id, line))


if __name__ == "__main__":
    main()
