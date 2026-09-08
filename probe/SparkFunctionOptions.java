import com.google.gson.GsonBuilder;
import io.substrait.expression.Expression;
import io.substrait.expression.ExpressionCreator;
import io.substrait.expression.FunctionOption;
import io.substrait.extension.DefaultExtensionCatalog;
import io.substrait.spark.SparkExtension$;
import io.substrait.spark.expression.ToScalarFunction$;
import io.substrait.spark.expression.ToSparkExpression;
import io.substrait.type.TypeCreator;
import io.substrait.util.EmptyVisitationContext;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import org.apache.spark.sql.internal.SQLConf;

/** Evaluates decimal function options through the Spark expression importer, without a session. */
public class SparkFunctionOptions {
  static Map<String, Object> run(String function, boolean overflow, boolean ansi) {
    SQLConf.get().setConfString("spark.sql.ansi.enabled", Boolean.toString(ansi));
    SQLConf.get().setConfString("spark.sql.decimalOperations.allowPrecisionLoss", "true");
    var converter = new ToSparkExpression(
        ToScalarFunction$.MODULE$.apply(SparkExtension$.MODULE$.SparkScalarFunctions()),
        scala.Option.empty());
    var declaration = DefaultExtensionCatalog.DEFAULT_COLLECTION.scalarFunctions().stream()
        .filter(f -> f.key().equals(function + ":dec_dec")).findFirst().orElseThrow();
    int p1 = overflow ? 38 : 10, s1 = overflow ? 0 : 2;
    int p2 = overflow ? 1 : 5, s2 = overflow ? 0 : 1;
    int pr = overflow ? 38 : function.equals("add") ? 11 : 16;
    int sr = overflow ? 0 : function.equals("add") ? 2 : 3;
    String left = overflow ? "99999999999999999999999999999999999999" : "1.00";
    String right = overflow ? (function.equals("add") ? "1" : "2") : "3.0";
    var builder = Expression.ScalarFunctionInvocation.builder()
        .declaration(declaration)
        .outputType(TypeCreator.REQUIRED.decimal(pr, sr))
        .addArguments(ExpressionCreator.decimal(false, new BigDecimal(left), p1, s1),
            ExpressionCreator.decimal(false, new BigDecimal(right), p2, s2));
    if (overflow) {
      builder.addOptions(FunctionOption.builder().name("overflow").addValues("ERROR").build());
    }
    var expression = builder.build();
    Map<String, Object> result = new LinkedHashMap<>();
    result.put("function", function);
    result.put("ansi", ansi);
    result.put("input", overflow ? "overflow" : "safe");
    result.put("options", expression.options().stream()
        .map(option -> Map.of("name", option.getName(), "values", option.values())).toList());
    org.apache.spark.sql.catalyst.expressions.Expression converted;
    try {
      converted = expression.accept(converter, EmptyVisitationContext.INSTANCE);
    } catch (IllegalArgumentException | UnsupportedOperationException e) {
      result.put("status", "rejected");
      result.put("error", e.getClass().getSimpleName());
      return result;
    }
    result.put("type", converted.dataType().simpleString());
    result.put("nullable", converted.nullable());
    try {
      Object value = converted.eval(null); // The expression has only literal inputs.
      result.put("status", "value");
      result.put("value", value == null ? null : value.toString());
    } catch (ArithmeticException e) {
      result.put("status", "overflow_error");
      result.put("error", e.getClass().getSimpleName());
    }
    return result;
  }

  public static void main(String[] args) {
    if (args.length != 0) throw new IllegalArgumentException("No arguments expected");
    var json = new GsonBuilder().serializeNulls().create();
    for (boolean ansi : new boolean[] {false, true}) {
      for (String function : new String[] {"add", "multiply"}) {
        for (boolean overflow : new boolean[] {false, true}) {
          System.out.println(json.toJson(run(function, overflow, ansi)));
        }
      }
    }
  }
}
