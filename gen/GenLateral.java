import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * LateralJoinRel, and the one thing v0.102.0 says two ways about it: when the join has to carry a
 * RelCommon.rel_anchor. algebra.proto says "LateralJoinRel must set RelCommon.rel_anchor so the
 * right input can reference fields of the current left row". logical_relations.md, Lateral Join
 * Operation, says "When the right input references the current left row, LateralJoinRel must set
 * RelCommon.rel_anchor". The two agree whenever the right input does reference the left row, and
 * part when it does not.
 *
 * <p>So both cases here have a right input that references nothing outside itself: t_nr, read as it
 * is. lateral_join_uncorrelated sets the anchor anyway, which is valid under either text;
 * lateral_join_uncorrelated_without_anchor leaves it out, which the page allows and the proto does
 * not. The anchor is the only difference between them, so a participant that answers the first and
 * refuses the second refuses over the anchor, and one that refuses both does not implement the
 * relation.
 *
 * <p>The schema under either reading is that of an inner join of t_rn (required, nullable) and t_nr
 * (nullable, required): the page calls a lateral join "semantically identical to JoinRel", and the
 * condition is the literal true.
 */
public class GenLateral {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    write(out, "lateral_join_uncorrelated", true,
        "an inner lateral join whose right input references nothing, anchor set, expecting t_rn "
            + "then t_nr unchanged");
    write(out, "lateral_join_uncorrelated_without_anchor", false,
        "the same join without rel_anchor: the page allows it, algebra.proto does not");
  }

  static void write(Path out, String name, boolean anchor, String note) throws Exception {
    RelCommon.Builder common = Tables.direct().toBuilder();
    if (anchor) {
      common.setRelAnchor(1);
    }
    LateralJoinRel join =
        LateralJoinRel.newBuilder()
            .setCommon(common)
            .setLeft(Tables.namedWithCommon("t_rn", "RN"))
            .setRight(Tables.namedWithCommon("t_nr", "NR"))
            .setExpression(
                Expression.newBuilder()
                    .setLiteral(Expression.Literal.newBuilder().setBoolean(true)))
            .setType(JoinRel.JoinType.JOIN_TYPE_INNER)
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setLateralJoin(join))
                            .addAllNames(List.of("l0", "l1", "r0", "r1"))))
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
