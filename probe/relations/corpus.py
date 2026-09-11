"""Reads a compiled case and renders what a participant is asked for, in the corpus's own notation.

A bundle is a serialized substrait.test.RelationTestCase. Reading one needs protobuf bindings and
nothing else, which is a property of the corpus rather than a convenience: a consumer that had to
run the YAML compiler to obtain a case would be testing this repository's tooling alongside its own
library. So nothing here imports tests/relations/lib, and the type and literal spellings below are a
second implementation of the ones lib/lower.py parses rather than a call into it. The two are held
together by probe/relations/expected.py, which renders every committed bundle through this file:
a spelling that drifted from the authoring side shows up there as a changed expectation.

Every participant answers in its own vocabulary - substrait-go prints `boolean?`, substrait-java
prints `I64{nullable=false}`, DuckDB prints `BIGINT`. A column records the answer in the notation
the cases are written in, so that two columns can be read side by side and a comparison needs no
per-participant parser. Translating is each runner's job and happens before the answer is a column.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BINDINGS = os.path.join(ROOT, "tests", "relations", ".bindings")
if os.path.isdir(_BINDINGS) and _BINDINGS not in sys.path:
    sys.path.insert(0, _BINDINGS)

from substrait.test import relation_test_pb2 as rt  # noqa: E402
from substrait.type_pb2 import Type  # noqa: E402

BUNDLES = os.path.join(ROOT, "tests", "relations", "bundles")

# What each kind means for a column. KIND_POSITIVE is the only kind that carries an expectation, so
# it is the only kind a verdict can be formed about; the rest are recorded and never scored. The
# marker is written into the column itself rather than left to a reader who knows the corpus,
# because a column that scores every case when only some of them carry an expectation flatters
# whoever is reading it.
SCORED, OBSERVED = "score", "observe"
KIND_MARK = {
    rt.RelationTestCase.KIND_POSITIVE: SCORED,
    rt.RelationTestCase.KIND_INVALID_PLAN: OBSERVED,
    rt.RelationTestCase.KIND_UNRESOLVED: OBSERVED,
}
KIND_NAME = {
    rt.RelationTestCase.KIND_UNSPECIFIED: "KIND_UNSPECIFIED",
    rt.RelationTestCase.KIND_POSITIVE: "KIND_POSITIVE",
    rt.RelationTestCase.KIND_INVALID_PLAN: "KIND_INVALID_PLAN",
    rt.RelationTestCase.KIND_UNRESOLVED: "KIND_UNRESOLVED",
}

_PARAM_LEN = ("varchar", "fixed_char", "fixed_binary")
_PARAM_PREC = ("precision_timestamp", "precision_time", "interval_day")
_SHORT = {"fixed_char": "fixedchar", "fixed_binary": "fixedbinary"}


def render_type(t, nullability=True, names=None):
    """`i64`, `i64?`, `decimal<11,2>`, `struct<x:i64, y:string>` - the spelling a case is written in.

    `nullability=False` drops the marker for a participant whose type system has none. Such an
    answer is not "required": it is silent about nullability, and the column's head says so.

    `names` is the flat, depth-first list of column names a NamedStruct carries, and a struct type
    consumes one entry per field from the front of it. Pairing names with top-level types instead
    was wrong the moment a column was a struct: the names after it all shifted by one, and the
    cases under names/ are there to catch exactly that.
    """
    kind = t.WhichOneof("kind")
    if kind is None:
        return "?"
    sub = getattr(t, kind)
    if kind == "struct":
        q = "?" if nullability and sub.nullability == Type.NULLABILITY_NULLABLE else ""
        members = []
        for member in sub.types:
            name = names.pop(0) if names else "?"
            members.append("%s:%s" % (name, render_type(member, nullability, names)))
        return "struct<%s>%s" % (", ".join(members), q)
    q = "?" if nullability and sub.nullability == Type.NULLABILITY_NULLABLE else ""
    name = _SHORT.get(kind, kind)
    if kind == "decimal":
        return "%s<%d,%d>%s" % (name, sub.precision, sub.scale, q)
    if kind in _PARAM_LEN:
        return "%s<%d>%s" % (name, sub.length, q)
    if kind in _PARAM_PREC:
        return "%s<%d>%s" % (name, sub.precision, q)
    return name + q


def render_schema(names, types, nullability=True):
    """`[a:i64, b:i64?]`. A type without a name is not silently dropped: the count is the answer.

    A participant may return more types than root names or the other way round - substrait-go
    refuses several cases on exactly that mismatch - so an unnamed column is rendered `?:i64`
    rather than left out, and a name left over after every type is rendered `<name>:?`.

    The names are consumed from the front rather than indexed, because a struct column takes one
    name per field and everything after it moves.
    """
    pending = list(names)
    cols = []
    for t in types:
        name = pending.pop(0) if pending else "?"
        cols.append("%s:%s" % (name, render_type(t, nullability, pending)))
    for leftover in pending:
        cols.append("%s:?" % leftover)
    return "[%s]" % ", ".join(cols)


def render_named_struct(ns, nullability=True):
    return render_schema(list(ns.names), list(ns.struct.types), nullability)


def render_value(v):
    """One cell of a row, as text. Engines answer in their host language's values, not in literals,
    so a row observation is compared as text and this is the only place that decides its spelling.

    A date and a timestamp reach here as the host's own date and datetime, from an engine and from
    literal_value alike, so the two sides compare without either knowing how the other stores them.
    """
    import datetime
    import decimal

    if v is None:
        return "null"
    if isinstance(v, datetime.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return "'%s'" % v
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, decimal.Decimal):
        return format(v, "f")
    if isinstance(v, float):
        return repr(v)
    return str(v)


def in_sequence(case):
    """Whether the case fixes the order of its rows: ORDER_SEQUENCE, which the sort and fetch cases
    declare because a sort sets which row comes first and a fetch keeps it."""
    return (case.expect.HasField("rows")
            and case.expect.rows.order == rt.RelationTestCase.RowSet.ORDER_SEQUENCE)


def render_rows(rows, sequence=False):
    """`(1, null) (2, 2)`: in the order given where the case fixes one, sorted where it does not.

    Most cases declare ORDER_MULTISET - the relation rules fix no order - so the sequence a run
    happens to return is not the observation, and the rows are sorted by their rendered text, which
    keeps a row of mixed types comparable at all. Under ORDER_SEQUENCE the order is the observation,
    and sorting it away would let a sort that ignores where nulls go pass.
    """
    rendered = ["(%s)" % ", ".join(render_value(v) for v in r) for r in rows]
    return " ".join(rendered if sequence else sorted(rendered))


EPOCH = None  # filled in on first use; see literal_value


def literal_value(lit):
    """A substrait literal as a host value, so an expectation and an engine's answer compare.

    The temporal kinds are the ones that cannot be handed over as they are stored. A date is a
    count of days and a precision_timestamp is a count of sub-second units, and returning either
    number would compare a schema-shaped integer against the date an engine actually returned -
    or, for the timestamp, print the protobuf message itself into the column.
    """
    import datetime
    import decimal

    global EPOCH
    if EPOCH is None:
        EPOCH = datetime.datetime(1970, 1, 1)

    kind = lit.WhichOneof("literal_type")
    if kind is None or kind == "null":
        return None
    if kind == "decimal":
        unscaled = int.from_bytes(lit.decimal.value, "little", signed=True)
        with decimal.localcontext() as ctx:
            ctx.prec = 60
            return decimal.Decimal(unscaled).scaleb(-lit.decimal.scale)
    if kind == "date":
        return (EPOCH + datetime.timedelta(days=lit.date)).date()
    if kind == "precision_timestamp":
        precision = lit.precision_timestamp.precision
        value = lit.precision_timestamp.value
        if precision > 6:
            # datetime stops at microseconds; a finer literal would be silently rounded, and a
            # rounded expectation is worse than none.
            raise ValueError("precision_timestamp<%d> is finer than a datetime holds" % precision)
        seconds, fraction = divmod(value, 10 ** precision) if precision else (value, 0)
        return EPOCH + datetime.timedelta(seconds=seconds,
                                          microseconds=fraction * 10 ** (6 - precision))
    return getattr(lit, kind)


def expected_rows(case):
    if not case.expect.HasField("rows"):
        return None
    return [[literal_value(f) for f in s.fields] for s in case.expect.rows.values]


def bundle_paths(args=None):
    """Every committed bundle, or the ones named on the command line.

    Sorted by case id rather than by path so that two participants' columns list the cases in the
    same order whatever the shell handed them.
    """
    if args:
        paths = list(args)
    else:
        paths = []
        for dirpath, _, files in os.walk(BUNDLES):
            paths += [os.path.join(dirpath, f) for f in files if f.endswith(".pb")]
    return sorted(paths, key=lambda p: read(p).id)


def read(path):
    case = rt.RelationTestCase()
    with open(path, "rb") as fh:
        case.ParseFromString(fh.read())
    return case
