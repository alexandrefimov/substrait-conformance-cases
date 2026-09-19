import io.substrait.plan.PlanProtoConverter;
import io.substrait.spark.logical.ToSubstraitRel;
import java.nio.file.Files;
import java.nio.file.Path;
import org.apache.spark.sql.SparkSession;

/** Spark (substrait-java's spark module) as a producer, from the optimized plan:
 *  bash probe/spark_run.sh ShapesSpark <queries.tsv> <out>. */
public class ShapesSpark {
  public static void main(String[] args) throws Exception {
    SparkSession spark = SparkSession.builder().master("local[1]").appName("shapes")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.warehouse.dir", Files.createTempDirectory("wh").toString())
        .getOrCreate();
    spark.sparkContext().setLogLevel("ERROR");
    for (String ddl : new String[] {
        "CREATE TABLE t_rn (c0 BIGINT NOT NULL, c1 BIGINT) USING parquet",
        "CREATE TABLE t_nr (c0 BIGINT, c1 BIGINT NOT NULL) USING parquet",
        "CREATE TABLE t_mix (c0 BIGINT NOT NULL, c1 STRING NOT NULL, c2 BOOLEAN NOT NULL) USING parquet",
        "CREATE TABLE t_ts (ts TIMESTAMP NOT NULL) USING parquet",
        "CREATE TABLE t_dec (a DECIMAL(10,2) NOT NULL, b DECIMAL(5,1) NOT NULL) USING parquet"})
      spark.sql(ddl);
    Path out = Path.of(args[1]);
    Files.createDirectories(out);
    for (String line : Files.readAllLines(Path.of(args[0]))) {
      String[] p = line.split("\t", 2);
      try {
        var plan = new ToSubstraitRel().convert(spark.sql(p[1]).queryExecution().optimizedPlan());
        Files.write(out.resolve(p[0] + ".pb"), new PlanProtoConverter().toProto(plan).toByteArray());
        System.out.println(p[0] + " written");
      } catch (Throwable e) {
        String first = e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()).split("\n")[0];
        Files.writeString(out.resolve(p[0] + ".err"), first + "\n");
        System.out.println(p[0] + " refused: " + first);
      }
    }
    System.out.println("spark " + spark.version());
    spark.stop();
  }
}
