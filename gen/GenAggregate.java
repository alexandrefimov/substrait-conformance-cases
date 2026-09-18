import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;

/**
 * The shape of an aggregate's output: which columns it has, and in what order.
 *
 * <p>Two sentences of the Aggregate page had no case that could tell them from another reading.
 * "The list of grouping expressions in declaration order followed by the list of measures in
 * declaration order" is the column order, and every aggregate case in the corpus carried either
 * groupings or measures and never both, so nothing here distinguished that order from its reverse.
 * And the `i32` column an aggregate with more than one grouping set receives was cut by the emit
 * mapping in both cases that had two grouping sets, so its presence, its width and its nullability
 * were all unasserted.
 *
 * <p>Neither case sets emit, which is the point of the second one: an emit mapping is what hid the
 * column.
 */
public class GenAggregate {
  static final String URN = "extension:io.substrait:functions_arithmetic";

  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);

    // foo is (a i64 required, b i64 required, c string required): the same leaf the other grouping
    // cases read. Grouping on the string and summing an integer makes the declared order and its
    // reverse produce different schemas, which is what the case is for.
    Rel groupingThenMeasure =
        Rel.newBuilder()
            .setAggregate(
                AggregateRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setInput(foo())
                    .addGroupingExpressions(GenSum.field(2))
                    .addGroupings(AggregateRel.Grouping.newBuilder().addExpressionReferences(0))
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
                                        FunctionArgument.newBuilder().setValue(GenSum.field(0))))))
            .build();
    write(out, "aggregate_grouping_then_measure", plan(groupingThenMeasure, "c", "s"),
        "one grouping expression and one measure, of different types, with emit unset");

    Rel groupingSetIndex =
        Rel.newBuilder()
            .setAggregate(
                AggregateRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setInput(foo())
                    .addGroupingExpressions(GenSum.field(2))
                    .addGroupingExpressions(GenSum.field(0))
                    .addGroupings(AggregateRel.Grouping.newBuilder().addExpressionReferences(0))
                    .addGroupings(AggregateRel.Grouping.newBuilder().addExpressionReferences(1)))
            .build();
    write(out, "aggregate_grouping_set_index", plan(groupingSetIndex, "c", "a", "g"),
        "two grouping sets and emit unset, so the grouping-set index column reaches the output");
  }

  /** The `foo` leaf: (a i64, b i64, c string), all required. Tables.named builds i64 columns only. */
  static Rel foo() {
    Type str =
        Type.newBuilder()
            .setString(Type.String.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED))
            .build();
    NamedStruct schema =
        NamedStruct.newBuilder()
            .addNames("a")
            .addNames("b")
            .addNames("c")
            .setStruct(
                Type.Struct.newBuilder()
                    .setNullability(Type.Nullability.NULLABILITY_REQUIRED)
                    .addTypes(Tables.i64(false))
                    .addTypes(Tables.i64(false))
                    .addTypes(str))
            .build();
    return Rel.newBuilder()
        .setRead(
            ReadRel.newBuilder()
                .setCommon(Tables.direct())
                .setBaseSchema(schema)
                .setNamedTable(ReadRel.NamedTable.newBuilder().addNames("foo")))
        .build();
  }

  static Plan plan(Rel rel, String... names) {
    RelRoot.Builder root = RelRoot.newBuilder().setInput(rel);
    for (String n : names) {
      root.addNames(n);
    }
    return Plan.newBuilder()
        .setVersion(Tables.version())
        .addExtensionUrns(SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(5).setUrn(URN))
        .addExtensions(
            SimpleExtensionDeclaration.newBuilder()
                .setExtensionFunction(
                    SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                        .setFunctionAnchor(5)
                        .setName("sum:i64")
                        .setExtensionUrnReference(5)))
        .addRelations(PlanRel.newBuilder().setRoot(root))
        .build();
  }

  static void write(Path out, String name, Plan plan, String note) throws Exception {
    Files.writeString(out.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf("=== %s  %s%n", name, note);
    try {
      System.out.printf(
          "    substrait-java: %s%n",
          new io.substrait.plan.ProtoPlanConverter().from(plan)
              .getRoots().get(0).getInput().getRecordType());
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println(
          "    substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }
}
