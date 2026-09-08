import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;

/**
 * A plain aggregate over an integer column. functions_arithmetic.yaml declares sum(i64) as
 * {@code return: i64?} with {@code nullability: DECLARED_OUTPUT}, so the type the plan carries in
 * output_type is the answer, and a consumer that binds its own wider accumulator returns a type the
 * plan never asked for. The window relation reaches the same call, but only where the engine's
 * window support is in play; this case separates the two.
 */
public class GenSum {
  static final String URN = "extension:io.substrait:functions_arithmetic";

  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);

    Rel agg =
        Rel.newBuilder()
            .setAggregate(
                AggregateRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setInput(Tables.namedWithCommon("t_avg", "RR"))
                    .addMeasures(
                        AggregateRel.Measure.newBuilder()
                            .setMeasure(
                                AggregateFunction.newBuilder()
                                    .setFunctionReference(5)
                                    .setOutputType(Tables.i64(true))
                                    .setPhase(AggregationPhase.AGGREGATION_PHASE_INITIAL_TO_RESULT)
                                    .setInvocation(
                                        AggregateFunction.AggregationInvocation
                                            .AGGREGATION_INVOCATION_ALL)
                                    .addArguments(
                                        FunctionArgument.newBuilder().setValue(field(0))))))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(5).setUrn(URN))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(5)
                            .setName("sum:i64")
                            .setExtensionUrnReference(5)))
            .addRelations(
                PlanRel.newBuilder().setRoot(RelRoot.newBuilder().setInput(agg).addNames("s")))
            .build();

    Files.writeString(out.resolve("aggregate_sum_i64.json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf(
        "=== %-18s sum:i64 over a required i64 column, the spec expects i64?%n",
        "aggregate_sum_i64");
    try {
      System.out.printf(
          "    substrait-java: %s%n",
          new io.substrait.plan.ProtoPlanConverter().from(plan)
              .getRoots().get(0).getInput().getRecordType().fields().get(0));
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println(
          "    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }

  static Expression field(int i) {
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
}
