// One relation case through DataFusion's Substrait consumer.
//
//     relation_case <bundle.pb>
//
// Prints one line, `<case id><TAB><answer>`, which probe/relations/column.py turns into a column.
// One case per process, as for every participant: a plan that panics the consumer has to be that
// case's answer rather than the end of the run.
//
// The bundle is decoded with bindings prost generated from relation_test.proto, whose Substrait
// messages are the substrait crate's own (build.rs), so the plan handed to the consumer is the
// message the bundle carries, not a copy rebuilt from another representation.
//
// The case's input tables are built here, from the types the case declares, by this file's own
// conversion rather than the consumer's literal reader: through the consumer's, a literal it read
// wrongly would change the input and the answer together and could not show as a difference. A
// plan whose base_schema is not the fixture's is refused before it runs, as the DuckDB runner
// refuses it.
//
// The schema is the one the consumer derives for the logical plan; the rows are what executing it
// returns. Both are written in the notation the cases use, so a column needs no parser of its own.

use std::collections::HashMap;
use std::sync::Arc;

use datafusion::arrow::array::{Array, ArrayRef, AsArray, RecordBatch, new_empty_array};
use datafusion::arrow::datatypes::{
    DataType, Date32Type, Decimal128Type, Field, Fields, Float32Type, Float64Type, Int8Type,
    Int16Type, Int32Type, Int64Type, Schema, TimeUnit, TimestampMicrosecondType,
    TimestampMillisecondType, TimestampNanosecondType, TimestampSecondType, UInt8Type, UInt16Type,
    UInt32Type, UInt64Type,
};
use datafusion::arrow::temporal_conversions::as_datetime;
use datafusion::common::{ScalarValue, TableReference};
use datafusion::datasource::MemTable;
use datafusion::logical_expr::LogicalPlan;
use datafusion::prelude::SessionContext;
use datafusion_substrait::logical_plan::consumer::from_substrait_plan;
use datafusion_substrait::substrait::proto;
use prost::Message;

pub mod substrait_test {
    include!(concat!(env!("OUT_DIR"), "/substrait.test.rs"));
}
use substrait_test::RelationTestCase;

/// The harness cannot put this case to DataFusion at all. Not a finding about DataFusion.
struct Harness(String);

impl From<String> for Harness {
    fn from(why: String) -> Self {
        Harness(why)
    }
}

impl From<&str> for Harness {
    fn from(why: &str) -> Self {
        Harness(why.to_string())
    }
}

/// The name of an enum variant, for a message: `Varchar` rather than the whole value.
fn variant(value: &impl std::fmt::Debug) -> String {
    let text = format!("{value:?}");
    text.split(['(', ' ', '{']).next().unwrap_or("").to_string()
}

fn nullable(nullability: i32) -> bool {
    nullability == proto::r#type::Nullability::Nullable as i32
}

fn time_unit(precision: i32) -> Result<TimeUnit, Harness> {
    // Only the units Arrow has. A case at another precision stops rather than being stored at a
    // neighbouring one, which would make the answer be about a type nobody wrote.
    match precision {
        0 => Ok(TimeUnit::Second),
        3 => Ok(TimeUnit::Millisecond),
        6 => Ok(TimeUnit::Microsecond),
        9 => Ok(TimeUnit::Nanosecond),
        p => Err(format!("no Arrow timestamp of precision {p}").into()),
    }
}

/// One column of a NamedStruct. The names are the flat, depth-first list the NamedStruct carries,
/// and a struct takes one name per field out of it after its own.
fn arrow_field(names: &mut std::slice::Iter<String>, t: &proto::Type) -> Result<Field, Harness> {
    let name = names
        .next()
        .ok_or("the schema has fewer names than columns")?
        .clone();
    let (data_type, is_nullable) = arrow_type(names, t)?;
    Ok(Field::new(name, data_type, is_nullable))
}

fn arrow_type(
    names: &mut std::slice::Iter<String>,
    t: &proto::Type,
) -> Result<(DataType, bool), Harness> {
    use proto::r#type::Kind;
    let kind = t.kind.as_ref().ok_or("a type with no kind")?;
    Ok(match kind {
        Kind::Bool(x) => (DataType::Boolean, nullable(x.nullability)),
        Kind::I8(x) => (DataType::Int8, nullable(x.nullability)),
        Kind::I16(x) => (DataType::Int16, nullable(x.nullability)),
        Kind::I32(x) => (DataType::Int32, nullable(x.nullability)),
        Kind::I64(x) => (DataType::Int64, nullable(x.nullability)),
        Kind::Fp32(x) => (DataType::Float32, nullable(x.nullability)),
        Kind::Fp64(x) => (DataType::Float64, nullable(x.nullability)),
        Kind::String(x) => (DataType::Utf8, nullable(x.nullability)),
        Kind::Binary(x) => (DataType::Binary, nullable(x.nullability)),
        Kind::Date(x) => (DataType::Date32, nullable(x.nullability)),
        Kind::Decimal(x) => (
            DataType::Decimal128(x.precision as u8, x.scale as i8),
            nullable(x.nullability),
        ),
        Kind::PrecisionTimestamp(x) => (
            DataType::Timestamp(time_unit(x.precision)?, None),
            nullable(x.nullability),
        ),
        Kind::Struct(x) => {
            let fields = x
                .types
                .iter()
                .map(|member| arrow_field(names, member))
                .collect::<Result<Vec<_>, _>>()?;
            (
                DataType::Struct(Fields::from(fields)),
                nullable(x.nullability),
            )
        }
        other => return Err(format!("no Arrow type for {}", variant(other)).into()),
    })
}

fn arrow_schema(ns: &proto::NamedStruct) -> Result<Schema, Harness> {
    let st = ns.r#struct.as_ref().ok_or("a schema with no struct")?;
    let mut names = ns.names.iter();
    let fields = st
        .types
        .iter()
        .map(|t| arrow_field(&mut names, t))
        .collect::<Result<Vec<_>, _>>()?;
    if names.next().is_some() {
        return Err("the schema has more names than columns".into());
    }
    Ok(Schema::new(fields))
}

/// One cell of a fixture. A null takes the column's type; anything else has to arrive as that
/// type already, because casting it here would be an input the case did not write.
fn scalar(lit: &proto::expression::Literal, want: &DataType) -> Result<ScalarValue, Harness> {
    use proto::expression::literal::LiteralType as L;
    let value = match lit.literal_type.as_ref().ok_or("a literal with no value")? {
        L::Null(_) => {
            return ScalarValue::try_from(want).map_err(|e| Harness(e.to_string()));
        }
        L::Boolean(v) => ScalarValue::Boolean(Some(*v)),
        L::I8(v) => ScalarValue::Int8(Some(*v as i8)),
        L::I16(v) => ScalarValue::Int16(Some(*v as i16)),
        L::I32(v) => ScalarValue::Int32(Some(*v)),
        L::I64(v) => ScalarValue::Int64(Some(*v)),
        L::Fp32(v) => ScalarValue::Float32(Some(*v)),
        L::Fp64(v) => ScalarValue::Float64(Some(*v)),
        L::String(v) => ScalarValue::Utf8(Some(v.clone())),
        L::Binary(v) => ScalarValue::Binary(Some(v.clone())),
        L::Date(v) => ScalarValue::Date32(Some(*v)),
        L::Decimal(d) => {
            let bytes: [u8; 16] = d
                .value
                .as_slice()
                .try_into()
                .map_err(|_| "a decimal literal that is not 16 bytes")?;
            ScalarValue::Decimal128(
                Some(i128::from_le_bytes(bytes)),
                d.precision as u8,
                d.scale as i8,
            )
        }
        L::PrecisionTimestamp(t) => match time_unit(t.precision)? {
            TimeUnit::Second => ScalarValue::TimestampSecond(Some(t.value), None),
            TimeUnit::Millisecond => ScalarValue::TimestampMillisecond(Some(t.value), None),
            TimeUnit::Microsecond => ScalarValue::TimestampMicrosecond(Some(t.value), None),
            TimeUnit::Nanosecond => ScalarValue::TimestampNanosecond(Some(t.value), None),
        },
        other => return Err(format!("no Arrow value for a {} literal", variant(other)).into()),
    };
    if &value.data_type() != want {
        return Err(format!("a {} value in a {} column", value.data_type(), want).into());
    }
    Ok(value)
}

/// Every ReadRel under a relation. The arms name each relation that has an input; the ones that
/// have none end the walk, and so does a relation added to Substrait after this was written, which
/// costs only the base_schema check below for the reads under it.
fn reads<'a>(rel: &'a proto::Rel, out: &mut Vec<&'a proto::ReadRel>) {
    use proto::rel::RelType as R;
    let Some(rel_type) = rel.rel_type.as_ref() else {
        return;
    };
    let children: Vec<&proto::Rel> = match rel_type {
        R::Read(r) => {
            out.push(r);
            vec![]
        }
        R::Filter(r) => r.input.as_deref().into_iter().collect(),
        R::Fetch(r) => r.input.as_deref().into_iter().collect(),
        R::Aggregate(r) => r.input.as_deref().into_iter().collect(),
        R::Sort(r) => r.input.as_deref().into_iter().collect(),
        R::Project(r) => r.input.as_deref().into_iter().collect(),
        R::Window(r) => r.input.as_deref().into_iter().collect(),
        R::Exchange(r) => r.input.as_deref().into_iter().collect(),
        R::Expand(r) => r.input.as_deref().into_iter().collect(),
        R::Write(r) => r.input.as_deref().into_iter().collect(),
        R::ExtensionSingle(r) => r.input.as_deref().into_iter().collect(),
        R::Join(r) => both(&r.left, &r.right),
        R::Cross(r) => both(&r.left, &r.right),
        R::HashJoin(r) => both(&r.left, &r.right),
        R::MergeJoin(r) => both(&r.left, &r.right),
        R::NestedLoopJoin(r) => both(&r.left, &r.right),
        R::Set(r) => r.inputs.iter().collect(),
        R::ExtensionMulti(r) => r.inputs.iter().collect(),
        _ => vec![],
    };
    for child in children {
        reads(child, out);
    }
}

fn both<'a>(
    left: &'a Option<Box<proto::Rel>>,
    right: &'a Option<Box<proto::Rel>>,
) -> Vec<&'a proto::Rel> {
    [left.as_deref(), right.as_deref()]
        .into_iter()
        .flatten()
        .collect()
}

fn table_reference(name: &[String]) -> Result<TableReference, Harness> {
    match name {
        [table] => Ok(TableReference::bare(table.as_str())),
        [schema, table] => Ok(TableReference::partial(schema.as_str(), table.as_str())),
        [catalog, schema, table] => Ok(TableReference::full(
            catalog.as_str(),
            schema.as_str(),
            table.as_str(),
        )),
        _ => Err(format!("a table named by {} parts", name.len()).into()),
    }
}

/// Registers the case's input tables, and refuses a plan that declares a different input schema.
fn bind(ctx: &SessionContext, case: &RelationTestCase) -> Result<(), Harness> {
    let mut declared: HashMap<&[String], &proto::NamedStruct> = HashMap::new();
    for table in &case.tables {
        let ns = table
            .schema
            .as_ref()
            .ok_or("an input table with no schema")?;
        let schema = Arc::new(arrow_schema(ns)?);
        let mut columns: Vec<Vec<ScalarValue>> = vec![Vec::new(); schema.fields().len()];
        for row in &table.rows {
            if row.fields.len() != columns.len() {
                return Err(format!(
                    "a row of {} values in a table of {} columns",
                    row.fields.len(),
                    columns.len()
                )
                .into());
            }
            for (i, lit) in row.fields.iter().enumerate() {
                columns[i].push(scalar(lit, schema.field(i).data_type())?);
            }
        }
        let arrays = columns
            .into_iter()
            .zip(schema.fields().iter())
            .map(|(values, field)| {
                if values.is_empty() {
                    Ok(new_empty_array(field.data_type()))
                } else {
                    ScalarValue::iter_to_array(values).map_err(|e| Harness(e.to_string()))
                }
            })
            .collect::<Result<Vec<ArrayRef>, _>>()?;
        let batch = RecordBatch::try_new(Arc::clone(&schema), arrays)
            .map_err(|e| Harness(e.to_string()))?;
        let provider =
            MemTable::try_new(schema, vec![vec![batch]]).map_err(|e| Harness(e.to_string()))?;
        ctx.register_table(table_reference(&table.name)?, Arc::new(provider))
            .map_err(|e| Harness(e.to_string()))?;
        declared.insert(table.name.as_slice(), ns);
    }

    let plan = case.plan.as_ref().ok_or("a case with no plan")?;
    let mut found = Vec::new();
    for relation in &plan.relations {
        match relation.rel_type.as_ref() {
            Some(proto::plan_rel::RelType::Root(root)) => {
                if let Some(input) = root.input.as_ref() {
                    reads(input, &mut found);
                }
            }
            Some(proto::plan_rel::RelType::Rel(rel)) => reads(rel, &mut found),
            None => {}
        }
    }
    for read in found {
        if let Some(proto::read_rel::ReadType::NamedTable(nt)) = read.read_type.as_ref() {
            let key = nt.names.join(".");
            let Some(ns) = declared.get(nt.names.as_slice()) else {
                return Err(
                    format!("plan reads table \"{key}\", which the case does not bind").into(),
                );
            };
            if read.base_schema.as_ref() != Some(*ns) {
                return Err(format!(
                    "table \"{key}\": the fixture schema is not the plan's base_schema"
                )
                .into());
            }
        }
    }
    Ok(())
}

fn render_type(data_type: &DataType, is_nullable: bool) -> String {
    let base = match data_type {
        DataType::Boolean => "bool".to_string(),
        DataType::Int8 => "i8".to_string(),
        DataType::Int16 => "i16".to_string(),
        DataType::Int32 => "i32".to_string(),
        DataType::Int64 => "i64".to_string(),
        DataType::Float32 => "fp32".to_string(),
        DataType::Float64 => "fp64".to_string(),
        DataType::Utf8 | DataType::LargeUtf8 | DataType::Utf8View => "string".to_string(),
        DataType::Binary | DataType::LargeBinary | DataType::BinaryView => "binary".to_string(),
        DataType::FixedSizeBinary(n) => format!("fixedbinary<{n}>"),
        DataType::Date32 => "date".to_string(),
        DataType::Decimal128(p, s) => format!("decimal<{p},{s}>"),
        DataType::Timestamp(unit, tz) => format!(
            "{}<{}>",
            if tz.is_some() {
                "precision_timestamp_tz"
            } else {
                "precision_timestamp"
            },
            match unit {
                TimeUnit::Second => 0,
                TimeUnit::Millisecond => 3,
                TimeUnit::Microsecond => 6,
                TimeUnit::Nanosecond => 9,
            }
        ),
        DataType::Struct(fields) => format!(
            "struct<{}>",
            fields
                .iter()
                .map(|f| format!(
                    "{}:{}",
                    f.name(),
                    render_type(f.data_type(), f.is_nullable())
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        // Passed through rather than dropped, so a column that meets a type this table has never
        // seen still shows it.
        other => format!("{other:?}").to_lowercase(),
    };
    if is_nullable { base + "?" } else { base }
}

fn render_schema(plan: &LogicalPlan) -> String {
    let columns = plan
        .schema()
        .fields()
        .iter()
        .map(|f| {
            format!(
                "{}:{}",
                f.name(),
                render_type(f.data_type(), f.is_nullable())
            )
        })
        .collect::<Vec<_>>();
    format!("[{}]", columns.join(", "))
}

/// Python's repr of a float, which is what probe/relations/corpus.py writes for one: the shortest
/// digits that round-trip, positional from 1e-4 up to 1e16 and in exponent form outside that.
fn py_float(v: f64) -> String {
    if v.is_nan() {
        return "nan".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    if v == 0.0 {
        return if v.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    let sci = format!("{v:e}");
    let (mantissa, exponent) = sci.split_once('e').unwrap_or((sci.as_str(), "0"));
    let exponent: i32 = exponent.parse().unwrap_or(0);
    let sign = if mantissa.starts_with('-') { "-" } else { "" };
    let digits: String = mantissa.chars().filter(|c| c.is_ascii_digit()).collect();
    if (-4..16).contains(&exponent) {
        if exponent >= 0 {
            let point = exponent as usize + 1;
            if digits.len() > point {
                format!("{sign}{}.{}", &digits[..point], &digits[point..])
            } else {
                format!("{sign}{digits:0<point$}.0")
            }
        } else {
            format!("{sign}0.{}{digits}", "0".repeat((-exponent - 1) as usize))
        }
    } else {
        let head = if digits.len() > 1 {
            format!("{}.{}", &digits[..1], &digits[1..])
        } else {
            digits.clone()
        };
        let exp_sign = if exponent < 0 { "-" } else { "+" };
        format!("{sign}{head}e{exp_sign}{:02}", exponent.abs())
    }
}

/// A decimal as Python's `format(Decimal(unscaled).scaleb(-scale), "f")`: exactly `scale` digits
/// after the point.
fn py_decimal(unscaled: i128, scale: i8) -> String {
    if scale <= 0 {
        return (unscaled * 10i128.pow(scale.unsigned_abs() as u32)).to_string();
    }
    let scale = scale as usize;
    let digits = unscaled.unsigned_abs().to_string();
    let padded = format!("{digits:0>width$}", width = scale + 1);
    let (whole, fraction) = padded.split_at(padded.len() - scale);
    format!("{}{whole}.{fraction}", if unscaled < 0 { "-" } else { "" })
}

/// A timestamp as Python's `datetime.isoformat(sep=" ")`: the microseconds only when there are
/// any. Python's datetime holds nothing finer, and neither does the expectation side, so a value
/// with digits beyond the microsecond is not rendered at all rather than rounded.
fn py_timestamp(value: i64, unit: &TimeUnit) -> Result<String, Harness> {
    let dt = match unit {
        TimeUnit::Second => as_datetime::<TimestampSecondType>(value),
        TimeUnit::Millisecond => as_datetime::<TimestampMillisecondType>(value),
        TimeUnit::Microsecond => as_datetime::<TimestampMicrosecondType>(value),
        TimeUnit::Nanosecond => as_datetime::<TimestampNanosecondType>(value),
    }
    .ok_or_else(|| format!("timestamp {value} is out of range"))?;
    let nanos = dt.format("%9f").to_string();
    if !nanos.ends_with("000") {
        return Err(format!("timestamp {value} is finer than a microsecond").into());
    }
    let seconds = dt.format("%Y-%m-%d %H:%M:%S").to_string();
    Ok(if nanos == "000000000" {
        seconds
    } else {
        format!("{seconds}.{}", &nanos[..6])
    })
}

/// One cell of a result, spelled the way probe/relations/corpus.py spells a value.
fn render_value(a: &dyn Array, i: usize) -> Result<String, Harness> {
    if a.is_null(i) {
        return Ok("null".to_string());
    }
    Ok(match a.data_type() {
        DataType::Boolean => (if a.as_boolean().value(i) {
            "true"
        } else {
            "false"
        })
        .to_string(),
        DataType::Int8 => a.as_primitive::<Int8Type>().value(i).to_string(),
        DataType::Int16 => a.as_primitive::<Int16Type>().value(i).to_string(),
        DataType::Int32 => a.as_primitive::<Int32Type>().value(i).to_string(),
        DataType::Int64 => a.as_primitive::<Int64Type>().value(i).to_string(),
        DataType::UInt8 => a.as_primitive::<UInt8Type>().value(i).to_string(),
        DataType::UInt16 => a.as_primitive::<UInt16Type>().value(i).to_string(),
        DataType::UInt32 => a.as_primitive::<UInt32Type>().value(i).to_string(),
        DataType::UInt64 => a.as_primitive::<UInt64Type>().value(i).to_string(),
        DataType::Float32 => py_float(a.as_primitive::<Float32Type>().value(i) as f64),
        DataType::Float64 => py_float(a.as_primitive::<Float64Type>().value(i)),
        DataType::Utf8 => format!("'{}'", a.as_string::<i32>().value(i)),
        DataType::LargeUtf8 => format!("'{}'", a.as_string::<i64>().value(i)),
        DataType::Utf8View => format!("'{}'", a.as_string_view().value(i)),
        DataType::Binary => hex(a.as_binary::<i32>().value(i)),
        DataType::LargeBinary => hex(a.as_binary::<i64>().value(i)),
        DataType::Decimal128(_, s) => py_decimal(a.as_primitive::<Decimal128Type>().value(i), *s),
        DataType::Date32 => {
            let days = a.as_primitive::<Date32Type>().value(i);
            as_datetime::<Date32Type>(days as i64)
                .ok_or_else(|| format!("date {days} is out of range"))?
                .format("%Y-%m-%d")
                .to_string()
        }
        DataType::Timestamp(unit, None) => {
            let value = match unit {
                TimeUnit::Second => a.as_primitive::<TimestampSecondType>().value(i),
                TimeUnit::Millisecond => a.as_primitive::<TimestampMillisecondType>().value(i),
                TimeUnit::Microsecond => a.as_primitive::<TimestampMicrosecondType>().value(i),
                TimeUnit::Nanosecond => a.as_primitive::<TimestampNanosecondType>().value(i),
            };
            py_timestamp(value, unit)?
        }
        other => return Err(format!("the harness cannot render a {other} value").into()),
    })
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::from("0x");
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

/// `(1, null) (2, 2)`, sorted by the rendered text: every row set in the corpus is a multiset, and
/// probe/relations/corpus.py sorts the expectation the same way.
fn render_rows(batches: &[RecordBatch]) -> Result<String, Harness> {
    let mut rows = Vec::new();
    for batch in batches {
        for i in 0..batch.num_rows() {
            let cells = batch
                .columns()
                .iter()
                .map(|c| render_value(c.as_ref(), i))
                .collect::<Result<Vec<_>, _>>()?;
            rows.push(format!("({})", cells.join(", ")));
        }
    }
    rows.sort();
    Ok(rows.join(" "))
}

/// The first line of an error, its runs of whitespace collapsed and cut at 160 characters, as the
/// DataFusion probe of the 98-plan corpus cuts it. A refusal of a relation this consumer has no arm
/// for carries the whole relation after it, which would otherwise be the longest line in the column.
fn refusal(error: &impl std::fmt::Display) -> String {
    let text = error.to_string();
    let first = text.lines().next().unwrap_or("");
    let collapsed = first.split_whitespace().collect::<Vec<_>>().join(" ");
    format!("ERROR: {}", collapsed.chars().take(160).collect::<String>())
}

async fn answer(case: &RelationTestCase) -> Result<String, Harness> {
    let ctx = SessionContext::new();
    bind(&ctx, case)?;
    let plan = case.plan.as_ref().ok_or("a case with no plan")?;
    let logical = match from_substrait_plan(&ctx.state(), plan).await {
        Ok(logical) => logical,
        Err(e) => return Ok(refusal(&e)),
    };
    let schema = render_schema(&logical);
    // Executed whether or not the case declares rows, as the DuckDB runner executes every plan: a
    // plan the consumer accepts and the engine cannot run is not an answer.
    let batches = match ctx.execute_logical_plan(logical).await {
        Ok(frame) => match frame.collect().await {
            Ok(batches) => batches,
            Err(e) => return Ok(refusal(&e)),
        },
        Err(e) => return Ok(refusal(&e)),
    };
    if case.expect.as_ref().and_then(|e| e.rows.as_ref()).is_some() {
        Ok(format!("{schema} rows {}", render_rows(&batches)?))
    } else {
        Ok(schema)
    }
}

#[tokio::main]
async fn main() {
    let path = std::env::args()
        .nth(1)
        .expect("usage: relation_case <bundle.pb>");
    let bytes = std::fs::read(&path).expect("could not read the bundle");
    let case = RelationTestCase::decode(bytes.as_slice()).expect("not a RelationTestCase");
    let line = match answer(&case).await {
        Ok(line) => line,
        Err(Harness(why)) => format!("HARNESS-ERROR: {why}"),
    };
    println!("{}\t{}", case.id, line);
}
