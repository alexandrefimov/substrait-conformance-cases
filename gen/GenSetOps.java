import com.google.protobuf.util.JsonFormat;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.*;

/**
 * The worked example the spec publishes for set operation output type derivation
 * (Logical Relations / Set Operation / Output Type Derivation Examples). The expected answers are
 * printed in the spec, so nothing here is inferred.
 */
public class GenSetOps {
  static Path OUT;

  // Nullability patterns of the three inputs, straight from the spec's example.
  static final String IN1 = "RRRRNNNN"; // primary
  static final String IN2 = "RRNNRRNN";
  static final String IN3 = "RNRNRNRN";

  static final Map<String, String> EXPECTED =
      new LinkedHashMap<>() {
        {
          put("MINUS_PRIMARY", "RRRRNNNN");
          put("MINUS_PRIMARY_ALL", "RRRRNNNN");
          put("MINUS_MULTISET", "RRRRNNNN");
          put("INTERSECTION_PRIMARY", "RRRRRNNN");
          put("INTERSECTION_MULTISET", "RRRRRRRN");
          put("INTERSECTION_MULTISET_ALL", "RRRRRRRN");
          put("UNION_DISTINCT", "RNNNNNNN");
          put("UNION_ALL", "RNNNNNNN");
        }
      };

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    int mismatches = 0;
    for (Map.Entry<String, String> e : EXPECTED.entrySet()) {
      if (!run(e.getKey(), e.getValue())) mismatches++;
    }
    System.out.println("\ndivergences from the spec: " + mismatches + " of " + EXPECTED.size());
  }

  static Type i64(boolean nullable) {
    return Type.newBuilder()
        .setI64(
            Type.I64.newBuilder()
                .setNullability(
                    nullable
                        ? Type.Nullability.NULLABILITY_NULLABLE
                        : Type.Nullability.NULLABILITY_REQUIRED))
        .build();
  }

  static boolean run(String opName, String expected) throws Exception {
    SetRel.SetOp op = SetRel.SetOp.valueOf("SET_OP_" + opName);
    SetRel set =
        SetRel.newBuilder()
            .setCommon(Tables.direct())
            .addInputs(Tables.namedWithCommon("s1", IN1))
            .addInputs(Tables.namedWithCommon("s2", IN2))
            .addInputs(Tables.namedWithCommon("s3", IN3))
            .setOp(op)
            .build();
    List<String> names = new ArrayList<>();
    for (int i = 0; i < IN1.length(); i++) names.add("c" + i);
    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(Rel.newBuilder().setSet(set))
                            .addAllNames(names)))
            .build();

    String name = "setop_" + opName.toLowerCase(Locale.ROOT);
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");

    System.out.printf("=== %-26s the spec expects %s%n", opName, expected);
    try {
      var pojo = new ProtoPlanConverter().from(plan);
      StringBuilder got = new StringBuilder();
      for (io.substrait.type.Type f :
          pojo.getRoots().get(0).getInput().getRecordType().fields()) {
        got.append(f.nullable() ? 'N' : 'R');
      }
      boolean ok = got.toString().equals(expected);
      System.out.printf(
          "    substrait-java %s  %s%n", got, ok ? "matches" : "<<< DIVERGES");
      return ok;
    } catch (RuntimeException ex) {
      System.out.println("    substrait-java REJECTED  " + ex.getMessage());
      return false;
    }
  }
}
