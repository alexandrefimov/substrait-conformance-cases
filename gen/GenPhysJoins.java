import com.google.protobuf.util.JsonFormat;
import io.substrait.proto.*;
import java.nio.file.*;
import java.util.*;

/**
 * The same join rule down the three physical join messages.
 *
 * <p>`physical_relations.md` gives HashJoin, MergeJoin and NestedLoopJoin one Direct Output Order
 * each: "Same as the Join operator". Each of the three carries its own copy of the twelve-member
 * JoinType enum, identical to JoinRel's. So the rule these cases assert is not a new one - it is
 * the rule the twenty-four GenJoins cases already assert, arriving through a different message.
 *
 * <p>That is what makes them worth having. A consumer derives the join rule once and then has to
 * wire it to four entry points, and the corpus could not see whether it did: every join case in it
 * is a JoinRel. Three join types are enough to tell the wiring apart, and only three are used, so
 * that this stays a check on the wiring rather than a second copy of the join matrix:
 *
 * <ul>
 *   <li>inner, where the answer is the two inputs concatenated - a control, because a consumer that
 *       does nothing at all is right here;
 *   <li>left, where the right side widens to nullable - the cheapest type that separates deriving
 *       from concatenating;
 *   <li>left mark, which returns the left side plus a nullable boolean, so the arity changes too.
 * </ul>
 *
 * <p>The predicate differs by message because the messages differ: NestedLoopJoinRel carries an
 * `expression`, while HashJoinRel and MergeJoinRel have no such field and take `keys`, a
 * ComparisonJoinKey per equality. Both forms are what the message in question requires, so this is
 * not a variable being held constant badly - there is no form common to all three.
 */
public class GenPhysJoins {
  static Path OUT;

  /** The three join types, and the output arity each one implies over two two-column inputs. */
  static final String[][] KINDS = {{"inner", "4"}, {"left", "4"}, {"left_mark", "3"}};

  public static void main(String[] args) throws Exception {
    OUT = Paths.get(args[0]);
    Files.createDirectories(OUT);
    for (String[] kind : KINDS) {
      for (String message : new String[] {"hash", "merge", "nested"}) {
        emit(message, kind[0], Integer.parseInt(kind[1]));
      }
    }
  }

  /** equal(left.c0, right.c0) as a ComparisonJoinKey; the references are into each input. */
  static ComparisonJoinKey key() {
    return ComparisonJoinKey.newBuilder()
        .setLeft(fieldRef(0))
        .setRight(fieldRef(0))
        .setComparison(
            ComparisonJoinKey.ComparisonType.newBuilder()
                .setSimple(ComparisonJoinKey.SimpleComparisonType.SIMPLE_COMPARISON_TYPE_EQ))
        .build();
  }

  static Expression.FieldReference fieldRef(int index) {
    return Expression.FieldReference.newBuilder()
        .setDirectReference(
            Expression.ReferenceSegment.newBuilder()
                .setStructField(
                    Expression.ReferenceSegment.StructField.newBuilder().setField(index)))
        .setRootReference(Expression.FieldReference.RootReference.newBuilder())
        .build();
  }

  static Expression alwaysTrue() {
    return Expression.newBuilder()
        .setLiteral(Expression.Literal.newBuilder().setBoolean(true).setNullable(false))
        .build();
  }

  static Rel relation(String message, String kind) {
    Rel left = Tables.namedWithCommon("t_rn", "RN");
    Rel right = Tables.namedWithCommon("t_nr", "NR");
    String type = "JOIN_TYPE_" + kind.toUpperCase(Locale.ROOT);
    switch (message) {
      case "hash":
        return Rel.newBuilder()
            .setHashJoin(
                HashJoinRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setLeft(left)
                    .setRight(right)
                    .addKeys(key())
                    .setType(HashJoinRel.JoinType.valueOf(type)))
            .build();
      case "merge":
        return Rel.newBuilder()
            .setMergeJoin(
                MergeJoinRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setLeft(left)
                    .setRight(right)
                    .addKeys(key())
                    .setType(MergeJoinRel.JoinType.valueOf(type)))
            .build();
      case "nested":
        return Rel.newBuilder()
            .setNestedLoopJoin(
                NestedLoopJoinRel.newBuilder()
                    .setCommon(Tables.direct())
                    .setLeft(left)
                    .setRight(right)
                    .setExpression(alwaysTrue())
                    .setType(NestedLoopJoinRel.JoinType.valueOf(type)))
            .build();
      default:
        throw new IllegalArgumentException(message);
    }
  }

  static void emit(String message, String kind, int arity) throws Exception {
    String name = "physjoin_" + message + "_" + kind;
    List<String> names = new ArrayList<>();
    for (int i = 0; i < arity; i++) names.add("c" + i);

    Plan plan =
        Plan.newBuilder()
            .setVersion(Tables.version())
            .addRelations(
                PlanRel.newBuilder()
                    .setRoot(
                        RelRoot.newBuilder().setInput(relation(message, kind)).addAllNames(names)))
            .build();
    Files.writeString(OUT.resolve(name + ".json"), JsonFormat.printer().print(plan) + "\n");

    System.out.printf(
        "=== %-28s %s join, %s: the Join operator's rule through a different message",
        name, message, kind.replace('_', ' '));
    try {
      io.substrait.plan.Plan pojo = new io.substrait.plan.ProtoPlanConverter().from(plan);
      StringBuilder sb = new StringBuilder();
      for (io.substrait.type.Type f : pojo.getRoots().get(0).getInput().getRecordType().fields()) {
        sb.append(f.nullable() ? 'N' : 'R');
      }
      System.out.printf("  substrait-java: %-6s (%d columns)%n", sb, sb.length());
    } catch (RuntimeException e) {
      String m = e.getMessage();
      // The colon goes after the name, as in GenDisputed: gen/make_manifest.py strips a measurement
      // by matching "substrait-java:", and a line that spells it otherwise puts the answer into the
      // manifest, where a record of what a case asserts would then quote the implementation.
      System.out.println(
          "  substrait-java: REJECTED  " + (m == null ? e.getClass().getSimpleName() : m));
    }
  }
}
