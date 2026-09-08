import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * The window relation, asked two things.
 *
 * <p><b>What its output is.</b> The spec's Consistent Partition Window Operation gives "Direct
 * Output Order: same as Project operator (input followed by each window expression)", so the schema
 * is the input's fields and then one per window function, in the order they are declared. The order
 * and the count are derivable; the type of each added column is not, because
 * ConsistentPartitionWindow.deriveRecordType takes the declared output_type of the invocation - a
 * match on that half is the same calibration the decimal cases carry.
 *
 * <p><b>Which encoding of a frame bound it reads.</b> Bound.Preceding carries a deprecated int64
 * offset and an offset_expr, and the spec is imperative about them: "Consumers must use offset_expr
 * when it is set and ignore offset." Either field alone is a legal plan, so the two written here
 * describe one frame twice and their schemas and rows are identical. A consumer reading only one of
 * the two answers one of the plans wrongly - and because an absent offset reads as zero rather than
 * as absent, it does so with no error at all.
 *
 * <p>The frame is ROWS BETWEEN 1 PRECEDING AND CURRENT ROW over the rows 1, 2, 3, 4 of a virtual
 * table, so the sums are 1, 3, 5, 7 and anyone can check them without this file. row_number and
 * cume_dist could not carry the pair: the extension declares them window_type PARTITION, which is
 * the whole partition and no frame.
 */
public class GenWindow {
  static Path OUT;
  static final String URN = "extension:io.substrait:functions_arithmetic";

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    outputOrder();
    bound("bound_offset", false);
    bound("bound_offset_expr", true);
  }

  /** A window over t_mix with two functions of different declared types, so order and count show. */
  static void outputOrder() throws Exception {
    ConsistentPartitionWindowRel win =
        ConsistentPartitionWindowRel.newBuilder()
            .setCommon(Tables.direct())
            .setInput(
                Rel.newBuilder()
                    .setRead(
                        ReadRel.newBuilder()
                            .setCommon(Tables.direct())
                            .setBaseSchema(GenEmit.mixSchema())
                            .setNamedTable(ReadRel.NamedTable.newBuilder().addNames("t_mix"))))
            // The types the extension declares for these two: row_number i64?, cume_dist fp64?.
            // A plan declaring anything else would make the case about a false declaration, which
            // is what probe/lie_matrix.sh is for.
            .addWindowFunctions(windowFn(1, type(true, true)))
            .addWindowFunctions(windowFn(2, type(false, true)))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(1).setUrn(URN))
            .addExtensions(declare(1, "row_number:"))
            .addExtensions(declare(2, "cume_dist:"))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setWindow(win))
                            .addAllNames(List.of("c0", "c1", "c2", "rn", "cd"))))
            .build();
    write("window_output_order", plan,
        "output_order  the input's three columns, then row_number and cume_dist in that order");
  }

  /** The same frame written twice: through the deprecated offset, and through offset_expr. */
  static void bound(String label, boolean expr) throws Exception {
    Expression.WindowFunction.Bound.Preceding.Builder lower =
        Expression.WindowFunction.Bound.Preceding.newBuilder();
    if (expr) {
      lower.setOffsetExpr(
          Expression.newBuilder()
              .setLiteral(Expression.Literal.newBuilder().setI64(1).setNullable(false)));
    } else {
      lower.setOffset(1);
    }
    ConsistentPartitionWindowRel win =
        ConsistentPartitionWindowRel.newBuilder()
            .setCommon(Tables.direct())
            .setInput(rows(1, 2, 3, 4))
            .addWindowFunctions(
                ConsistentPartitionWindowRel.WindowRelFunction.newBuilder()
                    .setFunctionReference(1)
                    .addArguments(FunctionArgument.newBuilder().setValue(field(0)))
                    .setOutputType(type(true, true))
                    .setPhase(AggregationPhase.AGGREGATION_PHASE_INITIAL_TO_RESULT)
                    .setInvocation(AggregateFunction.AggregationInvocation.AGGREGATION_INVOCATION_ALL)
                    .setBoundsType(Expression.WindowFunction.BoundsType.BOUNDS_TYPE_ROWS)
                    .setLowerBound(
                        Expression.WindowFunction.Bound.newBuilder().setPreceding(lower))
                    .setUpperBound(
                        Expression.WindowFunction.Bound.newBuilder()
                            .setCurrentRow(
                                Expression.WindowFunction.Bound.CurrentRow.getDefaultInstance())))
            .addSorts(
                SortField.newBuilder()
                    .setExpr(field(0))
                    .setDirection(SortField.SortDirection.SORT_DIRECTION_ASC_NULLS_LAST))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(1).setUrn(URN))
            .addExtensions(declare(1, "sum:i64"))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setWindow(win))
                            .addAllNames(List.of("v", "s"))))
            .build();
    write("window_" + label, plan,
        label + "  ROWS 1 PRECEDING to CURRENT ROW over 1,2,3,4 written through "
            + (expr ? "offset_expr" : "the deprecated offset") + "; sums 1,3,5,7");
  }

  static Rel rows(int... values) {
    ReadRel.VirtualTable.Builder vt = ReadRel.VirtualTable.newBuilder();
    for (int v : values) {
      vt.addExpressions(
          Expression.Nested.Struct.newBuilder()
              .addFields(
                  Expression.newBuilder()
                      .setLiteral(Expression.Literal.newBuilder().setI64(v).setNullable(false))));
    }
    return Rel.newBuilder()
        .setRead(
            ReadRel.newBuilder()
                .setCommon(Tables.direct())
                .setBaseSchema(
                    NamedStruct.newBuilder()
                        .addNames("v")
                        .setStruct(
                            Type.Struct.newBuilder()
                                .addTypes(Tables.i64(false))
                                .setNullability(Type.Nullability.NULLABILITY_REQUIRED)))
                .setVirtualTable(vt))
        .build();
  }

  static ConsistentPartitionWindowRel.WindowRelFunction windowFn(int anchor, Type out) {
    return ConsistentPartitionWindowRel.WindowRelFunction.newBuilder()
        .setFunctionReference(anchor)
        .setOutputType(out)
        .setPhase(AggregationPhase.AGGREGATION_PHASE_INITIAL_TO_RESULT)
        .setInvocation(AggregateFunction.AggregationInvocation.AGGREGATION_INVOCATION_ALL)
        .build();
  }

  static SimpleExtensionDeclaration declare(int anchor, String name) {
    return SimpleExtensionDeclaration.newBuilder()
        .setExtensionFunction(
            SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                .setFunctionAnchor(anchor)
                .setName(name)
                .setExtensionUrnReference(1))
        .build();
  }

  /** i64 when i64 is true, fp64 otherwise; nullable as the extension declares these returns. */
  static Type type(boolean isI64, boolean nullable) {
    Type.Nullability n =
        nullable ? Type.Nullability.NULLABILITY_NULLABLE : Type.Nullability.NULLABILITY_REQUIRED;
    return isI64
        ? Type.newBuilder().setI64(Type.I64.newBuilder().setNullability(n)).build()
        : Type.newBuilder().setFp64(Type.FP64.newBuilder().setNullability(n)).build();
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

  static void write(String name, Plan plan, String note) throws Exception {
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
