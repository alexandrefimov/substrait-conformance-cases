import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * The expand relation, and the two rules the spec states about it.
 *
 * <p><b>Its output.</b> "Direct Output Order: The expand fields followed by an i32 column describing
 * the index of the duplicate that the row is derived from" (physical_relations.md, Expand
 * Operation). The rule is unconditional in that table, so a bare expand of two fields is three
 * columns and not two.
 *
 * <p><b>A switching field's type.</b> "All duplicates must return the same type class but may differ
 * in nullability. The effective type of the output field will be nullable if any of the duplicate
 * expressions are nullable" (ExpandRel.SwitchingField in algebra.proto). So a field switching
 * between a required column and a nullable one is nullable.
 *
 * <p>Unlike the window cases, nothing here is declared: an ExpandField carries no output_type, and
 * its type comes from the expression. Both cases therefore ask a consumer to derive rather than to
 * repeat.
 */
public class GenExpand {
  static Path OUT;

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);

    // Two fields that do not switch: the output is those two and the duplicate index.
    emit("expand_consistent_fields",
        ExpandRel.newBuilder()
            .setCommon(Tables.direct())
            .setInput(Tables.namedWithCommon("t_rn", "RN"))
            .addFields(consistent(field(0)))
            .addFields(consistent(field(1))),
        "consistent_fields  two fields that do not switch, so the output is those two and the "
            + "i32 index");

    // One field switches between a required column and a nullable one, so it is nullable.
    emit("expand_switching_nullability",
        ExpandRel.newBuilder()
            .setCommon(Tables.direct())
            .setInput(Tables.namedWithCommon("t_rn", "RN"))
            .addFields(consistent(field(0)))
            .addFields(
                ExpandRel.ExpandField.newBuilder()
                    .setSwitchingField(
                        ExpandRel.SwitchingField.newBuilder()
                            .addDuplicates(field(0))
                            .addDuplicates(field(1)))),
        "switching_nullability  a field switching between a required column and a nullable one is "
            + "nullable");
  }

  static ExpandRel.ExpandField consistent(Expression e) {
    return ExpandRel.ExpandField.newBuilder().setConsistentField(e).build();
  }

  static Expression field(int i) {
    return Expression.newBuilder()
        .setSelection(
            Expression.FieldReference.newBuilder()
                .setRootReference(Expression.FieldReference.RootReference.getDefaultInstance())
                .setDirectReference(
                    Expression.ReferenceSegment.newBuilder()
                        .setStructField(
                            Expression.ReferenceSegment.StructField.newBuilder().setField(i))))
        .build();
  }

  static void emit(String name, ExpandRel.Builder rel, String note) throws Exception {
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setExpand(rel))))
            .build();
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf("=== %s%n", note);
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
