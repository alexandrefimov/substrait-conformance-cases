import com.google.protobuf.util.JsonFormat;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.relation.NamedScan;
import io.substrait.relation.Rel;
import io.substrait.spark.ToSparkType$;
import io.substrait.spark.logical.ToLogicalPlan;
import io.substrait.util.EmptyVisitationContext;
import java.nio.file.*;
import java.util.*;
import org.apache.spark.sql.Row;
import org.apache.spark.sql.SparkSession;
import org.apache.spark.sql.catalyst.plans.logical.LogicalPlan;
import org.apache.spark.sql.types.StructType;

/** Diagnostics: builds the plan around require(resolved) and prints what exactly is unresolved. */
public class DiagnoseSelfJoin {
  static void collect(Rel rel, List<NamedScan> out) {
    if (rel instanceof NamedScan) out.add((NamedScan) rel);
    for (Rel in : rel.getInputs()) collect(in, out);
  }

  public static void main(String[] args) throws Exception {
    SparkSession spark = SparkSession.builder().master("local[1]").appName("diag")
        .config("spark.ui.enabled", "false").getOrCreate();
    spark.sparkContext().setLogLevel("ERROR");
    var b = io.substrait.proto.Plan.newBuilder();
    JsonFormat.parser().merge(Files.readString(Paths.get(args[0])), b);
    var pojo = new ProtoPlanConverter().from(b.build());
    var root = pojo.getRoots().get(0).getInput();
    List<NamedScan> scans = new ArrayList<>();
    collect(root, scans);
    for (NamedScan ns : scans) {
      StructType st = ToSparkType$.MODULE$.toStructType(ns.getInitialSchema());
      spark.createDataFrame(new ArrayList<Row>(), st)
          .createOrReplaceTempView(ns.getNames().get(ns.getNames().size() - 1));
    }
    ToLogicalPlan tlp = new ToLogicalPlan(spark);
    LogicalPlan lp = (LogicalPlan) root.accept(tlp, EmptyVisitationContext.INSTANCE);
    System.out.println("=== tree:\n" + lp.treeString());
    System.out.println("resolved         = " + lp.resolved());
    System.out.println("childrenResolved = " + lp.childrenResolved());
    if (lp instanceof org.apache.spark.sql.catalyst.plans.logical.Join) {
      var j = (org.apache.spark.sql.catalyst.plans.logical.Join) lp;
      System.out.println("left.output      = " + j.left().output());
      System.out.println("right.output     = " + j.right().output());
      System.out.println("duplicateResolved= " + j.duplicateResolved());
      System.out.println("id intersection  = " + j.left().outputSet().intersect(j.right().outputSet()));
    }
    spark.stop();
  }
}
