import io.substrait.plan.PlanProtoConverter;
import io.substrait.spark.logical.ToSubstraitRel;
import java.nio.file.Files;
import java.nio.file.Path;
import org.apache.spark.sql.SparkSession;

/** Spark (substrait-java's spark module) as a producer, from the optimized plan:
 *  [SPARK_VARIANT=spark-4.0_2.13] bash probe/spark_run.sh producers/SparkProducer.java
 *  <tables.sql> <queries.tsv> <out>. Prints the Spark version last. */
public class SparkProducer {
  public static void main(String[] args) throws Exception {
    SparkSession spark = SparkSession.builder().master("local[1]").appName("producers")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.warehouse.dir", Files.createTempDirectory("wh").toString())
        .getOrCreate();
    spark.sparkContext().setLogLevel("ERROR");
    for (String statement : Files.readAllLines(Path.of(args[0]))) spark.sql(statement);
    Path out = Path.of(args[2]);
    Files.createDirectories(out);
    for (String line : Files.readAllLines(Path.of(args[1]))) {
      if (line.startsWith("#") || line.isBlank()) continue;
      String[] p = line.split("\t");
      try {
        var plan = new ToSubstraitRel().convert(spark.sql(p[1]).queryExecution().optimizedPlan());
        Files.write(out.resolve(p[0] + ".pb"), new PlanProtoConverter().toProto(plan).toByteArray());
      } catch (Throwable e) {
        String first = e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()).split("\n")[0];
        Files.writeString(out.resolve(p[0] + ".err"), first + "\n");
      }
    }
    System.out.println("spark " + spark.version());
    spark.stop();
  }
}
