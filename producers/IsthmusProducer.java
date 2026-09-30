import io.substrait.isthmus.SqlToSubstrait;
import io.substrait.isthmus.sql.SubstraitCreateStatementParser;
import io.substrait.plan.PlanProtoConverter;
import java.nio.file.Files;
import java.nio.file.Path;

/** Isthmus as a producer, through SqlToSubstrait:
 *  bash probe/isthmus_run.sh producers/IsthmusProducer.java <tables.sql> <queries.tsv> <out>.
 *  Isthmus plans against a catalog it parses from the CREATE statements. Prints a count last. */
public class IsthmusProducer {
  public static void main(String[] args) throws Exception {
    var catalog = SubstraitCreateStatementParser.processCreateStatementsToCatalog(
        String.join(";\n", Files.readAllLines(Path.of(args[0]))));
    Path out = Path.of(args[2]);
    Files.createDirectories(out);
    int written = 0, refused = 0;
    for (String line : Files.readAllLines(Path.of(args[1]))) {
      if (line.startsWith("#") || line.isBlank()) continue;
      String[] p = line.split("\t");
      try {
        var proto = new PlanProtoConverter().toProto(new SqlToSubstrait().convert(p[1], catalog));
        Files.write(out.resolve(p[0] + ".pb"), proto.toByteArray());
        written++;
      } catch (Throwable e) {
        String first = e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()).split("\n")[0];
        Files.writeString(out.resolve(p[0] + ".err"), first + "\n");
        refused++;
      }
    }
    // probe/isthmus_run.sh ends in a grep, which fails a run that printed nothing.
    System.out.println("isthmus " + written + " written, " + refused + " refused");
  }
}
