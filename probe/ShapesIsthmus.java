import io.substrait.isthmus.SqlToSubstrait;
import io.substrait.isthmus.sql.SubstraitCreateStatementParser;
import io.substrait.plan.PlanProtoConverter;
import java.nio.file.Files;
import java.nio.file.Path;

/** Isthmus as a producer: bash probe/isthmus_run.sh ShapesIsthmus <ddl> <queries.tsv> <out>. */
public class ShapesIsthmus {
  public static void main(String[] args) throws Exception {
    var catalog = SubstraitCreateStatementParser.processCreateStatementsToCatalog(args[0]);
    Path out = Path.of(args[2]);
    Files.createDirectories(out);
    for (String line : Files.readAllLines(Path.of(args[1]))) {
      String[] p = line.split("\t", 2);
      try {
        var proto = new PlanProtoConverter().toProto(new SqlToSubstrait().convert(p[1], catalog));
        Files.write(out.resolve(p[0] + ".pb"), proto.toByteArray());
        System.out.println(p[0] + " written");
      } catch (Throwable e) {
        String first = e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()).split("\n")[0];
        Files.writeString(out.resolve(p[0] + ".err"), first + "\n");
        System.out.println(p[0] + " refused: " + first);
      }
    }
  }
}
