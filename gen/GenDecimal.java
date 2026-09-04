import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * Derivation of precision/scale in decimal arithmetic. The expectation is not written by hand but
 * computed from the formulas in functions_arithmetic_decimal.yaml (spec 0.102), reproduced in
 * {@link #derive}. The plan carries the computed type in output_type, that is, it declares it; the
 * question is what the consumer derives.
 */
public class GenDecimal {
  static Path OUT;
  static final String URN = "extension:io.substrait:functions_arithmetic_decimal";

  /** The t_dec columns: c0 dec(10,2), c1 dec(5,1), c2 dec(38,10), c3 dec(38,10). */
  static final int[][] COLS = {{10, 2}, {5, 1}, {38, 10}, {38, 10}};

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    emit("add", "add:dec_dec", 0, 1);
    emit("add_overflow", "add:dec_dec", 2, 3);
    emit("multiply", "multiply:dec_dec", 0, 1);
    emit("multiply_overflow", "multiply:dec_dec", 2, 3);
    emit("divide", "divide:dec_dec", 0, 1);
  }

  /** The spec formulas verbatim; the shared borrow tail is the same for all three. */
  static int[] derive(String op, int p1, int s1, int p2, int s2) {
    int initScale, initPrec;
    switch (op) {
      case "add":
        initScale = Math.max(s1, s2);
        initPrec = initScale + Math.max(p1 - s1, p2 - s2) + 1;
        break;
      case "multiply":
        initScale = s1 + s2;
        initPrec = p1 + p2 + 1;
        break;
      case "divide":
        initScale = Math.max(6, s1 + p2 + 1);
        initPrec = p1 - s1 + p2 + initScale;
        break;
      default:
        throw new IllegalArgumentException(op);
    }
    int minScale = Math.min(initScale, 6);
    int delta = initPrec - 38;
    int prec = Math.min(initPrec, 38);
    int scaleAfterBorrow = Math.max(initScale - delta, minScale);
    int scale = initPrec > 38 ? scaleAfterBorrow : initScale;
    return new int[] {prec, scale};
  }

  static Type dec(int p, int s) {
    return Type.newBuilder()
        .setDecimal(
            Type.Decimal.newBuilder()
                .setPrecision(p)
                .setScale(s)
                .setNullability(Type.Nullability.NULLABILITY_REQUIRED))
        .build();
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

  static void emit(String label, String compound, int a, int b) throws Exception {
    String op = compound.substring(0, compound.indexOf(':'));
    int[] want = derive(op, COLS[a][0], COLS[a][1], COLS[b][0], COLS[b][1]);

    NamedStruct.Builder schema = NamedStruct.newBuilder();
    Type.Struct.Builder st =
        Type.Struct.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED);
    for (int i = 0; i < COLS.length; i++) {
      schema.addNames("c" + i);
      st.addTypes(dec(COLS[i][0], COLS[i][1]));
    }
    Rel read =
        Rel.newBuilder()
            .setRead(
                ReadRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setBaseSchema(schema.setStruct(st))
                    .setNamedTable(ReadRel.NamedTable.newBuilder().addNames("t_dec")))
            .build();

    Rel project =
        Rel.newBuilder()
            .setProject(
                ProjectRel.newBuilder()
                    .setCommon(
                        RelCommon.newBuilder()
                            .setEmit(RelCommon.Emit.newBuilder().addOutputMapping(COLS.length)))
                    .setInput(read)
                    .addExpressions(
                        Expression.newBuilder()
                            .setScalarFunction(
                                Expression.ScalarFunction.newBuilder()
                                    .setFunctionReference(7)
                                    .setOutputType(dec(want[0], want[1]))
                                    .addArguments(
                                        FunctionArgument.newBuilder().setValue(fieldRef(a)))
                                    .addArguments(
                                        FunctionArgument.newBuilder().setValue(fieldRef(b))))))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addExtensionUrns(
                SimpleExtensionURN.newBuilder().setExtensionUrnAnchor(7).setUrn(URN))
            .addExtensions(
                SimpleExtensionDeclaration.newBuilder()
                    .setExtensionFunction(
                        SimpleExtensionDeclaration.ExtensionFunction.newBuilder()
                            .setFunctionAnchor(7)
                            .setName(compound)
                            .setExtensionUrnReference(7)))
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(RelRoot.newBuilder().setInput(project).addNames("r")))
            .build();

    String name = "decimal_" + label;
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf(
        "=== %-18s dec(%d,%d) %s dec(%d,%d) -> spec: DECIMAL(%d,%d)%n",
        label, COLS[a][0], COLS[a][1], op, COLS[b][0], COLS[b][1], want[0], want[1]);
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
