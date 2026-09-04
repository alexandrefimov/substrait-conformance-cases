import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * ReadRel.projection - masking columns at the read. By the spec the projection masks the read's
 * columns before anything else, so emit's indexes count the columns that are left.
 *
 * <p>t_mix is (c0 i64 = 10, c1 string = "x", c2 bool = true). The mask selects fields 2 and 0, so
 * the expectation is [bool, i64] with the row (true, 10) - the same as emit_read.
 */
public class GenProjection {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);

    Expression.MaskExpression mask =
        Expression.MaskExpression.newBuilder()
            .setSelect(
                Expression.MaskExpression.StructSelect.newBuilder()
                    .addStructItems(Expression.MaskExpression.StructItem.newBuilder().setField(2))
                    .addStructItems(Expression.MaskExpression.StructItem.newBuilder().setField(0)))
            .build();

    Rel read =
        Rel.newBuilder()
            .setRead(
                ReadRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setBaseSchema(GenEmit.mixSchema())
                    .setProjection(mask)
                    .setNamedTable(ReadRel.NamedTable.newBuilder().addNames("t_mix")))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder().setInput(read).addAllNames(List.of("k0", "k1"))))
            .build();

    Files.writeString(
        out.resolve("read_projection_mask.json"), JsonFormat.printer().print(plan) + "\n");
    System.out.println("=== read_projection_mask  the mask selects fields [2, 0], expecting [bool, i64] / (true, 10)");
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
