import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.*;

/**
 * Places where the spec narrows nullability: the output is required although the input is nullable.
 * Testing the hypothesis that DataFusion widens correctly but never narrows.
 */
public class GenNarrowing {
  static Path OUT;
  static final String URN = "extension:io.substrait:functions_comparison";

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    // functions_comparison.yaml declares is_null / is_not_null with
    // "return: boolean" and "nullability: DECLARED_OUTPUT" -- required output, nullable input.
    fn("is_null", "is_null:any");
    fn("is_not_null", "is_not_null:any");
    countOverNullable();
  }

  /**
   * functions_aggregate_generic.yaml declares count with "return: i64" and
   * "nullability: DECLARED_OUTPUT" -- a required count over a nullable input. Relation level, but
   * a single input, unlike the grouping-sets and intersection cases.
   */
  static void countOverNullable() throws Exception {
    Rel input = Tables.namedWithCommon("t_xnull", "N");

    Type i64Req =
        Type.newBuilder()
            .setI64(Type.I64.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED))
            .build();

    AggregateRel agg =
        AggregateRel.newBuilder()
            .setCommon(Tables.direct())
            .setInput(input)
            .addMeasures(
                AggregateRel.Measure.newBuilder()
                    .setMeasure(
                        AggregateFunction.newBuilder()
                            .setFunctionReference(3)
                            .setOutputType(i64Req)
                            .setPhase(AggregationPhase.AGGREGATION_PHASE_INITIAL_TO_RESULT)
                            .setInvocation(AggregateFunction.AggregationInvocation.AGGREGATION_INVOCATION_ALL)
                            .addArguments(
                                FunctionArgument.newBuilder()
                                    .setValue(
                                        Expression.newBuilder()
                                            .setSelection(
                                                Expression.FieldReference.newBuilder()
                                                    .setDirectReference(
                                                        Expression.ReferenceSegment.newBuilder()
                                                            .setStructField(
                                                                Expression.ReferenceSegment.StructField
                                                                    .newBuilder()
                                                                    .setField(0)))
                                                    .setRootReference(
                                                        Expression.FieldReference.RootReference
                                                            .newBuilder()))))))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(
                SimpleExtensionURN.newBuilder()
                    .setExtensionUrnAnchor(2)
                    .setUrn("extension:io.substrait:functions_aggregate_generic"))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(3)
                            .setName("count:any")
                            .setExtensionUrnReference(2)))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setAggregate(agg))
                            .addNames("n")))
            .build();

    Files.writeString(
        OUT.resolve("narrowing_count.json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf("=== %-14s the plan declares i64 required over a nullable input%n", "count");
    try {
      io.substrait.plan.Plan pojo = new io.substrait.plan.ProtoPlanConverter().from(plan);
      System.out.printf(
          "    substrait-java: %s%n",
          pojo.getRoots().get(0).getInput().getRecordType().fields().get(0));
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println("    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }

  static Type i64Nullable() {
    return Type.newBuilder()
        .setI64(Type.I64.newBuilder().setNullability(Type.Nullability.NULLABILITY_NULLABLE))
        .build();
  }

  static void fn(String label, String compound) throws Exception {
    Rel input = Tables.namedWithCommon("t_xnull", "N");

    Expression call =
        Expression.newBuilder()
            .setScalarFunction(
                Expression.ScalarFunction.newBuilder()
                    .setFunctionReference(1)
                    // The plan declares the result required, as the extension says it is.
                    .setOutputType(
                        Type.newBuilder()
                            .setBool(
                                Type.Boolean.newBuilder()
                                    .setNullability(Type.Nullability.NULLABILITY_REQUIRED)))
                    .addArguments(
                        FunctionArgument.newBuilder()
                            .setValue(
                                Expression.newBuilder()
                                    .setSelection(
                                        Expression.FieldReference.newBuilder()
                                            .setDirectReference(
                                                Expression.ReferenceSegment.newBuilder()
                                                    .setStructField(
                                                        Expression.ReferenceSegment.StructField
                                                            .newBuilder()
                                                            .setField(0)))
                                            .setRootReference(
                                                Expression.FieldReference.RootReference
                                                    .newBuilder())))))
            .build();

    Rel project =
        Rel.newBuilder()
            .setProject(
                ProjectRel.newBuilder()
                    .setCommon(
                        RelCommon.newBuilder()
                            .setEmit(RelCommon.Emit.newBuilder().addOutputMapping(1)))
                    .setInput(input)
                    .addExpressions(call))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(
                SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(1).setUrn(URN))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(1)
                            .setName(compound)
                            .setExtensionUrnReference(1)))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(RelRoot.newBuilder().setInput(project).addNames("r")))
            .build();

    String name = "narrowing_" + label;
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");

    System.out.printf("=== %-14s the plan declares boolean required%n", label);
    try {
      io.substrait.plan.Plan pojo = new io.substrait.plan.ProtoPlanConverter().from(plan);
      io.substrait.type.Type f =
          pojo.getRoots().get(0).getInput().getRecordType().fields().get(0);
      System.out.printf("    substrait-java: %s%n", f);
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println("    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }
}
