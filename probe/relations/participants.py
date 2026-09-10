"""Who is measured on the relations corpus, and how far each of them can be read.

Two files need this and they must not disagree: probe/relations/column.py writes the boundary into
the head of a saved column, and probe/relations/check_column.py decides what a comparison is
entitled to compare. Kept in one place, because a boundary written in prose in one file and encoded
as a flag in another is how a column comes to claim more than it measured.

A boundary is not a defect and not an excuse. `nullability: False` says the participant's type
system carries none, so its answer is silent about nullability rather than asserting that every
column is required. `executes: False` says the participant derives a schema and never runs a plan,
so it has not disagreed about rows - it has not looked, and the two cases that differ only in their
rows are one case to it.

Needs python3 and nothing else, like everything else the self-check reaches.
"""

PARTICIPANTS = {
    "JAVA": {
        "label": "substrait-java",
        "nullability": True,
        "names": True,
        "executes": False,
        "boundary": [
            "BOUNDARY: substrait-java derives a schema and does not execute, so every case here is"
            " answered on its schema alone, including the 26 that declare rows.",
        ],
    },
    "GO": {
        "label": "substrait-go",
        "nullability": True,
        "names": True,
        "executes": False,
        "boundary": [
            "BOUNDARY: substrait-go derives a schema and does not execute, so every case here is"
            " answered on its schema alone, including the 26 that declare rows.",
        ],
    },
    "DUCKDB": {
        "label": "DuckDB",
        "nullability": False,
        "names": True,
        "executes": True,
        "boundary": [
            "BOUNDARY: DuckDB's logical types carry no nullability, so no answer below carries"
            " `?`; names, types, arity and order are what a `score` line is compared on.",
            "It executes, so a case that declares rows is answered with rows too, unless the"
            " plan was refused before it ran.",
        ],
    },
}


def participant(name):
    if name not in PARTICIPANTS:
        raise KeyError("%s is not a relations participant; add it to probe/relations/participants.py"
                       % name)
    return PARTICIPANTS[name]
