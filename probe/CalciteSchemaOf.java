import com.google.protobuf.util.JsonFormat;
import io.substrait.isthmus.ConverterProvider;
import io.substrait.isthmus.SubstraitToCalcite;
import io.substrait.plan.ProtoPlanConverter;
import java.nio.file.*;
import org.apache.calcite.rel.type.RelDataType;

/**
 * The schema Calcite derives for the same plan, through Isthmus.
 *
 * <p>Each case is wrapped whole: parsing fails on the cases substrait-java rejects deliberately,
 * and one of those must not cut the run short for the rest.
 */
public class CalciteSchemaOf {
  public static void main(String[] args) throws Exception {
    var s2c = new SubstraitToCalcite(ConverterProvider.DEFAULT);
    for (String a : args) {
      String name = Paths.get(a).getFileName().toString().replace(".json", "");
      try {
        var b = io.substrait.proto.Plan.newBuilder();
        JsonFormat.parser().merge(Files.readString(Paths.get(a)), b);
        var pojo = new ProtoPlanConverter().from(b.build());
        var rel = pojo.getRoots().get(0).getInput();
        System.out.printf("%-24s declared/POJO: %s%n", name, rel.getRecordType());
        try {
          System.out.printf("%-24s Calcite:        %s%n", "", render(s2c.convert(rel).getRowType()));
        } catch (Exception e) {
          System.out.printf("%-24s Calcite:        %s: %s%n", "", e.getClass().getSimpleName(),
              String.valueOf(e.getMessage()).replace('\n', ' '));
        }
      } catch (Exception e) {
        System.out.printf("%-24s declared/POJO: PARSE FAILED: %s: %s%n", name,
            e.getClass().getSimpleName(), String.valueOf(e.getMessage()).replace('\n', ' '));
      }
    }
  }

  /**
   * The row type with each field's nullability spelled out. {@code RelDataType.toString()} prints a
   * short form that omits {@code NOT NULL}, and nullability cannot be recovered from it.
   */
  static String render(RelDataType t) {
    var sb = new StringBuilder("[");
    for (var f : t.getFieldList()) {
      if (sb.length() > 1) sb.append(", ");
      // A ROW is printed with its fields: getSqlTypeName() on a struct gives a bare ROW, and the
      // type of an aggregate's intermediate phase would look like a divergence caused by the format.
      if (f.getType().getSqlTypeName() == org.apache.calcite.sql.type.SqlTypeName.ROW) {
        sb.append(f.getName()).append(':').append("ROW").append(render(f.getType()));
        if (f.getType().isNullable()) sb.append('?');
        continue;
      }
      // getSqlTypeName() drops precision, scale and length: DECIMAL(11,2) printed as DECIMAL, and
      // every parameterized type looked like a divergence caused by the probe's own format.
      var ft = f.getType();
      sb.append(f.getName()).append(':').append(ft.getSqlTypeName());
      if (ft.getSqlTypeName().allowsPrec()
          && ft.getPrecision() != RelDataType.PRECISION_NOT_SPECIFIED) {
        sb.append('(').append(ft.getPrecision());
        if (ft.getSqlTypeName().allowsScale()) sb.append(',').append(ft.getScale());
        sb.append(')');
      }
      if (ft.isNullable()) sb.append('?');
    }
    return sb.append(']').toString();
  }
}
