import io.substrait.plan.PlanProtoConverter;
import io.substrait.proto.Expression;
import io.substrait.proto.Type;
import io.substrait.spark.logical.ToSubstraitRel;
import java.nio.file.Files;
import org.apache.spark.sql.SparkSession;

/** What Spark as a producer DECLARES in a function call's output_type. */
public class ProducerSpark {
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
        if (o instanceof Expression.ScalarFunction sf)
          out.append("  scalar#").append(sf.getFunctionReference()).append(" -> ")
             .append(t(sf.getOutputType())).append('\n');
        if (o instanceof io.substrait.proto.AggregateFunction af)
          out.append("  aggregate#").append(af.getFunctionReference()).append(" -> ")
             .append(t(af.getOutputType())).append('\n');
        if (o instanceof com.google.protobuf.Message msg) scan(msg, out);
      }
    }
  }

  public static void main(String[] args) throws Exception {
    SparkSession spark = SparkSession.builder().master("local[1]").appName("producer")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.warehouse.dir", Files.createTempDirectory("wh").toString())
        .getOrCreate();
    spark.sparkContext().setLogLevel("ERROR");
    spark.sql("CREATE TABLE t (a DECIMAL(10,2), b DECIMAL(5,1), c DECIMAL(38,10), d DECIMAL(38,10), i BIGINT) USING parquet");
    for (String sql : args) {
      try {
        var plan = new ToSubstraitRel().convert(spark.sql(sql).queryExecution().optimizedPlan());
        var proto = new PlanProtoConverter().toProto(plan);
        StringBuilder out = new StringBuilder();
        scan(proto, out);
        System.out.println("SQL " + sql);
        System.out.print(out.length() == 0 ? "  (no function calls)\n" : out);
        for (var ext : proto.getExtensionsList())
          if (ext.hasExtensionFunction())
            System.out.println("  function#" + ext.getExtensionFunction().getFunctionAnchor()
                + " = " + ext.getExtensionFunction().getName());
      } catch (Throwable e) {
        System.out.println("SQL " + sql + "\n  ERROR: " + e.getClass().getSimpleName() + ": "
            + String.valueOf(e.getMessage()).replace('\n', ' ').substring(0, Math.min(90,
                String.valueOf(e.getMessage()).length())));
      }
    }
    spark.stop();
  }
}
