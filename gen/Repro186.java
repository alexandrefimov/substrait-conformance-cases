import io.substrait.isthmus.ConverterProvider;
import io.substrait.isthmus.SubstraitToCalcite;
import io.substrait.proto.*;
import java.util.List;

/**
 * Reproduces a known substrait-java issue: converting a SetRel to Calcite when the inputs differ in
 * nullability. For MINUS_* the spec gives the primary input's nullability; Calcite derives the
 * least-restrictive one. Primary required, secondary nullable -> the rules disagree.
 */
public class Repro186 {
  static Type i64(boolean n) {
    return Type.newBuilder()
        .setI64(Type.I64.newBuilder().setNullability(
            n ? Type.Nullability.NULLABILITY_NULLABLE : Type.Nullability.NULLABILITY_REQUIRED))
        .build();
  }

  static Rel scan(String table, boolean nullable) {
    return Rel.newBuilder()
        .setRead(ReadRel.newBuilder()
            .setCommon(RelCommon.newBuilder().setDirect(RelCommon.Direct.newBuilder()))
            .setBaseSchema(NamedStruct.newBuilder().addNames("v")
                .setStruct(Type.Struct.newBuilder().addTypes(i64(nullable))
                    .setNullability(Type.Nullability.NULLABILITY_REQUIRED)))
            .setNamedTable(ReadRel.NamedTable.newBuilder().addNames(table)))
        .build();
  }

  public static void main(String[] args) throws Exception {
    for (SetRel.SetOp op : new SetRel.SetOp[] {
        SetRel.SetOp.SET_OP_MINUS_PRIMARY,
        SetRel.SetOp.SET_OP_INTERSECTION_MULTISET,
        SetRel.SetOp.SET_OP_UNION_ALL}) {
      SetRel set = SetRel.newBuilder()
          .setCommon(RelCommon.newBuilder().setDirect(RelCommon.Direct.newBuilder()))
          .addInputs(scan("t_req", false))
          .addInputs(scan("t_null", true))
          .setOp(op).build();
      Plan plan = Plan.newBuilder()
          .setVersion(Version.newBuilder().setMinorNumber(102).setProducer("repro"))
          .addRelations(PlanRel.newBuilder().setRoot(
              RelRoot.newBuilder().setInput(Rel.newBuilder().setSet(set)).addAllNames(List.of("v"))))
          .build();

      io.substrait.plan.Plan pojo = new io.substrait.plan.ProtoPlanConverter().from(plan);
      io.substrait.relation.Rel rel = pojo.getRoots().get(0).getInput();
      System.out.printf("=== %-26s substrait: %s%n",
          op.name().replace("SET_OP_", ""), rel.getRecordType());
      try {
        var node = new SubstraitToCalcite(new ConverterProvider()).convert(rel);
        var f = node.getRowType().getFieldList().get(0);
        System.out.printf("    Calcite: OK, %s nullable=%s   %s%n",
            f.getType().getSqlTypeName(), f.getType().isNullable(),
            rel.getRecordType().fields().get(0).nullable() == f.getType().isNullable()
                ? "matches" : "<<< DIVERGES");
        var back = io.substrait.isthmus.SubstraitRelVisitor.convert(
            node, new ConverterProvider().getExtensions());
        System.out.printf("    back:    %s   %s%n", back.getRecordType(),
            back.getRecordType().equals(rel.getRecordType())
                ? "the round trip closed" : "<<< THE ROUND TRIP LOST THE TYPE");
      } catch (Throwable t) {
        String m = t.getMessage();
        System.out.printf("    Calcite: %s — %s%n", t.getClass().getSimpleName(),
            m == null ? "" : m.replace("\n", " ").substring(0, Math.min(140, m.length())));
      }
    }
  }
}
