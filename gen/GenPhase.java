import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;

/**
 * Aggregation phases. functions_arithmetic.yaml declares two different types for avg(i64):
 * {@code return: i64?} for the result and {@code intermediate: STRUCT<i64,i64>} for the intermediate
 * state. So one and the same call must have a different output type depending on the phase - a
 * discriminating case that a single phase cannot catch.
 */
public class GenPhase {
  static Path OUT;
  static final String URN = "extension:io.substrait:functions_arithmetic";

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    emit("final", AggregationPhase.AGGREGATION_PHASE_INITIAL_TO_RESULT, finalType(), "i64?",
        java.util.List.of("r"));
    emit(
        "intermediate",
        AggregationPhase.AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE,
        intermediateType(),
        "STRUCT<i64,i64>",
        // Names in RelRoot are counted by depth: the struct itself plus its two fields.
        java.util.List.of("r", "sum", "count"));
  }

  static Type finalType() {
    return Type.newBuilder()
        .setI64(Type.I64.newBuilder().setNullability(Type.Nullability.NULLABILITY_NULLABLE))
        .build();
  }

  static Type intermediateType() {
    return Type.newBuilder()
        .setStruct(
            Type.Struct.newBuilder()
                .addTypes(Tables.i64(false))
                .addTypes(Tables.i64(false))
                .setNullability(Type.Nullability.NULLABILITY_REQUIRED))
        .build();
  }

  static void emit(
      String label,
      AggregationPhase phase,
      Type outputType,
      String want,
      java.util.List<String> names)
      throws Exception {
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
                                    .setOutputType(outputType)
                                    .setPhase(phase)
                                    .setInvocation(
                                        AggregateFunction.AggregationInvocation
                                            .AGGREGATION_INVOCATION_ALL)
                                    .addArguments(
                                        FunctionArgument.newBuilder()
                                            .setValue(
                                                Expression.newBuilder()
                                                    .setSelection(
                                                        Expression.FieldReference.newBuilder()
                                                            .setDirectReference(
                                                                Expression.ReferenceSegment
                                                                    .newBuilder()
                                                                    .setStructField(
                                                                        Expression.ReferenceSegment
                                                                            .StructField
                                                                            .newBuilder()
                                                                            .setField(0)))
                                                            .setRootReference(
                                                                Expression.FieldReference
                                                                    .RootReference.newBuilder())))))))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(
                SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(5).setUrn(URN))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(5)
                            .setName("avg:i64")
                            .setExtensionUrnReference(5)))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(RelRoot.newBuilder().setInput(agg).addAllNames(names)))
            .build();

    String name = "phase_" + label;
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf("=== %-14s phase %s, the spec expects %s%n", label, phase.name().replace("AGGREGATION_PHASE_", ""), want);
    try {
      System.out.printf(
          "    substrait-java: %s%n",
          new io.substrait.plan.ProtoPlanConverter().from(plan)
              .getRoots().get(0).getInput().getRecordType().fields().get(0));
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println("    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }
}
