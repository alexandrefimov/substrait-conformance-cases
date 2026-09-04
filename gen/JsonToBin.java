import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.Plan;
import java.nio.file.*;
import java.util.stream.Stream;

/** Writes each case's binary protobuf next to it: Acero accepts nothing else. */
public class JsonToBin {
  public static void main(String[] args) throws Exception {
    Path dir = Paths.get(args[0]);
    int n = 0;
    try (Stream<Path> files = Files.list(dir)) {
      for (Path p : files.sorted().toList()) {
        String name = p.getFileName().toString();
        if (!name.endsWith(".json") || name.endsWith("manifest.json")) continue;
        Plan.Builder b = Plan.newBuilder();
        JsonFormat.parser().merge(Files.readString(p), b);
        Files.write(dir.resolve(name.substring(0, name.length() - 5) + ".bin"), b.build().toByteArray());
        n++;
      }
    }
    System.out.println("binary cases written: " + n);
  }
}
