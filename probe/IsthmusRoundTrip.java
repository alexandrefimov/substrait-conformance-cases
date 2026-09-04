import com.google.protobuf.util.JsonFormat;
import io.substrait.isthmus.ConverterProvider;
import io.substrait.isthmus.SubstraitRelVisitor;
import io.substrait.isthmus.SubstraitToCalcite;
import io.substrait.plan.ProtoPlanConverter;
import java.nio.file.*;

/**
 * The round trip Substrait -> Calcite -> Substrait: what the incoming plan declares, and what the
 * plan converted back out of the same Calcite tree declares. A difference here is what Isthmus as a
 * producer will write into someone else's plan, not only what it derives for itself.
 */
public class IsthmusRoundTrip {
  public static void main(String[] args) throws Exception {
    var s2c = new SubstraitToCalcite(ConverterProvider.DEFAULT);
    for (String a : args) {
      String name = Paths.get(a).getFileName().toString().replace(".json", "");
      try {
        var b = io.substrait.proto.Plan.newBuilder();
        JsonFormat.parser().merge(Files.readString(Paths.get(a)), b);
        var rel = new ProtoPlanConverter().from(b.build()).getRoots().get(0).getInput();
        var back = SubstraitRelVisitor.convert(s2c.convert(rel), ConverterProvider.DEFAULT);
        System.out.printf("%-40s in:         %s%n", name, nulls(rel.getRecordType()));
        System.out.printf("%-40s round trip: %s%n", "", nulls(back.getRecordType()));
      } catch (Exception e) {
        System.out.printf("%-40s ERROR %s: %s%n", name, e.getClass().getSimpleName(),
            String.valueOf(e.getMessage()).replace('\n', ' '));
      }
    }
  }

  static String nulls(io.substrait.type.Type t) {
    var sb = new StringBuilder();
    for (io.substrait.type.Type f : ((io.substrait.type.Type.Struct) t).fields()) {
      sb.append(f.nullable() ? 'N' : 'R');
    }
    return sb.toString();
  }
}
