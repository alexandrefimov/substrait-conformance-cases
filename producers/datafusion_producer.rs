// DataFusion as a producer: one plan per query, through datafusion-substrait's own
// serializer::serialize_bytes (the optimized logical plan), at the pinned DATAFUSION_COMMIT.
//
//   cp producers/datafusion_producer.rs <DF_DIR>/datafusion/substrait/examples/
//   cargo run --locked -p datafusion-substrait --example datafusion_producer -- \
//     <tables.sql> <queries.tsv> <out>
//
// Writes <out>/<query>.pb, or <out>/<query>.err with the first line of the refusal.
use datafusion::prelude::SessionContext;
use datafusion_substrait::serializer::serialize_bytes;

#[tokio::main(flavor = "current_thread")]
async fn main() -> datafusion::error::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let (tables, queries, out) = (&args[1], &args[2], std::path::Path::new(&args[3]));
    std::fs::create_dir_all(out)?;
    let ctx = SessionContext::new();
    for statement in std::fs::read_to_string(tables)?.lines() {
        ctx.sql(statement).await?.collect().await?;
    }
    for line in std::fs::read_to_string(queries)?.lines() {
        if line.starts_with('#') || line.trim().is_empty() {
            continue;
        }
        let mut fields = line.split('\t');
        let (name, sql) = (fields.next().unwrap(), fields.next().expect("<name>\\t<sql>"));
        match serialize_bytes(sql, &ctx).await {
            Ok(bytes) => std::fs::write(out.join(format!("{name}.pb")), bytes)?,
            Err(e) => {
                let first = e.to_string().lines().next().unwrap_or("").to_string();
                std::fs::write(out.join(format!("{name}.err")), first + "\n")?
            }
        }
    }
    println!("datafusion {}", datafusion::DATAFUSION_VERSION);
    Ok(())
}
