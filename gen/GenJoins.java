import com.google.protobuf.util.JsonFormat;
import io.substrait.extension.ExtensionCollector;
import io.substrait.proto.*;
import io.substrait.relation.ProtoRelConverter;
import java.nio.file.*;
import java.util.*;

/**
 * Nullability of a join's output per join type. The spec does not publish a table here as it does
 * for set operations, but the semantics are unambiguous: a join returns "the record from the
 * corresponding input along with nulls for the opposite input", so the opposite side's columns
 * become nullable. Left and right inputs are both (required i64, nullable i64).
 */
public class GenJoins {
  static Path OUT;

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    for (JoinRel.JoinType t : JoinRel.JoinType.values()) {
      if (t == JoinRel.JoinType.UNRECOGNIZED || t == JoinRel.JoinType.JOIN_TYPE_UNSPECIFIED) {
        continue;
      }
      // Two forms of the same case: with a true literal (the spec allows it; Acero rejects it) and
      // with an equality (the only form Acero accepts - otherwise there is nothing to compare it on).
      run(t, false);
      run(t, true);
    }
  }

  /** equal(left.c0, right.c0); the field indexes are into the concatenated input. */
  static Expression equality() {
    return Expression.newBuilder()
        .setScalarFunction(
            Expression.ScalarFunction.newBuilder()
                .setFunctionReference(9)
                .setOutputType(
                    Type.newBuilder()
                        .setBool(
                            Type.Boolean.newBuilder()
                                .setNullability(Type.Nullability.NULLABILITY_NULLABLE)))
                .addArguments(fieldArg(0))
                .addArguments(fieldArg(2)))
        .build();
  }

  static FunctionArgument fieldArg(int index) {
    return FunctionArgument.newBuilder()
        .setValue(
            Expression.newBuilder()
                .setSelection(
                    Expression.FieldReference.newBuilder()
                        .setDirectReference(
                            Expression.ReferenceSegment.newBuilder()
                                .setStructField(
                                    Expression.ReferenceSegment.StructField.newBuilder()
                                        .setField(index)))
                        .setRootReference(
                            Expression.FieldReference.RootReference.newBuilder())))
        .build();
  }

  @SuppressWarnings("unused")
  static Type i64(boolean nullable) {
    return Type.newBuilder()
        .setI64(
            Type.I64.newBuilder()
                .setNullability(
                    nullable
                        ? Type.Nullability.NULLABILITY_NULLABLE
                        : Type.Nullability.NULLABILITY_REQUIRED))
        .build();
  }

  static void run(JoinRel.JoinType type, boolean withEquality) throws Exception {
    Rel join =
        Rel.newBuilder()
            .setJoin(
                JoinRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setLeft(Tables.namedWithCommon("t_rn", "RN"))
                    .setRight(Tables.namedWithCommon("t_nr", "NR"))
                    .setType(type)
                    .setExpression(
                        withEquality
                            ? equality()
                            : Expression.newBuilder()
                                .setLiteral(
                                    Expression.Literal.newBuilder()
                                        .setBoolean(true)
                                        .setNullable(false))
                                .build()))
            .build();

    String label = type.name().replace("JOIN_TYPE_", "");
    String name = (withEquality ? "joineq_" : "join_") + label.toLowerCase(Locale.ROOT);
    System.out.printf("=== %-8s %-14s", withEquality ? "equality" : "true", label);

    int arity = arityOf(type);

    List<String> names = new ArrayList<>();
    for (int i = 0; i < arity; i++) names.add("c" + i);
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(
                SimpleExtensionURN.newBuilder()
                    .setExtensionUrnAnchor(9)
                    .setUrn("extension:io.substrait:functions_comparison"))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(9)
                            .setName("equal:any_any")
                            .setExtensionUrnReference(9)))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(RelRoot.newBuilder().setInput(join).addAllNames(names)))
            .build();
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");

    try {
      io.substrait.plan.Plan pojo = new io.substrait.plan.ProtoPlanConverter().from(plan);
      StringBuilder sb = new StringBuilder();
      for (io.substrait.type.Type f :
          pojo.getRoots().get(0).getInput().getRecordType().fields()) {
        sb.append(f.nullable() ? 'N' : 'R');
      }
      System.out.printf(" substrait-java: %-6s (%d columns)%n", sb, sb.length());
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println(" substrait-java REJECTED: " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }

  /** Output arity by join type: semi/anti give one side, mark one side plus the mark column. */
  static int arityOf(JoinRel.JoinType t) {
    switch (t) {
      case JOIN_TYPE_LEFT_SEMI:
      case JOIN_TYPE_LEFT_ANTI:
      case JOIN_TYPE_RIGHT_SEMI:
      case JOIN_TYPE_RIGHT_ANTI:
        return 2;
      case JOIN_TYPE_LEFT_MARK:
      case JOIN_TYPE_RIGHT_MARK:
        return 3;
      default:
        return 4;
    }
  }
}
