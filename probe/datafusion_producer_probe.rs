// What DataFusion DECLARES in output_type when it produces a plan, and whether it agrees with
// itself on reading that plan back. The probe is external and changes nothing in the crate.
//
// The plans it produces are written to $SUBSTRAIT_PLANS_OUT (default ./df_plans), so they can be
// handed to other participants - probe/SchemaOfBin.java reads them.
use std::collections::HashMap;
use prost::Message;
use std::sync::Arc;

use datafusion::arrow::datatypes::{DataType, Field, Schema};
use datafusion::datasource::MemTable;
use datafusion::prelude::SessionContext;
use datafusion_substrait::logical_plan::consumer::from_substrait_plan;
use datafusion_substrait::logical_plan::producer::to_substrait_plan;
use datafusion_substrait::substrait::proto::expression::RexType;
use datafusion_substrait::substrait::proto::extensions::simple_extension_declaration::MappingType;
use datafusion_substrait::substrait::proto::r#type::Kind;
use datafusion_substrait::substrait::proto::function_argument::ArgType;
use datafusion_substrait::substrait::proto::plan_rel;
use datafusion_substrait::substrait::proto::{Expression, Plan, Rel, Type, rel};

fn type_str(t: &Type) -> String {
    match &t.kind {
        Some(Kind::Decimal(d)) => format!("dec({},{})", d.precision, d.scale),
        Some(Kind::I64(_)) => "i64".to_string(),
        Some(Kind::Fp64(_)) => "fp64".to_string(),
        Some(k) => format!("{k:?}").split('(').next().unwrap().to_lowercase(),
        None => "?".to_string(),
    }
}

fn walk_expr(e: &Expression, names: &HashMap<u32, String>, out: &mut Vec<String>) {
    if let Some(RexType::ScalarFunction(f)) = &e.rex_type {
        let name = names
            .get(&f.function_reference)
            .cloned()
            .unwrap_or_else(|| format!("#{}", f.function_reference));
        let t = f.output_type.as_ref().map(type_str).unwrap_or("none".into());
        out.push(format!("{name} -> {t}"));
        for a in &f.arguments {
            if let Some(ArgType::Value(v)) = &a.arg_type {
                walk_expr(v, names, out);
            }
        }
    }
    if let Some(RexType::Cast(c)) = &e.rex_type {
        out.push(format!("cast -> {}", c.r#type.as_ref().map(type_str).unwrap_or("?".into())));
        if let Some(i) = &c.input {
            walk_expr(i, names, out);
        }
    }
}

fn walk_rel(r: &Rel, names: &HashMap<u32, String>, out: &mut Vec<String>) {
    match &r.rel_type {
        Some(rel::RelType::Project(p)) => {
            for e in &p.expressions {
                walk_expr(e, names, out);
            }
            if let Some(i) = &p.input {
                walk_rel(i, names, out);
            }
        }
        Some(rel::RelType::Aggregate(a)) => {
            for m in &a.measures {
                if let Some(f) = &m.measure {
                    let name = names
                        .get(&f.function_reference)
                        .cloned()
                        .unwrap_or_else(|| format!("#{}", f.function_reference));
                    let t = f.output_type.as_ref().map(type_str).unwrap_or("none".into());
                    out.push(format!("{name} -> {t}"));
                }
            }
            if let Some(i) = &a.input {
                walk_rel(i, names, out);
            }
        }
        Some(rel::RelType::Filter(f)) => {
            if let Some(i) = &f.input {
                walk_rel(i, names, out);
            }
        }
        _ => {}
    }
}

fn declared(plan: &Plan) -> Vec<String> {
    let mut names = HashMap::new();
    for e in &plan.extensions {
        if let Some(MappingType::ExtensionFunction(f)) = &e.mapping_type {
            names.insert(f.function_anchor, f.name.clone());
        }
    }
    let mut out = vec![];
    for r in &plan.relations {
        if let Some(plan_rel::RelType::Root(root)) = &r.rel_type {
            if let Some(input) = &root.input {
                walk_rel(input, &names, &mut out);
            }
        }
    }
    out
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> datafusion::error::Result<()> {
    let schema = Arc::new(Schema::new(vec![
        Field::new("a", DataType::Decimal128(10, 2), false),
        Field::new("b", DataType::Decimal128(5, 1), false),
        Field::new("c", DataType::Decimal128(38, 10), false),
        Field::new("d", DataType::Decimal128(38, 10), false),
        Field::new("i", DataType::Int64, false),
    ]));
    let ctx = SessionContext::new();
    ctx.register_table("t", Arc::new(MemTable::try_new(schema.clone(), vec![vec![]])?))?;

    for sql in [
        "SELECT a + b FROM t",
        "SELECT c + d FROM t",
        "SELECT c * d FROM t",
        "SELECT a / b FROM t",
        "SELECT avg(i) FROM t",
    ] {
        if sql.contains("avg") {
            let df0 = ctx.sql(sql).await?;
            let proto0 = to_substrait_plan(&df0.logical_plan().clone(), &ctx.state())?;
            println!("    extensions: {:?}", proto0.extensions);
            println!("    URN list: {:?}", proto0.extension_urns);
            println!("    first relation: {:?}", &format!("{:?}", proto0.relations[0])[..600.min(format!("{:?}", proto0.relations[0]).len())]);
            if let Some(plan_rel::RelType::Root(root)) = &proto0.relations[0].rel_type {
                if let Some(rel::RelType::Aggregate(a)) = &root.input.as_ref().unwrap().rel_type {
                    println!("    measure[0].output_type = {:?}", a.measures[0].measure.as_ref().unwrap().output_type);
                }
            }
        }
        let df = ctx.sql(sql).await?;
        let plan = df.logical_plan().clone();
        let direct = format!("{}", plan.schema().field(0).data_type());
        match to_substrait_plan(&plan, &ctx.state()) {
            Ok(proto) => {
                let decl = declared(&proto);
                let out_dir = std::env::var("SUBSTRAIT_PLANS_OUT")
                    .unwrap_or_else(|_| "df_plans".to_string());
                let file = format!("{}/{}.pb", out_dir,
                    sql.replace("SELECT ", "").replace(" FROM t", "").replace(' ', "_")
                       .replace('+', "add").replace('*', "mul").replace('/', "div")
                       .replace('(', "_").replace(')', ""));
                std::fs::create_dir_all(&out_dir).ok();
                std::fs::write(&file, proto.encode_to_vec()).ok();
                let back = match from_substrait_plan(&ctx.state(), &proto).await {
                    Ok(p) => format!("{}", p.schema().field(0).data_type()),
                    Err(e) => format!("ERROR reading back: {}", e.to_string().replace('\n', " ")),
                };
                let same = if direct == back { "" } else { "  <-- diverged" };
                println!("{:<22} direct {:<22} round trip {:<22}{}", sql.replace("SELECT ", "").replace(" FROM t", ""), direct, back, same);
                println!("    declared: {}", decl.join("; "));
            }
            Err(e) => println!("{:<22} ERROR producing: {}", sql, e.to_string().replace('\n', " ")),
        }
    }
    Ok(())
}
