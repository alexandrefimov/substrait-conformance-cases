"""One case through Acero (pyarrow.substrait.run_query). A separate process per case.

Acero accepts binary protobuf only (the .bin next to each .json, written by JsonToBin).
"""
import pathlib, re, sys
import decimal
import pyarrow as pa
import pyarrow.substrait as ps

# protobuf varies this marker, and the run of spaces after it, between runs on purpose, so that debug
# output is not parsed as data. The message is truncated below, so the varying length shifts the cut
# and the saved column changes on every run for a reason unrelated to the measurement. Collapsed here,
# before the truncation.
REDACTION = re.compile(r"goo\.gle/debug\w*\s+")

def message(e):
    return REDACTION.sub("goo.gle/debug ", str(e).replace("\n", " "))

SCHEMAS = {
    "foo": pa.schema([pa.field("a", pa.int64(), nullable=False),
                      pa.field("b", pa.int64(), nullable=False),
                      pa.field("c", pa.string(), nullable=False)]),
    "SRC1": pa.schema([pa.field("INTCOL", pa.int32()), pa.field("CHARCOL", pa.string())]),
    "t_mix": pa.schema([pa.field("c0", pa.int64(), nullable=False),
                       pa.field("c1", pa.string(), nullable=False),
                       pa.field("c2", pa.bool_(), nullable=False)]),
    "t_dec": pa.schema([pa.field("c0", pa.decimal128(10, 2), nullable=False),
                       pa.field("c1", pa.decimal128(5, 1), nullable=False),
                       pa.field("c2", pa.decimal128(38, 10), nullable=False),
                       pa.field("c3", pa.decimal128(38, 10), nullable=False)]),
    "t_str": pa.schema([pa.field("c0", pa.string(), nullable=False),
                       pa.field("c1", pa.string(), nullable=False),
                       pa.field("c2", pa.binary(), nullable=False),
                       pa.field("c3", pa.string(), nullable=False)]),
    "t_avg": pa.schema([pa.field("c0", pa.int64(), nullable=False),
                       pa.field("c1", pa.int64(), nullable=False)]),
    "t_rn": pa.schema([pa.field("c0", pa.int64(), nullable=False), pa.field("c1", pa.int64(), nullable=True)]),
    "t_nr": pa.schema([pa.field("c0", pa.int64(), nullable=True), pa.field("c1", pa.int64(), nullable=False)]),
    "s1": pa.schema([pa.field("c0", pa.int64(), nullable=False), pa.field("c1", pa.int64(), nullable=False), pa.field("c2", pa.int64(), nullable=False), pa.field("c3", pa.int64(), nullable=False), pa.field("c4", pa.int64(), nullable=True), pa.field("c5", pa.int64(), nullable=True), pa.field("c6", pa.int64(), nullable=True), pa.field("c7", pa.int64(), nullable=True)]),
    "s2": pa.schema([pa.field("c0", pa.int64(), nullable=False), pa.field("c1", pa.int64(), nullable=False), pa.field("c2", pa.int64(), nullable=True), pa.field("c3", pa.int64(), nullable=True), pa.field("c4", pa.int64(), nullable=False), pa.field("c5", pa.int64(), nullable=False), pa.field("c6", pa.int64(), nullable=True), pa.field("c7", pa.int64(), nullable=True)]),
    "s3": pa.schema([pa.field("c0", pa.int64(), nullable=False), pa.field("c1", pa.int64(), nullable=True), pa.field("c2", pa.int64(), nullable=False), pa.field("c3", pa.int64(), nullable=True), pa.field("c4", pa.int64(), nullable=False), pa.field("c5", pa.int64(), nullable=True), pa.field("c6", pa.int64(), nullable=False), pa.field("c7", pa.int64(), nullable=True)]),
    "t_xnull": pa.schema([pa.field("c0", pa.int64(), nullable=True)]),
}


def provider(names, schema=None):
    key = names[-1] if names else None
    s = SCHEMAS.get(key)
    if s is None:
        raise KeyError("no such table %r" % (names,))
    # The callback schema is the decoded ReadRel.base_schema. Preserve its types
    # when materializing the synthetic input, including Arrow extension types.
    if schema is not None:
        s = schema
    import decimal as _d
    _big = _d.Decimal("9999999999999999999999999999.9999999999")
    rows = {"t_mix": {"c0": [10], "c1": ["x"], "c2": [True]},
            "t_avg": {"c0": [1, 2], "c1": [10, 20]},
            "t_dec": {"c0": [_d.Decimal("1.00")], "c1": [_d.Decimal("3.0")],
                      "c2": [_big], "c3": [_big]}}.get(key)
    if rows:
        return pa.table({f.name: pa.array(rows[f.name], type=f.type) for f in s}, schema=s)
    return pa.table({f.name: pa.array([], type=f.type) for f in s}, schema=s)


plan = pathlib.Path(sys.argv[1]).read_bytes()
try:
    reader = ps.run_query(pa.py_buffer(plan), table_provider=provider)
    tbl = reader.read_all()
    cols = ["%s:%s%s" % (f.name, f.type, "?" if f.nullable else "") for f in tbl.schema]
    print("ACERO ACCEPTED   [%s]" % ", ".join(cols))
    if tbl.num_rows:
        print("ACERO ROW        %r" % (tbl.slice(0, 1).to_pylist()[0],))
        if tbl.num_columns == 1:
            nm = tbl.schema[0].name
            vals = sorted(r[nm] for r in tbl.to_pylist())
            print("ACERO ROWS       %s" % (vals if len(vals) <= 30 else vals[:30] + ["..."],))
except Exception as e:
    print("ACERO REJECTED   %s: %s" % (type(e).__name__, message(e)[:150]))
