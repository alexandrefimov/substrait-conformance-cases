import io.substrait.plan.ProtoPlanConverter;
import io.substrait.proto.Plan;
import java.nio.file.*;

/** The schema substrait-java derives for a plan given as binary protobuf. */
public class SchemaOfBin {
  public static void main(String[] args) throws Exception {
    for (String a : args) {
      String name = Paths.get(a).getFileName().toString().replace(".pb", "");
      try {
        Plan p = Plan.parseFrom(Files.readAllBytes(Paths.get(a)));
        var pojo = new ProtoPlanConverter().from(p);
        System.out.printf("%-14s %s%n", name, pojo.getRoots().get(0).getInput().getRecordType());
      } catch (Throwable t) {
        String m = String.valueOf(t.getMessage()).replace('\n', ' ');
        System.out.printf("%-14s ERROR: %s: %s%n", name, t.getClass().getSimpleName(),
            m.length() > 100 ? m.substring(0, 100) : m);
      }
    }
  }
}
