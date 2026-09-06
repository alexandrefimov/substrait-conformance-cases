// The corpus through the DataFusion consumer. A standalone example: the checkout it is dropped
// into is not modified, the plans are read from this repository (SUBSTRAIT_CORPUS_DIR), and nothing
// is copied anywhere. It goes into datafusion/substrait/examples/ and is removed after the run.
use datafusion::arrow::datatypes::{DataType, Field, Schema};
use datafusion::common::{Result, TableReference};
use datafusion::datasource::empty::EmptyTable;
use datafusion::prelude::SessionContext;
use datafusion_substrait::logical_plan::consumer::from_substrait_plan;
use std::sync::Arc;

fn ctx() -> Result<SessionContext> {
    let ctx = SessionContext::new();
    let foo = Schema::new(vec![
        Field::new("a", DataType::Int64, false),
        Field::new("b", DataType::Int64, false),
        Field::new("c", DataType::Utf8, false),
    ]);
    ctx.register_table(
        TableReference::bare("foo"),
        Arc::new(EmptyTable::new(Arc::new(foo))),
    )?;
    let src1 = Schema::new(vec![
        Field::new("INTCOL", DataType::Int32, true),
        Field::new("CHARCOL", DataType::Utf8, true),
    ]);
    ctx.register_table(
        TableReference::bare("SRC1"),
        Arc::new(EmptyTable::new(Arc::new(src1))),
    )?;
    ctx.register_table(
        TableReference::bare("t_rn"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![Field::new("c0", DataType::Int64, false), Field::new("c1", DataType::Int64, true)])))),
    )?;
    ctx.register_table(
        TableReference::bare("t_nr"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![Field::new("c0", DataType::Int64, true), Field::new("c1", DataType::Int64, false)])))),
    )?;
    ctx.register_table(
        TableReference::bare("s1"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![Field::new("c0", DataType::Int64, false), Field::new("c1", DataType::Int64, false), Field::new("c2", DataType::Int64, false), Field::new("c3", DataType::Int64, false), Field::new("c4", DataType::Int64, true), Field::new("c5", DataType::Int64, true), Field::new("c6", DataType::Int64, true), Field::new("c7", DataType::Int64, true)])))),
    )?;
    ctx.register_table(
        TableReference::bare("s2"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![Field::new("c0", DataType::Int64, false), Field::new("c1", DataType::Int64, false), Field::new("c2", DataType::Int64, true), Field::new("c3", DataType::Int64, true), Field::new("c4", DataType::Int64, false), Field::new("c5", DataType::Int64, false), Field::new("c6", DataType::Int64, true), Field::new("c7", DataType::Int64, true)])))),
    )?;
    ctx.register_table(
        TableReference::bare("s3"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![Field::new("c0", DataType::Int64, false), Field::new("c1", DataType::Int64, true), Field::new("c2", DataType::Int64, false), Field::new("c3", DataType::Int64, true), Field::new("c4", DataType::Int64, false), Field::new("c5", DataType::Int64, true), Field::new("c6", DataType::Int64, false), Field::new("c7", DataType::Int64, true)])))),
    )?;
    ctx.register_table(
        TableReference::bare("t_xnull"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![Field::new("c0", DataType::Int64, true)])))),
    )?;
    {
        use datafusion::arrow::array::{ArrayRef, BooleanArray, Int64Array, StringArray};
        use datafusion::arrow::record_batch::RecordBatch;
        use datafusion::datasource::MemTable;
        let schema = Arc::new(Schema::new(vec![
            Field::new("c0", DataType::Int64, false),
            Field::new("c1", DataType::Utf8, false),
            Field::new("c2", DataType::Boolean, false),
        ]));
        let batch = RecordBatch::try_new(
            Arc::clone(&schema),
            vec![
                Arc::new(Int64Array::from(vec![10])) as ArrayRef,
                Arc::new(StringArray::from(vec!["x"])) as ArrayRef,
                Arc::new(BooleanArray::from(vec![true])) as ArrayRef,
            ],
        )
        .unwrap();
        ctx.register_table(
            TableReference::bare("t_mix"),
            Arc::new(MemTable::try_new(schema, vec![vec![batch]])?),
        )?;
    }
    {
        use datafusion::arrow::array::{ArrayRef, Decimal128Array};
        use datafusion::arrow::record_batch::RecordBatch;
        use datafusion::datasource::MemTable;
        // c2 = c3 = 10^38-1 unscaled, that is dec(38,10) at its maximum: the exact sum needs 39
        // digits and does not fit into (38,10).
        const BIG: i128 = 99999999999999999999999999999999999999;
        let schema = Arc::new(Schema::new(vec![
            Field::new("c0", DataType::Decimal128(10, 2), false),
            Field::new("c1", DataType::Decimal128(5, 1), false),
            Field::new("c2", DataType::Decimal128(38, 10), false),
            Field::new("c3", DataType::Decimal128(38, 10), false),
        ]));
        let batch = RecordBatch::try_new(
            Arc::clone(&schema),
            vec![
                Arc::new(Decimal128Array::from(vec![100i128]).with_precision_and_scale(10, 2)?) as ArrayRef,
                Arc::new(Decimal128Array::from(vec![30i128]).with_precision_and_scale(5, 1)?) as ArrayRef,
                Arc::new(Decimal128Array::from(vec![BIG]).with_precision_and_scale(38, 10)?) as ArrayRef,
                Arc::new(Decimal128Array::from(vec![BIG]).with_precision_and_scale(38, 10)?) as ArrayRef,
            ],
        )
        .unwrap();
        ctx.register_table(
            TableReference::bare("t_dec"),
            Arc::new(MemTable::try_new(schema, vec![vec![batch]])?),
        )?;
    }
    ctx.register_table(
        TableReference::bare("t_str"),
        Arc::new(EmptyTable::new(Arc::new(Schema::new(vec![
            Field::new("c0", DataType::Utf8, false),
            Field::new("c1", DataType::Utf8, false),
            Field::new("c2", DataType::FixedSizeBinary(4), false),
            Field::new("c3", DataType::Utf8, false),
        ])))),
    )?;
    {
        use datafusion::arrow::array::{ArrayRef, Int64Array};
        use datafusion::arrow::record_batch::RecordBatch;
        use datafusion::datasource::MemTable;
        let schema = Arc::new(Schema::new(vec![
            Field::new("c0", DataType::Int64, false),
            Field::new("c1", DataType::Int64, false),
        ]));
        let batch = RecordBatch::try_new(
            Arc::clone(&schema),
            vec![
                Arc::new(Int64Array::from(vec![1i64, 2])) as ArrayRef,
                Arc::new(Int64Array::from(vec![10i64, 20])) as ArrayRef,
            ],
        ).unwrap();
        ctx.register_table(
            TableReference::bare("t_avg"),
            Arc::new(MemTable::try_new(schema, vec![vec![batch]])?),
        )?;
    }
    Ok(ctx)
}

fn render(plan: &datafusion::logical_expr::LogicalPlan) -> String {
    plan.schema()
        .fields()
        .iter()
        .map(|f| {
            format!(
                "{}:{:?}{}",
                f.name(),
                f.data_type(),
                if f.is_nullable() { "?" } else { "" }
            )
        })
        .collect::<Vec<_>>()
        .join(", ")
}

async fn probe(dir: &str, name: &str) {
    // The probe used to be appended to a tracked DataFusion test file, with the plans copied into
    // its testdata. It is a standalone example reading this repository now, so the checkout is not
    // modified at all.
    let path = format!("{dir}/{name}.json");
    let text = std::fs::read_to_string(&path).expect("could not read the case");
    let proto_plan: substrait::proto::Plan =
        serde_json::from_str(&text).expect("could not parse the protobuf-JSON");
    let ctx = ctx().unwrap();
    println!("\n##### {name}");
    match from_substrait_plan(&ctx.state(), &proto_plan).await {
        Ok(plan) => {
            println!("DATAFUSION ACCEPTED  [{}]", render(&plan));
            // The column count comes from the plan, not from the first batch: at zero rows there
            // are no batches at all, and the arity cannot be read off them.
            let plan_cols = plan.schema().fields().len();
            // Rows matter separately from the schema: a substituted column shows only in a value.
            match ctx.execute_logical_plan(plan).await {
                Ok(df) => match df.collect().await {
                    Ok(batches) => {
                        if let Some(b) = batches.iter().find(|b| b.num_rows() > 0) {
                            let cells: Vec<String> = (0..b.num_columns())
                                .map(|i| format!("{:?}", b.column(i).as_ref().slice(0, 1)))
                                .collect();
                            let one: Vec<String> = cells
                                .iter()
                                .map(|c| {
                                    c.lines()
                                        .find(|l| l.trim().starts_with(|ch: char| ch != '[' && ch != ']')
                                            && !l.contains("Array"))
                                        .unwrap_or("")
                                        .trim()
                                        .trim_end_matches(',')
                                        .to_string()
                                })
                                .collect();
                            println!("DATAFUSION ROW       ({})", one.join(", "));
                        }
                        // The whole multiset: multiplicity is invisible in a schema.
                        //
                        // unwrap_or(plan_cols): an empty result arrives as zero batches, and the
                        // condition on the first batch then did not fire at all, so the ROWS line
                        // was not printed - "ran and returned nothing" was again indistinguishable
                        // from "did not run", although the fix below claimed otherwise.
                        if batches.first().map(|b| b.num_columns()).unwrap_or(plan_cols) == 1 {
                            use datafusion::arrow::array::{Array, Int64Array};
                            let mut vals: Vec<i64> = Vec::new();
                            // Only Int64 is collected. For a column of another type the list stays
                            // empty, and printing that as ROWS [] would say "no rows" about a result
                            // that has them: on the aggregation-phase cases the column is Float64
                            // and the answer is 1.5.
                            let mut collectable = batches.is_empty();
                            for b in &batches {
                                if let Some(arr) =
                                    b.column(0).as_any().downcast_ref::<Int64Array>()
                                {
                                    collectable = true;
                                    for i in 0..arr.len() {
                                        if !arr.is_null(i) {
                                            vals.push(arr.value(i));
                                        }
                                    }
                                }
                            }
                            if !collectable {
                                let t = batches[0].column(0).data_type().to_string();
                                // A tag of its own rather than ROWS: check_rows.py pulls every
                                // number out of a ROWS body with a regexp, and "Float64" would
                                // give it the row 64.
                                println!("DATAFUSION NOCOUNT   column {t}, only Int64 is counted");
                            } else {
                                vals.sort_unstable();
                                // Always printed, an empty result included.
                                println!("DATAFUSION ROWS      {:?}", vals);
                            }
                        }
                    }
                    Err(e) => println!("DATAFUSION EXECERR   {}", e.to_string().lines().next().unwrap_or("")),
                },
                Err(e) => println!("DATAFUSION EXECERR   {}", e.to_string().lines().next().unwrap_or("")),
            }
        }
        Err(e) => {
            let msg = e.to_string();
            let head: String = msg.chars().take(160).collect();
            println!("DATAFUSION REJECTED  {head}");
        }
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let dir = std::env::var("SUBSTRAIT_CORPUS_DIR").expect("SUBSTRAIT_CORPUS_DIR is not set");
    let mut names: Vec<String> = std::fs::read_dir(&dir)
        .expect("could not read the case directory")
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".json") && !n.contains("manifest"))
        .map(|n| n.trim_end_matches(".json").to_string())
        .collect();
    names.sort();
    for name in &names {
        probe(&dir, name).await;
    }
}
