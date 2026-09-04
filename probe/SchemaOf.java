import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.Plan;
import io.substrait.plan.ProtoPlanConverter;
import java.nio.file.*;

/** Prints the schema substrait-java derives for a plan. */
public class SchemaOf {
  public static void main(String[] args) throws Exception {
    for (String a : args) {
      String name = Paths.get(a).getFileName().toString().replace(".json", "");
      try {
        Plan.Builder b = Plan.newBuilder();
        JsonFormat.parser().merge(Files.readString(Paths.get(a)), b);
        var pojo = new ProtoPlanConverter().from(b.build());
        System.out.printf("%-46s %s%n", name, pojo.getRoots().get(0).getInput().getRecordType());
      } catch (Throwable t) {
        String m = String.valueOf(t.getMessage()).replace('\n', ' ');
        System.out.printf("%-46s ERROR: %s: %s%n", name, t.getClass().getSimpleName(),
            m.length() > 80 ? m.substring(0, 80) : m);
      }
    }
  }
}
