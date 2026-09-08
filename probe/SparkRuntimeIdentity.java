import java.util.LinkedHashMap;
import org.apache.spark.sql.internal.SQLConf;

/** Reports the loaded runtime before the profile overrides ANSI mode. */
public class SparkRuntimeIdentity {
  public static void main(String[] args) {
    var values = new LinkedHashMap<String, Object>();
    values.put("spark", org.apache.spark.package$.MODULE$.SPARK_VERSION());
    values.put("scala", scala.util.Properties.versionNumberString());
    values.put("java", System.getProperty("java.version"));
    values.put("ansi_default", SQLConf.get().ansiEnabled());
    values.put("substrait_spec", io.substrait.SubstraitVersion.VERSION);
    // The runner verifies these locations against its fresh build and resolved dependencies.
    values.put("consumer_loaded_from", io.substrait.spark.expression.ToSparkExpression.class
        .getProtectionDomain().getCodeSource().getLocation().toString());
    values.put("spark_loaded_from", SQLConf.class
        .getProtectionDomain().getCodeSource().getLocation().toString());
    System.out.println(new com.google.gson.Gson().toJson(values));
  }
}
