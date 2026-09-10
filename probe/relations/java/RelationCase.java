// One relation case through substrait-java.
//
//     java -cp <core classpath>:<generated>:<this> RelationCase <bundle.pb>
//
// Prints "<case id><TAB><answer>", which probe/relations/column.py turns into a column.
//
// It reads a serialized substrait.test.RelationTestCase with generated protobuf bindings and knows
// nothing else about this repository: no YAML, no authoring parser, no text format. The envelope's
// `plan` field is a plain substrait.Plan, so the generated class resolves to io.substrait.proto.Plan
// out of the packaged protobuf artifact and no second copy of the Substrait protos is compiled here.
//
// substrait-java derives schemas and does not execute, so it answers with a schema and never with
// rows.
import com.google.protobuf.Descriptors;
import com.google.protobuf.Message;
import io.substrait.extension.ExtensionCollector;
import io.substrait.plan.Plan;
import io.substrait.plan.ProtoPlanConverter;
import io.substrait.proto.test.RelationTestCase;
import io.substrait.type.proto.TypeProtoConverter;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class RelationCase {

  /** NULLABILITY_NULLABLE. Read as a number, the way corpus.py and the Go runner read it. */
  private static final int NULLABLE = 1;

  /** The two type names the corpus spells differently from the protobuf field that carries them. */
  private static final Map<String, String> SHORT =
      Map.of("fixed_char", "fixedchar", "fixed_binary", "fixedbinary");

  /** The harness cannot put this case to substrait-java at all. Not a finding about it. */
  static final class Unbindable extends Exception {
    Unbindable(String message) {
      super(message);
    }
  }

  static Descriptors.FieldDescriptor oneof(Message m, String name) {
    for (Descriptors.OneofDescriptor od : m.getDescriptorForType().getOneofs()) {
      if (od.getName().equals(name)) {
        return m.getOneofFieldDescriptor(od);
      }
    }
    return null;
  }

  static long number(Message m, String name) {
    Descriptors.FieldDescriptor fd = m.getDescriptorForType().findFieldByName(name);
    if (fd == null) {
      return 0;
    }
    Object value = m.getField(fd);
    // nullability is an enum and the parameters are integers; protobuf hands the two back as
    // different objects, so the kind is asked rather than assumed.
    if (value instanceof Descriptors.EnumValueDescriptor) {
      return ((Descriptors.EnumValueDescriptor) value).getNumber();
    }
    return ((Number) value).longValue();
  }

  static boolean has(Message m, String name) {
    return m.getDescriptorForType().findFieldByName(name) != null;
  }

  /**
   * A type the way a case is written: {@code i64}, {@code i64?}, {@code decimal<11,2>}.
   *
   * <p>Deliberately not substrait-java's StringTypeVisitor, which spells a type its own way. A
   * column records the answer in the notation the cases use, so that two participants' columns can
   * be read side by side and the comparison needs no per-participant parser. Reading the protobuf
   * oneof through the descriptor rather than switching on every known kind keeps this the same
   * procedure probe/relations/corpus.py follows, so a type neither of them has met is still named
   * and not dropped.
   */
  static String renderType(io.substrait.proto.Type t, Deque<String> names) {
    Descriptors.FieldDescriptor fd = oneof(t, "kind");
    if (fd == null) {
      return "?";
    }
    Message sub = (Message) t.getField(fd);
    String name = SHORT.getOrDefault(fd.getName(), fd.getName());
    String q = number(sub, "nullability") == NULLABLE ? "?" : "";
    // A struct column takes one name per field out of the flat, depth-first list a NamedStruct
    // carries, and everything after it moves. Pairing names with top-level types instead was wrong
    // the moment a column was a struct, which is what the cases under names/ are for.
    if (name.equals("struct")) {
      List<String> members = new ArrayList<>();
      for (io.substrait.proto.Type member : t.getStruct().getTypesList()) {
        members.add(takeName(names) + ":" + renderType(member, names));
      }
      return "struct<" + String.join(", ", members) + ">" + q;
    }
    if (name.equals("decimal")) {
      return String.format("decimal<%d,%d>%s", number(sub, "precision"), number(sub, "scale"), q);
    }
    if (has(sub, "length")) {
      return String.format("%s<%d>%s", name, number(sub, "length"), q);
    }
    if (has(sub, "precision")) {
      return String.format("%s<%d>%s", name, number(sub, "precision"), q);
    }
    return name + q;
  }

  /**
   * {@code [a:i64, b:i64?]}.
   *
   * <p>A name without a type and a type without a name are both kept as {@code ?} rather than
   * dropped: an answer that quietly shortened itself to the smaller of the two counts would hide
   * the arity disagreement it is there to record. The names are consumed from the front rather
   * than indexed, because a struct column takes one per field.
   */
  /** The next name, or {@code ?} rather than an invented one. */
  static String takeName(Deque<String> names) {
    return names.isEmpty() ? "?" : names.removeFirst();
  }

  static String renderSchema(List<String> names, List<io.substrait.proto.Type> types) {
    Deque<String> pending = new ArrayDeque<>(names);
    List<String> cols = new ArrayList<>();
    for (io.substrait.proto.Type t : types) {
      String name = takeName(pending);
      cols.add(name + ":" + renderType(t, pending));
    }
    while (!pending.isEmpty()) {
      cols.add(pending.removeFirst() + ":?");
    }
    return "[" + String.join(", ", cols) + "]";
  }

  /**
   * Visits every Rel reachable from one, through the descriptor rather than a list of relation
   * types. A hand-written switch has to gain an arm for each relation the corpus reaches, and the
   * four physical join cases are exactly what it would have missed.
   */
  static void walk(io.substrait.proto.Rel rel, List<io.substrait.proto.ReadRel> reads) {
    Descriptors.FieldDescriptor fd = oneof(rel, "rel_type");
    if (fd == null) {
      return;
    }
    if (rel.hasRead()) {
      reads.add(rel.getRead());
    }
    Message inner = (Message) rel.getField(fd);
    for (Map.Entry<Descriptors.FieldDescriptor, Object> e : inner.getAllFields().entrySet()) {
      Descriptors.FieldDescriptor f = e.getKey();
      if (f.getJavaType() != Descriptors.FieldDescriptor.JavaType.MESSAGE
          || !f.getMessageType().getFullName().equals("substrait.Rel")) {
        continue;
      }
      if (f.isRepeated()) {
        for (Object item : (List<?>) e.getValue()) {
          walk((io.substrait.proto.Rel) item, reads);
        }
      } else {
        walk((io.substrait.proto.Rel) e.getValue(), reads);
      }
    }
  }

  /**
   * Refuses a plan that declares an input schema the case did not bind. An engine answering about a
   * different input schema is not answering this case.
   */
  static void bindTables(RelationTestCase tc) throws Unbindable {
    Map<String, io.substrait.proto.NamedStruct> declared = new HashMap<>();
    for (RelationTestCase.InputTable t : tc.getTablesList()) {
      declared.put(String.join(".", t.getNameList()), t.getSchema());
    }
    List<io.substrait.proto.ReadRel> reads = new ArrayList<>();
    for (io.substrait.proto.PlanRel pr : tc.getPlan().getRelationsList()) {
      walk(pr.hasRoot() ? pr.getRoot().getInput() : pr.getRel(), reads);
    }
    for (io.substrait.proto.ReadRel read : reads) {
      if (!read.hasNamedTable()) {
        continue;
      }
      String key = String.join(".", read.getNamedTable().getNamesList());
      io.substrait.proto.NamedStruct want = declared.get(key);
      if (want == null) {
        throw new Unbindable("plan reads table \"" + key + "\", which the case does not bind");
      }
      if (!want.equals(read.getBaseSchema())) {
        throw new Unbindable(
            "table \"" + key + "\": the fixture schema is not the plan's base_schema");
      }
    }
  }

  static String oneLine(String s) {
    return String.valueOf(s).replaceAll("\\s+", " ").trim();
  }

  static String answer(RelationTestCase tc) {
    try {
      bindTables(tc);
    } catch (Unbindable e) {
      return "HARNESS-ERROR: " + oneLine(e.getMessage());
    }
    Plan plan;
    Plan.Root root;
    io.substrait.proto.Type.Struct derived;
    try {
      plan = new ProtoPlanConverter().from(tc.getPlan());
      if (plan.getRoots().isEmpty()) {
        return "ERROR: the plan has no root relation";
      }
      root = plan.getRoots().get(0);
      derived =
          new TypeProtoConverter(new ExtensionCollector())
              .toProto(root.getInput().getRecordType())
              .getStruct();
    } catch (Throwable t) {
      // A refusal and a defect are both this participant's answer to this case, but they are not
      // the same answer, so the exception type decides which word the column carries.
      boolean refused =
          t instanceof IllegalArgumentException
              || t instanceof UnsupportedOperationException
              || t instanceof IllegalStateException;
      String message = t.getClass().getSimpleName() + ": " + oneLine(String.valueOf(t.getMessage()));
      return (refused ? "ERROR: " : "CRASH: ") + message;
    }
    return renderSchema(root.getNames(), derived.getTypesList());
  }

  public static void main(String[] args) throws Exception {
    for (String path : args) {
      RelationTestCase tc;
      try {
        tc = RelationTestCase.parseFrom(Files.readAllBytes(Path.of(path)));
      } catch (Exception e) {
        System.out.printf("%s\tHARNESS-ERROR: the bundle does not parse: %s%n", path,
            oneLine(e.getMessage()));
        continue;
      }
      System.out.printf("%s\t%s%n", tc.getId(), answer(tc));
    }
  }
}
