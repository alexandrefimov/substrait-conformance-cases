import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * Top-N, and the one thing the spec fixes about it: "Direct Output Order: The field order of the
 * input" (physical_relations.md, Top-N Operation). Sorting and cutting change which rows come back
 * and not which columns, so the schema is the input's, unchanged.
 *
 * <p>A thin assertion on purpose. TopNRel is field 23 in the Rel oneof and support for it is thin
 * everywhere: what this case mostly records is who reads the relation at all, which is a fact about
 * the field's age rather than about anyone's derivation.
 */
public class GenTopN {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    TopNRel top =
        TopNRel.newBuilder()
            .setCommon(Tables.direct())
            .setInput(Tables.namedWithCommon("t_rn", "RN"))
            .addSorts(
                SortField.newBuilder()
                    .setExpr(field(0))
                    .setDirection(SortField.SortDirection.SORT_DIRECTION_ASC_NULLS_LAST))
            .setOffset(literal(0))
            .setCount(literal(2))
            .setMode(FetchMode.FETCH_MODE_ROWS_ONLY)
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setTopN(top))
                            .addAllNames(List.of("c0", "c1"))))
            .build();
    Files.writeString(out.resolve("topn_keeps_the_input_schema.json"),
        JsonFormat.printer().print(plan) + "\n");
    System.out.printf("=== topn_keeps_the_input_schema  sorting and cutting change rows, not "
        + "columns%n");
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

  static Expression literal(long v) {
    return Expression.newBuilder()
        .setLiteral(Expression.Literal.newBuilder().setI64(v).setNullable(false))
        .build();
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
}
