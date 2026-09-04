import com.google.protobuf.util.JsonFormat;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.relation.NamedScan;
import io.substrait.relation.Rel;
import io.substrait.spark.ToSparkType$;
import io.substrait.spark.logical.ToLogicalPlan;
import java.nio.file.*;
import java.util.*;
import org.apache.spark.sql.Row;
import org.apache.spark.sql.SparkSession;
import org.apache.spark.sql.types.StructField;
import org.apache.spark.sql.types.StructType;

/**
 * The schema Spark derives for a plan. The named tables are registered as temporary views with
 * exactly the schema the case itself declares: Spark reads a table from the catalog rather than from
 * base_schema, so anything else would compare the wrong thing.
 */
public class SparkSchemaOf {
  static void collect(Rel rel, List<NamedScan> out) {
    if (rel instanceof NamedScan) out.add((NamedScan) rel);
    for (Rel in : rel.getInputs()) collect(in, out);
  }

  public static void main(String[] args) throws Exception {
    SparkSession spark =
        SparkSession.builder().master("local[1]").appName("probe")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.shuffle.partitions", "1")
            .config("spark.sql.ansi.enabled", System.getenv("SPARK_ANSI") != null)
            .getOrCreate();
    spark.sparkContext().setLogLevel("ERROR");
    ToLogicalPlan tlp = new ToLogicalPlan(spark);
    for (String a : args) {
      String name = Paths.get(a).getFileName().toString().replace(".json", "");
      try {
        var b = io.substrait.proto.Plan.newBuilder();
        JsonFormat.parser().merge(Files.readString(Paths.get(a)), b);
        var pojo = new ProtoPlanConverter().from(b.build());
        var root = pojo.getRoots().get(0).getInput();
        List<NamedScan> scans = new ArrayList<>();
        collect(root, scans);
        for (NamedScan ns : scans) {
          StructType st = ToSparkType$.MODULE$.toStructType(ns.getInitialSchema());
          spark.createDataFrame(new ArrayList<Row>(), st)
              .createOrReplaceTempView(ns.getNames().get(ns.getNames().size() - 1));
        }
        var lp = tlp.convert(pojo);
        StringBuilder sb = new StringBuilder();
        for (StructField f : lp.schema().fields()) {
          if (sb.length() > 0) sb.append(", ");
          sb.append(f.name()).append(':').append(f.dataType().simpleString())
              .append(f.nullable() ? "?" : "");
        }
        System.out.printf("%-46s [%s]%n", name, sb);
      } catch (Throwable t) {
        String m = String.valueOf(t.getMessage()).replace('\n', ' ');
        System.out.printf("%-46s ERROR: %s: %s%n", name, t.getClass().getSimpleName(),
            m.length() > 90 ? m.substring(0, 90) : m);
      }
    }
    spark.stop();
  }
}
