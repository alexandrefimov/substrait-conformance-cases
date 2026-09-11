// Generates the bindings a bundle is read with: relation_test.proto alone, compiled by prost. The
// Substrait messages it refers to resolve to the substrait crate datafusion-substrait re-exports,
// so a bundle is decoded into the very types the consumer takes, not into a second copy compiled
// beside them.
//
// The three are named one by one rather than as the `.substrait` package. An extern path matches by
// prefix and prost generates nothing for a message it resolves to one, so the package entry would
// also claim `.substrait.test` and leave relation_test.proto with no code at all. A message the file
// starts referring to later fails the build here, rather than being decoded into a type of its own.
fn main() -> std::io::Result<()> {
    let repo = std::env::var("RELATIONS_REPO")
        .expect("RELATIONS_REPO names the repository whose proto/ holds relation_test.proto");
    let own = format!("{repo}/proto");
    let vendored = format!("{repo}/tests/relations/vendor/proto");
    println!("cargo:rerun-if-env-changed=RELATIONS_REPO");
    println!("cargo:rerun-if-changed={own}/substrait/test/relation_test.proto");
    let substrait = "::datafusion_substrait::substrait::proto";
    prost_build::Config::new()
        .extern_path(".substrait.Plan", format!("{substrait}::Plan"))
        .extern_path(
            ".substrait.NamedStruct",
            format!("{substrait}::NamedStruct"),
        )
        .extern_path(".substrait.Expression", format!("{substrait}::Expression"))
        .compile_protos(
            &[format!("{own}/substrait/test/relation_test.proto")],
            &[own, vendored],
        )
}
