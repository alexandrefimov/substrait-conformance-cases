import com.google.protobuf.util.JsonFormat;
import io.substrait.isthmus.ConverterProvider;
import io.substrait.isthmus.SubstraitToCalcite;
import io.substrait.plan.ProtoPlanConverter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import org.apache.calcite.jdbc.CalciteSchema;
import org.apache.calcite.rel.type.RelDataTypeFactory;
import org.apache.calcite.util.Util;

/** A schema-only Isthmus probe with an explicit type factory; never invokes Impala planning. */
public class TypeFactorySchemaOf {
  public static void main(String[] args) throws Exception {
    if (args.length < 2) {
      throw new IllegalArgumentException("usage: TypeFactorySchemaOf default|<factory class> <plans...>");
    }
    // Resolve the requested factory before reading cases. A missing class or dependency is a
    // broken environment, not 78 unsupported plans and not a reason to fall back to the default.
    var provider = args[0].equals("default")
        ? ConverterProvider.DEFAULT
        : ConverterProvider.builder().typeFactory((RelDataTypeFactory)
            Class.forName(args[0]).getDeclaredConstructor().newInstance()).build();
    var builder = provider.getRelBuilder(CalciteSchema.createRootSchema(false));
    describe("provider-factory", provider.getTypeFactory());
    describe("provider-type-system", provider.getTypeSystem());
    describe("builder-factory", builder.getTypeFactory());
    describe("builder-type-system", builder.getTypeFactory().getTypeSystem());
    System.err.println("calcite-version=" + Util.class.getPackage().getImplementationVersion());
    System.err.println("java-version=" + System.getProperty("java.version"));

    var s2c = new SubstraitToCalcite(provider);
    for (String arg : Arrays.copyOfRange(args, 1, args.length)) {
      var path = Path.of(arg);
      var name = path.getFileName().toString().replaceFirst("\\.json$", "");
      // Missing/unreadable inputs must stop the harness, not look like consumer refusals.
      var json = Files.readString(path);
      io.substrait.relation.Rel rel;
      try {
        var b = io.substrait.proto.Plan.newBuilder();
        JsonFormat.parser().merge(json, b);
        rel = new ProtoPlanConverter().from(b.build()).getRoots().get(0).getInput();
      } catch (Exception e) {
        System.out.println(name + " ERROR: PARSE FAILED: " + message(e));
        continue;
      }
      try {
        System.out.println(name + " " + CalciteSchemaOf.render(s2c.convert(rel).getRowType()));
      } catch (Exception e) {
        System.out.println(name + " ERROR: " + message(e));
      }
    }
  }

  private static String message(Exception e) {
    return e.getClass().getSimpleName() + ": "
        + String.valueOf(e.getMessage()).replace('\n', ' ').replace('\r', ' ');
  }

  private static void describe(String label, Object value) {
    var cls = value.getClass();
    System.err.println(label + "=" + cls.getName());
    var source = cls.getProtectionDomain().getCodeSource();
    if (source != null) System.err.println(label + "-source=" + source.getLocation());
  }
}
