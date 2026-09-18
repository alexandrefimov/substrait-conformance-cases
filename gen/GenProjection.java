import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * ReadRel.projection - masking columns at the read. By the spec the projection masks the read's
 * columns before anything else, so emit's indexes count the columns that are left.
 *
 * <p>t_mix is (c0 i64 = 10, c1 string = "x", c2 bool = true). The mask selects fields 0 and 2, so
 * the expectation is [i64, bool] with the row (10, true).
 *
 * <p>The mask lists its fields in ascending order on purpose. v0.102.0 does not settle whether a
 * mask may reorder at all: algebra.proto describes a MaskExpression as one that "selectively removes
 * fields" and adds that it "does not fundamentally alter the structure of data beyond the
 * elimination of unnecessary elements", while field_references.md raises reordering as an open
 * question - "Right now, you can only mask things out." A mask listing [2, 0] makes this case assert
 * an output order the spec does not give, and its answer then depends on which reading a participant
 * took. Listing [0, 2] gives [i64, bool] under either reading, and what the case is for - whether the
 * projection is applied at all - is unchanged, because a consumer that ignores it answers with all
 * three columns either way.
 *
 * <p>read_projection_mask_reordered is the question itself: the same read with the mask listing
 * [2, 0]. It carries no expectation, because the spec gives none, and what it measures is which
 * reading each participant takes - schema order, the listed order, or a refusal.
 */
public class GenProjection {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    write(out, "read_projection_mask", List.of(0, 2),
        "the mask selects fields [0, 2], expecting [i64, bool] / (10, true)");
    write(out, "read_projection_mask_reordered", List.of(2, 0),
        "the mask lists fields [2, 0]; the spec does not say what that yields");
  }

  static void write(Path out, String name, List<Integer> fields, String note) throws Exception {
    Expression.MaskExpression.StructSelect.Builder select =
        Expression.MaskExpression.StructSelect.newBuilder();
    for (int f : fields) {
      select.addStructItems(Expression.MaskExpression.StructItem.newBuilder().setField(f));
    }
    Expression.MaskExpression mask =
        Expression.MaskExpression.newBuilder().setSelect(select).build();

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
