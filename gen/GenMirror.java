import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;

/**
 * MIRROR nullability, which is the default for every function the specification declares and was
 * asserted by nothing here.
 *
 * <p>scalar_functions.md: "if at least one of the input arguments are nullable, the return type is
 * also nullable. If all arguments are non-nullable, the return type will be non-nullable."
 * functions_arithmetic.yaml declares add(i64, i64) with no nullability key, so it takes that
 * default. Every MIRROR call already in the corpus either reads required decimal columns - where
 * mirroring and ignoring the arguments give the same answer - or sits in a join predicate whose
 * type never reaches the output schema.
 *
 * <p>One case, two calls over the same leaf: add(c0, c0) over two required columns and
 * add(c0, c1) where c1 is nullable. Both directions of the rule are in one output, so a consumer
 * that drops the rule and one that applies it unconditionally both differ from the expectation.
 */
public class GenMirror {
  static final String URN = "extension:io.substrait:functions_arithmetic";

  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);

    // t_rn is (c0 i64 required, c1 i64 nullable).
    Rel project =
        Rel.newBuilder()
            .setProject(
                ProjectRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setInput(Tables.namedWithCommon("t_rn", "RN"))
                    .addExpressions(add(0, 0, false))
                    .addExpressions(add(0, 1, true)))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(6).setUrn(URN))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(6)
                            .setName("add:i64_i64")
                            .setExtensionUrnReference(6)))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(project)
                            .addNames("c0")
                            .addNames("c1")
                            .addNames("rr")
                            .addNames("rn")))
            .build();

    String name = "mirror_argument_nullability";
    Files.writeString(out.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf(
        "=== %s  add:i64_i64 over (required, required) and over (required, nullable)%n", name);
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

  /** add(field(x), field(y)), declaring the return type the MIRROR rule gives it. */
  static Expression add(int x, int y, boolean nullable) {
    return Expression.newBuilder()
        .setScalarFunction(
            Expression.ScalarFunction.newBuilder()
                .setFunctionReference(6)
                .setOutputType(Tables.i64(nullable))
                .addArguments(FunctionArgument.newBuilder().setValue(GenSum.field(x)))
                .addArguments(FunctionArgument.newBuilder().setValue(GenSum.field(y))))
        .build();
  }
}
