import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.util.List;
import java.nio.file.*;

/**
 * Types with a declared length: varchar&lt;N&gt;, fixed_char&lt;N&gt;, fixed_binary&lt;N&gt;.
 * In the spec the length is part of the type; the question is whether it survives into the
 * consumer's schema. substrait-java once lost it in Isthmus, which is where this case comes from.
 */
public class GenStringLen {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[0]);
    Files.createDirectories(out);

    NamedStruct.Builder schema = NamedStruct.newBuilder();
    Type.Struct.Builder st =
        Type.Struct.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED);
    Type.Nullability req = Type.Nullability.NULLABILITY_REQUIRED;
    schema.addNames("c0");
    st.addTypes(
        Type.newBuilder()
            .setVarchar(Type.VarChar.newBuilder().setLength(10).setNullability(req)));
    schema.addNames("c1");
    st.addTypes(
        Type.newBuilder()
            .setFixedChar(Type.FixedChar.newBuilder().setLength(5).setNullability(req)));
    schema.addNames("c2");
    st.addTypes(
        Type.newBuilder()
            .setFixedBinary(Type.FixedBinary.newBuilder().setLength(4).setNullability(req)));
    schema.addNames("c3");
    st.addTypes(
        Type.newBuilder().setString(Type.String.newBuilder().setNullability(req)));

    Rel read =
        Rel.newBuilder()
            .setRead(
                ReadRel.newBuilder()
                    .setBaseSchema(schema.setStruct(st))
                    .setNamedTable(ReadRel.NamedTable.newBuilder().addNames("t_str")))
            .build();

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder()
                            .setInput(read)
                            .addAllNames(List.of("c0", "c1", "c2", "c3"))))
            .build();

    Files.writeString(
        out.resolve("stringlen_declared.json"), JsonFormat.printer().print(plan) + "\n");
    System.out.println("=== stringlen_declared  varchar(10), fixed_char(5), fixed_binary(4), string");
    System.out.println(
        "    substrait-java: "
            + new io.substrait.plan.ProtoPlanConverter().from(plan)
                .getRoots().get(0).getInput().getRecordType());
  }
}
