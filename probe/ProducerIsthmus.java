import io.substrait.isthmus.SqlToSubstrait;
import io.substrait.isthmus.sql.SubstraitCreateStatementParser;
import io.substrait.plan.PlanProtoConverter;
import io.substrait.proto.Expression;
import io.substrait.proto.Plan;
import io.substrait.proto.Rel;
import io.substrait.proto.Type;

/**
 * What Isthmus DECLARES when it produces a plan from SQL: the type it puts into a function call's
 * output_type. A separate question from what consumers then derive.
 */
public class ProducerIsthmus {
  static String t(Type t) {
    return switch (t.getKindCase()) {
      case DECIMAL -> "dec(" + t.getDecimal().getPrecision() + "," + t.getDecimal().getScale() + ")"
          + (t.getDecimal().getNullability() == Type.Nullability.NULLABILITY_NULLABLE ? "?" : "");
      case I64 -> "i64" + (t.getI64().getNullability() == Type.Nullability.NULLABILITY_NULLABLE ? "?" : "");
      case FP64 -> "fp64" + (t.getFp64().getNullability() == Type.Nullability.NULLABILITY_NULLABLE ? "?" : "");
      default -> t.getKindCase().toString().toLowerCase();
    };
  }

  static void scan(com.google.protobuf.Message m, StringBuilder out) {
    for (var e : m.getAllFields().entrySet()) {
      Object v = e.getValue();
      java.util.List<?> items = v instanceof java.util.List<?> l ? l : java.util.List.of(v);
      for (Object o : items) {
        if (o instanceof Expression.ScalarFunction sf) {
          out.append("  scalar#").append(sf.getFunctionReference())
             .append(" -> ").append(t(sf.getOutputType())).append('\n');
        }
        if (o instanceof com.google.protobuf.Message msg) scan(msg, out);
      }
    }
  }

  /** Where SUBSTRAIT_PLANS_OUT asks for it, the plan is kept, named the way datafusion_producer_probe.rs names its own. */
  static void keep(String sql, com.google.protobuf.Message proto) throws java.io.IOException {
    String dir = System.getenv("SUBSTRAIT_PLANS_OUT");
    if (dir == null || dir.isEmpty()) return;
    String name = sql.replace("SELECT ", "").replace(" FROM t", "").replace(' ', '_')
        .replace("+", "add").replace("*", "mul").replace("/", "div").replace("(", "_").replace(")", "");
    java.nio.file.Path d = java.nio.file.Path.of(dir);
    java.nio.file.Files.createDirectories(d);
    java.nio.file.Files.write(d.resolve(name + ".pb"), proto.toByteArray());
  }

  public static void main(String[] args) throws Exception {
    String ddl = args[0];
    var catalog = SubstraitCreateStatementParser.processCreateStatementsToCatalog(ddl);
    var s2s = new SqlToSubstrait();
    for (int i = 1; i < args.length; i++) {
      String sql = args[i];
      try {
        Plan proto = new PlanProtoConverter().toProto(s2s.convert(sql, catalog));
        keep(sql, proto);
        StringBuilder out = new StringBuilder();
        scan(proto, out);
        System.out.println("SQL " + sql);
        System.out.print(out.length() == 0 ? "  (no function calls)\n" : out);
        var names = proto.getRelations(0).getRoot().getNamesList();
        System.out.println("  root: " + names);
      } catch (Throwable e) {
        System.out.println("SQL " + sql + "\n  ERROR: " + e.getClass().getSimpleName() + ": "
            + String.valueOf(e.getMessage()).replace('\n', ' '));
      }
    }
  }
}
