import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * The cross product, and the one thing the spec fixes about it: "Direct Output Order: Same as the
 * `Input Order`" (logical_relations.md, Cross Product Operation). So the output is the left input's
 * fields and then the right input's, and nothing else happens to them.
 *
 * <p>The nullability is the half worth measuring. A cross product pads nothing - every output row
 * pairs a real left row with a real right row - so a required column stays required on both sides.
 * That is exactly where the join cases in this corpus already found three participants widening a
 * side that a join does null-pad, and this case asks the same question where the answer is no.
 *
 * <p>t_rn is (c0 i64 required, c1 i64 nullable) and t_nr is (c0 i64 nullable, c1 i64 required), so
 * a side that comes back wholly nullable, wholly required, or in the wrong order is visible in the
 * pattern alone.
 */
public class GenCross {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    CrossRel cross =
        CrossRel.newBuilder()
            .setCommon(Tables.direct())
            .setLeft(Tables.namedWithCommon("t_rn", "RN"))
            .setRight(Tables.namedWithCommon("t_nr", "NR"))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setCross(cross))
                            .addAllNames(List.of("l0", "l1", "r0", "r1"))))
            .build();
    Files.writeString(out.resolve("cross_preserves_nullability.json"),
        JsonFormat.printer().print(plan) + "\n");
    System.out.printf(
        "=== cross_preserves_nullability  the left input's fields then the right's, neither side "
            + "padded%n");
    try {
      System.out.printf(
          "    substrait-java: %s%n",
          new io.substrait.plan.ProtoPlanConverter().from(plan)
              .getRoots().get(0).getInput().getRecordType());
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println("    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }
}
