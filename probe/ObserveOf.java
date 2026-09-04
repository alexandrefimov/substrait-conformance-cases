import com.google.protobuf.util.JsonFormat;
import io.substrait.isthmus.ConverterProvider;
import io.substrait.isthmus.SubstraitToCalcite;
import io.substrait.isthmus.expression.TypeObserver;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.isthmus.TypeConverter;
import java.nio.file.*;

/** Whether Isthmus notices a declared type diverging from what Calcite derives. */
public class ObserveOf {
  public static void main(String[] args) throws Exception {
    for (String a : args) {
      String name = Paths.get(a).getFileName().toString().replace(".json", "");
      var counts = new int[] {0, 0, 0};   // total, divergences, failures to derive
      var report = new StringBuilder();
      TypeObserver obs =
          o -> {
            counts[0]++;
            if (o.inferenceFailure().isPresent()) {
              counts[2]++;
              return;
            }
            o.inferredType()
                .ifPresent(
                    inferred -> {
                      var suppliedCalcite =
                          TypeConverter.DEFAULT.toCalcite(
                              ConverterProvider.DEFAULT.getTypeFactory(), o.suppliedType());
                      if (!suppliedCalcite.equals(inferred)) {
                        counts[1]++;
                        report.append(
                            String.format("      declared %s, Calcite derived %s%n",
                                suppliedCalcite, inferred));
                      }
                    });
          };
      var provider = ConverterProvider.builder().typeObserver(obs).build();
      var s2c = new SubstraitToCalcite(provider);
      var b = io.substrait.proto.Plan.newBuilder();
      JsonFormat.parser().merge(Files.readString(Paths.get(a)), b);
      var rel = new ProtoPlanConverter().from(b.build()).getRoots().get(0).getInput();
      s2c.convert(rel);
      System.out.printf("%-22s observations %d, divergences %d, derivation failed %d%n",
          name, counts[0], counts[1], counts[2]);
      System.out.print(report);
    }
  }
}
