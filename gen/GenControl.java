import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * Control cases: not a single operation. If an engine loses non-nullability already here, it simply
 * does not carry it, and every conclusion about "does not narrow" drawn on it is an artefact rather
 * than a finding.
 */
public class GenControl {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Rel read = Tables.named("t_rn", "RN");
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder().setInput(read).addAllNames(List.of("c0", "c1"))))
            .build();
    Files.writeString(
        out.resolve("control_passthrough_rn.json"), JsonFormat.printer().print(plan) + "\n");

    // A dedicated probe for one finding: a join WITHOUT the optional RelCommon. Every other case
    // sets it, as real producers do, so this needs a case of its own.
    Rel joinNoCommon =
        Rel.newBuilder()
            .setJoin(
                JoinRel.newBuilder()
                    .setLeft(Tables.namedWithCommon("t_rn", "RN"))
                    .setRight(Tables.namedWithCommon("t_nr", "NR"))
                    .setType(JoinRel.JoinType.JOIN_TYPE_INNER)
                    .setExpression(
                        Expression.newBuilder()
                            .setLiteral(
                                Expression.Literal.newBuilder().setBoolean(true).setNullable(false))))
            .build();
    Plan p2 =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(joinNoCommon)
                            .addAllNames(List.of("a", "b", "c", "d"))))
            .build();
    Files.writeString(
        out.resolve("control_join_without_relcommon.json"), JsonFormat.printer().print(p2) + "\n");
    System.out.println(
        "=== control_join_without_relcommon  the same join without the optional RelCommon");
    System.out.println(
        "    substrait-java: "
            + new io.substrait.plan.ProtoPlanConverter().from(p2)
                .getRoots().get(0).getInput().getRecordType());
    System.out.println(
        "=== control_passthrough_rn  table t_rn is declared (required, nullable), no operations");
    System.out.println(
        "    substrait-java: "
            + new io.substrait.plan.ProtoPlanConverter().from(plan)
                .getRoots().get(0).getInput().getRecordType());
  }
}
