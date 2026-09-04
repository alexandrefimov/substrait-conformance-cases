import com.google.protobuf.util.JsonFormat;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.spark.logical.ToLogicalPlan;
import java.nio.file.*;
import org.apache.spark.sql.SparkSession;

/** One self-joining plan against three ways of introducing the name "t". */
public class ViewVsTable {
  public static void main(String[] args) throws Exception {
    for (String mode : new String[] {"empty view", "non-empty view", "catalog table"}) {
      SparkSession spark = SparkSession.builder().master("local[1]").appName("m" + mode.hashCode())
          .config("spark.ui.enabled", "false")
          .config("spark.sql.warehouse.dir", Files.createTempDirectory("wh").toString())
          .getOrCreate();
      spark.sparkContext().setLogLevel("ERROR");
      spark.sql("DROP TABLE IF EXISTS t");
      spark.catalog().dropTempView("t");
      if (mode.equals("empty view")) {
        spark.createDataFrame(new java.util.ArrayList<org.apache.spark.sql.Row>(),
            new org.apache.spark.sql.types.StructType()
                .add("a", org.apache.spark.sql.types.DataTypes.LongType, false))
            .createOrReplaceTempView("t");
      } else if (mode.equals("non-empty view")) {
        spark.range(3).selectExpr("id as a").createOrReplaceTempView("t");
      } else {
        spark.sql("CREATE TABLE t (a BIGINT) USING parquet");
      }
      var b = io.substrait.proto.Plan.newBuilder();
      JsonFormat.parser().merge(Files.readString(Paths.get(args[0])), b);
      var pojo = new ProtoPlanConverter().from(b.build());
      try {
        var lp = new ToLogicalPlan(spark).convert(pojo);
        System.out.printf("%-24s -> %s%n", mode, lp.schema().catalogString());
      } catch (Throwable t) {
        System.out.printf("%-24s -> %s: %s%n", mode, t.getClass().getSimpleName(), t.getMessage());
      }
      spark.stop();
      org.apache.spark.sql.SparkSession.clearActiveSession();
      org.apache.spark.sql.SparkSession.clearDefaultSession();
    }
  }
}
