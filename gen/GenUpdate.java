import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * UpdateRel, whose output v0.102.0 describes in words and never as a type. logical_relations.md,
 * Update Operator, gives "Output is number of modified records" under Property Maintenance, and
 * algebra.proto's UpdateRel says nothing about its output at all. WriteRel, the neighbouring
 * relation, has an OutputMode whose OUTPUT_MODE_MODIFIED_RECORDS "makes the operator return all the
 * record INSERTED/DELETED/UPDATED by the operator", leaving the count to "operators upstreams". So the
 * page reads as one column holding a count, of a type it does not name, while the one mode WriteRel
 * spells out returns the rows themselves.
 *
 * <p>The update sets t_rn's nullable column c1 to 0 wherever the literal true holds, which is
 * everywhere. Nothing in it calls a function, so its answer depends on how a participant types the
 * relation and on nothing else. A root has to name every output column, so a producer has to pick a
 * reading before it can write the plan at all. The two cases are the same update under each:
 * update_root_names_a_count gives the root one name, as a count would have;
 * update_root_names_the_table gives it the table's two, as the modified records would have.
 */
public class GenUpdate {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    write(out, "update_root_names_a_count", List.of("modified"),
        "an update of t_rn with one root name, as the page's count would have");
    write(out, "update_root_names_the_table", List.of("c0", "c1"),
        "the same update with the table's two names, as its modified records would have");
  }

  static void write(Path out, String name, List<String> names, String note) throws Exception {
    NamedStruct.Builder schema = NamedStruct.newBuilder().addAllNames(List.of("c0", "c1"));
    schema.setStruct(
        Type.Struct.newBuilder()
            .setNullability(Type.Nullability.NULLABILITY_REQUIRED)
            .addTypes(Tables.i64(false))
            .addTypes(Tables.i64(true)));
    UpdateRel update =
        UpdateRel.newBuilder()
            .setCommon(Tables.direct())
            .setNamedTable(NamedTable.newBuilder().addNames("t_rn"))
            .setTableSchema(schema)
            .setCondition(
                Expression.newBuilder()
                    .setLiteral(Expression.Literal.newBuilder().setBoolean(true)))
            .addTransformations(
                UpdateRel.TransformExpression.newBuilder()
                    .setColumnTarget(1)
                    .setTransformation(
                        Expression.newBuilder()
                            .setLiteral(Expression.Literal.newBuilder().setI64(0))))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setUpdate(update))
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
