import com.google.protobuf.util.JsonFormat;
import io.substrait.expression.Expression;
import io.substrait.expression.ExpressionCreator;
import io.substrait.plan.Plan;
import io.substrait.plan.PlanProtoConverter;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.relation.Rel;
import io.substrait.dsl.SubstraitBuilder;
import io.substrait.relation.AbstractWriteRel;
import io.substrait.relation.Aggregate;
import io.substrait.relation.NamedWrite;
import io.substrait.relation.Project;
import io.substrait.relation.VirtualTableScan;
import io.substrait.type.NamedStruct;
import io.substrait.type.TypeCreator;
import java.nio.file.*;
import java.util.*;

public class GenCases {
  static final TypeCreator R = TypeCreator.REQUIRED;
  static final TypeCreator N = TypeCreator.NULLABLE;
  static Path OUT;
  static final SubstraitBuilder sb = new SubstraitBuilder();
  static final List<String> MANIFEST = new ArrayList<>();
  static String currentSource = "";
  static String currentNote = "";
  static String currentAssertion = "output_schema";
  static String currentExpectation = "";
  static String currentCaveat = "";

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    emitMappingOnVirtualTable();
    groupingSetsDeclaredOrder();
    groupingFieldSharedBySets();
    ctasKeepsDeclaredSchema();
    Files.writeString(
        OUT.resolve("manifest.json"),
        "[\n" + String.join(",\n", MANIFEST) + "\n]\n");
    System.out.println("\nmanifest: " + MANIFEST.size() + " cases");
  }

  static Expression.NestedStruct row(Expression... fields) {
    return ExpressionCreator.nestedStruct(false, fields);
  }

  /** #1189: a virtual table carrying an emit mapping returns only the columns the mapping names. */
  static void emitMappingOnVirtualTable() throws Exception {
    NamedStruct schema = NamedStruct.of(List.of("col1", "col2"), R.struct(R.I32, R.STRING));
    Rel rel =
        VirtualTableScan.builder()
            .initialSchema(schema)
            .addRows(row(ExpressionCreator.i32(false, 2), ExpressionCreator.string(false, "a")))
            .remap(Rel.Remap.of(List.of(1)))
            .build();
    currentSource = "substrait-java#1189";
    currentNote = "A virtual table carrying an emit mapping returns only the columns the mapping names.";
    write("virtual_table_emit_mapping", rel, List.of("col2"));
  }

  /**
   * #1161: the aggregate declares field 2 before field 0. The declared order is the plan's output
   * order; a consumer that emits grouping columns in ascending field order transposes the schema.
   */
  static void groupingSetsDeclaredOrder() throws Exception {
    Rel rel =
        sb.aggregate(
            input -> List.of(sb.grouping(input, 2), sb.grouping(input, 0)),
            input -> List.<Aggregate.Measure>of(),
            Optional.of(Rel.Remap.of(List.of(0, 1))),
            sb.namedScan(List.of("foo"), List.of("a", "b", "c"), List.of(R.I64, R.I64, R.STRING)));
    currentSource = "substrait-java#1161";
    currentNote = "The aggregate declares field 2 before field 0; the declared order is the output order.";
    write("aggregate_grouping_sets_declared_order", rel, List.of("c", "a"));
  }

  /**
   * #1161: field 2 is grouped on by both sets. It is one column of the output, not two, so the
   * count of grouping mentions is not the count of output columns.
   */
  static void groupingFieldSharedBySets() throws Exception {
    Rel rel =
        sb.aggregate(
            input -> List.of(sb.grouping(input, 2, 0), sb.grouping(input, 2)),
            input -> List.<Aggregate.Measure>of(),
            Optional.of(Rel.Remap.of(List.of(0, 1))),
            sb.namedScan(List.of("foo"), List.of("a", "b", "c"), List.of(R.I64, R.I64, R.STRING)));
    currentSource = "substrait-java#1161";
    currentNote = "A field grouped on by both sets is one output column, not two.";
    write("aggregate_grouping_field_shared_by_sets", rel, List.of("c", "a"));
  }

  /**
   * #1181: a CTAS declares the schema of the table it creates. The columns its input computes are
   * a different thing -- here the input yields two nullable i32 while the statement declares
   * [total: i64 required, doubled: i32 nullable] -- so a consumer that recomputes the schema from
   * the input reports the wrong one.
   */
  static void ctasKeepsDeclaredSchema() throws Exception {
    NamedStruct declared =
        NamedStruct.of(List.of("total", "doubled"), R.struct(R.I64, N.I32));
    Rel scan =
        sb.namedScan(
            List.of("SRC1"), List.of("INTCOL", "CHARCOL"), List.of(N.I32, N.varChar(10)));
    Rel computed =
        Project.builder()
            .input(scan)
            .remap(Rel.Remap.offset(2, 2))
            .addExpressions(
                sb.add(sb.fieldReference(scan, 0), sb.i32(1)),
                sb.add(sb.fieldReference(scan, 0), sb.i32(2)))
            .build();
    Rel ctas =
        NamedWrite.builder()
            .input(computed)
            .names(List.of("dst1"))
            .tableSchema(declared)
            .operation(AbstractWriteRel.WriteOp.CTAS)
            .createMode(AbstractWriteRel.CreateMode.REPLACE_IF_EXISTS)
            .outputMode(AbstractWriteRel.OutputMode.NO_OUTPUT)
            .build();
    currentSource = "substrait-java#1181";
    currentAssertion = "declared_table_schema";
    currentExpectation = declared.toString();
    currentCaveat =
        "The spec says a write's input schema must match table_schema; this case has them differ "
            + "on purpose, so whether the plan is valid at all is an open question for the thread.";
    currentNote =
        "A CTAS declares the schema of the table it creates; it is not the schema of its input.";
    write("ctas_keeps_declared_schema", ctas, List.of("total", "doubled"));
  }

  static String quoteList(List<String> xs) {
    StringBuilder b = new StringBuilder("[");
    for (int i = 0; i < xs.size(); i++) {
      if (i > 0) b.append(", ");
      b.append('"').append(xs.get(i)).append('"');
    }
    return b.append(']').toString();
  }

  static void write(String name, Rel rel, List<String> names) throws Exception {
    Plan pojo =
        Plan.builder()
            // Otherwise the POJO builder puts substrait-java down as the producer, and four cases
            // would differ from the other seventy-four.
            .version(
                io.substrait.plan.Plan.Version.builder()
                    .from(io.substrait.plan.Plan.Version.DEFAULT_VERSION)
                    .producer("case-corpus")
                    .build())
            .executionBehavior(
                Plan.ExecutionBehavior.builder()
                    .variableEvaluationMode(
                        Plan.ExecutionBehavior.VariableEvaluationMode.PER_PLAN)
                    .build())
            .addRoots(Plan.Root.builder().input(rel).addAllNames(names).build())
            .build();
    io.substrait.proto.Plan proto = new PlanProtoConverter().toProto(pojo);
    String json = JsonFormat.printer().print(proto);
    Files.writeString(OUT.resolve(name + ".json"), json + "\n");

    Plan back = new ProtoPlanConverter().from(proto);
    var schema = back.getRoots().get(0).getInput().getRecordType();

    // Re-read the artifact from disk: the case is the file, not the in-memory object.
    io.substrait.proto.Plan.Builder reparsed = io.substrait.proto.Plan.newBuilder();
    JsonFormat.parser().merge(Files.readString(OUT.resolve(name + ".json")), reparsed);
    Plan fromFile = new ProtoPlanConverter().from(reparsed.build());
    var fileSchema = fromFile.getRoots().get(0).getInput().getRecordType();

    System.out.println("=== " + name);
    System.out.println("    schema: " + schema);
    System.out.println("    names : " + back.getRoots().get(0).getNames());
    MANIFEST.add(
        String.format(
            "  {\n    \"case\": \"%s\",\n    \"plan\": \"%s.json\",\n"
                + "    \"source\": \"%s\",\n    \"note\": \"%s\",\n"
                + "    \"assertion\": \"%s\",\n    \"expected\": \"%s\",\n"
                + "    \"derived_output_schema\": \"%s\",\n    \"output_names\": %s%s\n  }",
            name,
            name,
            currentSource,
            currentNote,
            currentAssertion,
            currentExpectation.isEmpty() ? schema.toString() : currentExpectation,
            schema,
            quoteList(names),
            currentCaveat.isEmpty()
                ? ""
                : ",\n    \"caveat\": \"" + currentCaveat + "\""));
    System.out.println("    matches when re-read from the file: " + fileSchema.equals(schema));
    currentAssertion = "output_schema";
    currentExpectation = "";
    currentCaveat = "";
    if (!fileSchema.equals(schema)) {
      throw new IllegalStateException("mismatch for " + name + ": " + fileSchema);
    }
  }
}
