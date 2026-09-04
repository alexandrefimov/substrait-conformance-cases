import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.*;

/**
 * The executable semantics of the set operations. The spec publishes worked examples with data
 * (Logical Relations / Set Operation Types), so the expected multisets here are not derived by this
 * project but transcribed. Multiplicity is invisible in a schema: MINUS_PRIMARY and
 * MINUS_PRIMARY_ALL give the same output type and differ only in the number of rows.
 *
 * <p>The inputs are virtual tables: the data has to live inside the case.
 */
public class GenSetData {
  record Example(String op, int[] p, int[] s1, int[] s2, int[] expected) {}

  static final List<Example> SPEC =
      List.of(
          new Example("MINUS_PRIMARY", a(1,2,2,3,3,3,4), a(1,2), a(3), a(4)),
          new Example("MINUS_PRIMARY_ALL", a(1,2,2,3,3,3,3), a(1,2,3,4), a(3), a(2,3,3)),
          new Example("MINUS_MULTISET", a(1,2,3,4), a(1,2), a(1,2,3), a(3,4)),
          new Example("INTERSECTION_PRIMARY", a(1,2,2,3,3,3,4), a(1,2,3,5), a(2,3,6), a(1,2,3)),
          new Example("INTERSECTION_MULTISET", a(1,2,3,4), a(2,3), a(3,4), a(3)),
          new Example("INTERSECTION_MULTISET_ALL", a(1,2,2,3,3,3,4), a(1,2,3,3,5), a(2,3,3,6), a(2,3,3)),
          new Example("UNION_DISTINCT", a(1,2,2,3,3,3,4), a(2,3,5), a(1,6), a(1,2,3,4,5,6)),
          new Example("UNION_ALL", a(1,2,2,3,3,3,4), a(2,3,5), a(1,6),
              a(1,2,2,3,3,3,4,2,3,5,1,6)));

  static int[] a(int... v) { return v; }

  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);
    for (Example e : SPEC) build(out, e);
  }

  /** A virtual table of one i64 column holding the given multiset. */
  static Rel input(int[] values) {
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

  static void build(Path out, Example e) throws Exception {
    SetRel set =
        SetRel.newBuilder()
            .setCommon(Tables.direct())
            .addInputs(input(e.p()))
            .addInputs(input(e.s1()))
            .addInputs(input(e.s2()))
            .setOp(SetRel.SetOp.valueOf("SET_OP_" + e.op()))
            .build();
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setSet(set))
                            .addNames("v")))
            .build();
    String name = "setdata_" + e.op().toLowerCase(Locale.ROOT);
    Files.writeString(out.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");
    System.out.printf(
        "=== %-28s p=%s s1=%s s2=%s -> the spec expects %s%n",
        e.op(), Arrays.toString(e.p()), Arrays.toString(e.s1()),
        Arrays.toString(e.s2()), Arrays.toString(e.expected()));
  }
}
