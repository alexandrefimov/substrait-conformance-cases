import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * The emit mapping on different relations. Table t_mix is (c0 i64 = 10, c1 string = "x",
 * c2 bool = true), all required; the mapping [2, 0] selects bool and i64 in reverse order, so a
 * substituted column shows both in the type and in the value. Expected: schema [bool, i64],
 * row (true, 10).
 */
public class GenEmit {
  static Path OUT;

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    emit("read", readMix(RelCommon.newBuilder().setEmit(mapping())));
    emit("filter", filter(mapping()));
    emit("sort", sort(mapping()));
    emit("fetch", fetch(mapping()));
    emit("project", project(mapping()));
    emit("join", join(mapping()));
    emit("aggregate", aggregate(mapping()));
  }

  static RelCommon.Emit.Builder mapping() {
    return RelCommon.Emit.newBuilder().addOutputMapping(2).addOutputMapping(0);
  }

  public static NamedStruct mixSchema() {
    return NamedStruct.newBuilder()
        .addNames("c0").addNames("c1").addNames("c2")
        .setStruct(
            Type.Struct.newBuilder()
                .addTypes(Tables.i64(false))
                .addTypes(
                    Type.newBuilder()
                        .setString(
                            Type.String.newBuilder()
                                .setNullability(Type.Nullability.NULLABILITY_REQUIRED)))
                .addTypes(
                    Type.newBuilder()
                        .setBool(
                            Type.Boolean.newBuilder()
                                .setNullability(Type.Nullability.NULLABILITY_REQUIRED)))
                .setNullability(Type.Nullability.NULLABILITY_REQUIRED))
        .build();
  }

  static Rel readMix(RelCommon.Builder common) {
    ReadRel.Builder r =
        ReadRel.newBuilder()
            .setBaseSchema(mixSchema())
            .setNamedTable(ReadRel.NamedTable.newBuilder().addNames("t_mix"));
    if (common != null) r.setCommon(common);
    return Rel.newBuilder().setRead(r).build();
  }

  static Expression fieldRef(int i) {
    return Expression.newBuilder()
        .setSelection(
            Expression.FieldReference.newBuilder()
                .setDirectReference(
                    Expression.ReferenceSegment.newBuilder()
                        .setStructField(
                            Expression.ReferenceSegment.StructField.newBuilder().setField(i)))
                .setRootReference(Expression.FieldReference.RootReference.newBuilder()))
        .build();
  }

  static Rel filter(RelCommon.Emit.Builder m) {
    return Rel.newBuilder()
        .setFilter(
            FilterRel.newBuilder()
                .setCommon(RelCommon.newBuilder().setEmit(m))
                .setInput(readMix(null))
                .setCondition(fieldRef(2)))
        .build();
  }

  static Rel sort(RelCommon.Emit.Builder m) {
    return Rel.newBuilder()
        .setSort(
            SortRel.newBuilder()
                .setCommon(RelCommon.newBuilder().setEmit(m))
                .setInput(readMix(null))
                .addSorts(
                    SortField.newBuilder()
                        .setExpr(fieldRef(0))
                        .setDirection(SortField.SortDirection.SORT_DIRECTION_ASC_NULLS_LAST)))
        .build();
  }

  static Rel fetch(RelCommon.Emit.Builder m) {
    return Rel.newBuilder()
        .setFetch(
            FetchRel.newBuilder()
                .setCommon(RelCommon.newBuilder().setEmit(m))
                .setInput(readMix(null))
                .setCountExpr(
                    Expression.newBuilder()
                        .setLiteral(Expression.Literal.newBuilder().setI64(10))))
        .build();
  }

  /** A projection with no new expressions: emit selects from the input columns. */
  static Rel project(RelCommon.Emit.Builder m) {
    return Rel.newBuilder()
        .setProject(
            ProjectRel.newBuilder()
                .setCommon(RelCommon.newBuilder().setEmit(m))
                .setInput(readMix(null))
                .addExpressions(fieldRef(1)))
        .build();
  }

  /** t_mix joined with itself: six input columns, the mapping [2,0] selects bool and i64. */
  static Rel join(RelCommon.Emit.Builder m) {
    return Rel.newBuilder()
        .setJoin(
            JoinRel.newBuilder()
                .setCommon(RelCommon.newBuilder().setEmit(m))
                .setLeft(readMix(null))
                .setRight(readMix(null))
                .setType(JoinRel.JoinType.JOIN_TYPE_INNER)
                .setExpression(
                    Expression.newBuilder()
                        .setLiteral(
                            Expression.Literal.newBuilder().setBoolean(true).setNullable(false))))
        .build();
  }

  /**
   * Grouped on all three columns: the aggregate's output is the same (c0, c1, c2) in the declared
   * order, so the expectation for the mapping [2, 0] is the same as everywhere else.
   */
  static Rel aggregate(RelCommon.Emit.Builder m) {
    return Rel.newBuilder()
        .setAggregate(
            AggregateRel.newBuilder()
                .setCommon(RelCommon.newBuilder().setEmit(m))
                .setInput(readMix(null))
                // The 0.102 encoding: the expressions live in grouping_expressions and a set refers
                // to them by index; Grouping.grouping_expressions is reserved.
                .addGroupingExpressions(fieldRef(0))
                .addGroupingExpressions(fieldRef(1))
                .addGroupingExpressions(fieldRef(2))
                .addGroupings(
                    AggregateRel.Grouping.newBuilder()
                        .addExpressionReferences(0)
                        .addExpressionReferences(1)
                        .addExpressionReferences(2)))
        .build();
  }

  static void emit(String label, Rel rel) throws Exception {
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder().setInput(rel).addAllNames(List.of("k0", "k1"))))
            .build();
    String name = "emit_" + label;
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf("=== %-10s expected [bool, i64], row (true, 10)%n", label);
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
