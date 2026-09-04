import com.google.protobuf.util.JsonFormat;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.List;

/**
 * Cases built straight on the proto, either because substrait-java's POJO layer refuses them --
 * which is the observation itself -- or because they sweep a range the builders do not expose.
 */
public class GenDisputed {
  static Path OUT;

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    virtualTableLiteralTypeDiffersFromSchema();
    virtualTableRowNullabilityDiffersFromSchema();
    precisionTimestampSweep();
  }

  /** Wraps a single-column virtual table around one literal and reports substrait-java's verdict. */
  static void emit(String name, Type colType, Expression.Literal lit, String note) throws Exception {
    ReadRel read =
        ReadRel.newBuilder()
            .setBaseSchema(
                NamedStruct.newBuilder()
                    .addNames("c")
                    .setStruct(
                        Type.Struct.newBuilder()
                            .addTypes(colType)
                            .setNullability(Type.Nullability.NULLABILITY_REQUIRED)))
            .setVirtualTable(
                ReadRel.VirtualTable.newBuilder()
                    .addExpressions(
                        Expression.Nested.Struct.newBuilder()
                            .addFields(Expression.newBuilder().setLiteral(lit))))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setRead(read))
                            .addAllNames(List.of("c"))))
            .build();
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.println("=== " + name + (note.isEmpty() ? "" : "  (" + note + ")"));
    try {
      var pojo = new ProtoPlanConverter().from(plan);
      System.out.println(
          "    substrait-java: ACCEPTED  " + pojo.getRoots().get(0).getInput().getRecordType());
    } catch (RuntimeException e) {
      String m = e.getMessage();
      System.out.println(
          "    substrait-java: REJECTED  " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }

  /** The row's literal is an i8 while the base schema declares the column i32. */
  static void virtualTableLiteralTypeDiffersFromSchema() throws Exception {
    emit(
        "virtual_table_literal_type_differs_from_schema",
        Type.newBuilder()
            .setI32(Type.I32.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED))
            .build(),
        Expression.Literal.newBuilder().setI8(1).setNullable(false).build(),
        "base_schema declares i32, the literal is i8");
  }

  /**
   * The row's literal and its column differ in nullability alone. The spec defines neither
   * direction for a virtual table: {@code ReadRel.VirtualTable} is documented as "A table composed
   * of expressions" and {@code base_schema} carries no comment at all, so whether the two have to
   * agree is left open. Where the spec does rule on the same shape -- {@code DISCRETE} nullability
   * in function binding -- it requires an explicit cast.
   */
  static void virtualTableRowNullabilityDiffersFromSchema() throws Exception {
    emit(
        "virtual_table_row_required_in_nullable_column",
        Type.newBuilder()
            .setI32(Type.I32.newBuilder().setNullability(Type.Nullability.NULLABILITY_NULLABLE))
            .build(),
        Expression.Literal.newBuilder().setI32(1).setNullable(false).build(),
        "base_schema declares i32?, the literal is i32");
    emit(
        "virtual_table_row_nullable_in_required_column",
        Type.newBuilder()
            .setI32(Type.I32.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED))
            .build(),
        Expression.Literal.newBuilder().setI32(1).setNullable(true).build(),
        "base_schema declares i32, the literal is i32?");
    // The direction where taking the row's type costs a guarantee: the column is declared required
    // and the value in it is null.
    emit(
        "virtual_table_row_null_in_required_column",
        Type.newBuilder()
            .setI32(Type.I32.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED))
            .build(),
        Expression.Literal.newBuilder()
            .setNull(
                Type.newBuilder()
                    .setI32(
                        Type.I32.newBuilder()
                            .setNullability(Type.Nullability.NULLABILITY_NULLABLE)))
            .build(),
        "base_schema declares i32, the value is null");
  }

  /**
   * The spec allows any sub-second precision ("0 means seconds, 3 milliseconds, 6 microseconds,
   * 9 nanoseconds, 12 picoseconds"), while Arrow carries only seconds/ms/us/ns. What a consumer
   * does with the values in between is the question.
   */
  static void precisionTimestampSweep() throws Exception {
    for (int p : new int[] {0, 1, 2, 3, 4, 6, 7, 9, 12}) {
      emit(
          String.format("precision_timestamp_p%02d", p),
          Type.newBuilder()
              .setPrecisionTimestamp(
                  Type.PrecisionTimestamp.newBuilder()
                      .setPrecision(p)
                      .setNullability(Type.Nullability.NULLABILITY_REQUIRED))
              .build(),
          Expression.Literal.newBuilder()
              .setPrecisionTimestamp(
                  Expression.Literal.PrecisionTimestamp.newBuilder()
                      .setPrecision(p)
                      // Non-zero low-order digits: a silent rounding of precision shows in the data.
                      .setValue(1234567891L))
              .setNullable(false)
              .build(),
          "precision=" + p);
    }
  }
}
