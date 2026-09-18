import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * DdlRel, the one relation v0.102.0 gives no output at all. logical_relations.md, DDL Operator: "Outputs
 * 0", and under Property Maintenance "N/A (no output)". Every other relation on that page, WriteRel
 * with OUTPUT_MODE_NO_OUTPUT included, has one output.
 *
 * <p>Both cases create a view over t_rn, the DDL Isthmus writes for CREATE VIEW: a view definition,
 * the view's schema as table_schema, and an empty table_defaults. They differ only in the root.
 * ddl_view_root_names_nothing names no column, which is what a relation with no output leaves to
 * name. ddl_view_root_names_the_view names the view's two columns, as Isthmus's own plan does and as
 * substrait-java derives; a root cannot name columns its input does not have, so under the page this
 * plan is invalid, and what it measures is whether anyone says so.
 */
public class GenDdl {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    write(out, "ddl_view_root_names_nothing", List.of(),
        "CREATE VIEW over t_rn with no root name, expecting no columns");
    write(out, "ddl_view_root_names_the_view", List.of("c0", "c1"),
        "the same view with its two columns named on the root, which a relation with no output "
            + "cannot have");
  }

  static void write(Path out, String name, List<String> names, String note) throws Exception {
    NamedStruct.Builder schema = NamedStruct.newBuilder().addAllNames(List.of("c0", "c1"));
    schema.setStruct(
        Type.Struct.newBuilder()
            .setNullability(Type.Nullability.NULLABILITY_REQUIRED)
            .addTypes(Tables.i64(false))
            .addTypes(Tables.i64(true)));
    DdlRel ddl =
        DdlRel.newBuilder()
            .setCommon(Tables.direct())
            .setNamedObject(NamedObjectWrite.newBuilder().addNames("v"))
            .setTableSchema(schema)
            .setTableDefaults(Expression.Literal.Struct.newBuilder())
            .setObject(DdlRel.DdlObject.DDL_OBJECT_VIEW)
            .setOp(DdlRel.DdlOp.DDL_OP_CREATE)
            .setViewDefinition(Tables.namedWithCommon("t_rn", "RN"))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setDdl(ddl))
                            .addAllNames(names)))
            .build();
    Files.writeString(out.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.println("=== " + name + "  " + note);
    try {
      System.out.println(
          "    substrait-java: "
              + new io.substrait.plan.ProtoPlanConverter().from(plan)
                  .getRoots().get(0).getInput().getRecordType());
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println("    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }
}
