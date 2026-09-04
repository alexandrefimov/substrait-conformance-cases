import io.substrait.proto.*;

/**
 * The named tables shared by every case. A case's leaf has to be a control rather than a variable:
 * with a virtual table at the leaf the run would also be measuring support for virtual tables (Acero
 * does not read them at all), and a divergence in type derivation could no longer be told apart from
 * a lack of support.
 *
 * <p>The schemas are duplicated in each engine's probe: {@code foo}, {@code SRC1}, {@code t_rn},
 * {@code t_nr}, {@code s1}, {@code s2}, {@code s3}, {@code t_xnull}.
 */
public final class Tables {
  private Tables() {}

  /**
   * The version the corpus declares: the one the core was built against
   * ({@code io.substrait.SubstraitVersion.VERSION}), with a single producer for the whole corpus.
   * Until 2026-09-03 the version was hard-coded in each generator and the corpus drifted apart:
   * some cases declared 0.102, some 0.103, and four named substrait-java as the producer.
   */
  public static Version.Builder version() {
    String[] parts = io.substrait.SubstraitVersion.VERSION.split("\\.");
    return Version.newBuilder()
        .setMajorNumber(Integer.parseInt(parts[0]))
        .setMinorNumber(Integer.parseInt(parts[1]))
        .setPatchNumber(Integer.parseInt(parts[2].replaceAll("\\D.*$", "")))
        .setProducer("case-corpus");
  }

  public static Type i64(boolean nullable) {
    return Type.newBuilder()
        .setI64(
            Type.I64.newBuilder()
                .setNullability(
                    nullable
                        ? Type.Nullability.NULLABILITY_NULLABLE
                        : Type.Nullability.NULLABILITY_REQUIRED))
        .build();
  }

  /** A pattern such as "RRNN": R is required, N is nullable. The columns are named c0, c1, ... */
  public static Rel named(String table, String pattern) {
    NamedStruct.Builder schema = NamedStruct.newBuilder();
    Type.Struct.Builder st =
        Type.Struct.newBuilder().setNullability(Type.Nullability.NULLABILITY_REQUIRED);
    for (int i = 0; i < pattern.length(); i++) {
      schema.addNames("c" + i);
      st.addTypes(i64(pattern.charAt(i) == 'N'));
    }
    return Rel.newBuilder()
        .setRead(
            ReadRel.newBuilder()
                .setBaseSchema(schema.setStruct(st))
                .setNamedTable(ReadRel.NamedTable.newBuilder().addNames(table)))
        .build();
  }

  /**
   * An empty RelCommon with a direct output. Real producers always set it (in substrait-java that is
   * RelProtoConverter.common), while hand-assembled plans leave it out - and substrait-go dies on
   * that. It is set here so the cases stay realistic; control_join_without_relcommon is the separate
   * case kept for the finding itself.
   */
  public static RelCommon direct() {
    return RelCommon.newBuilder().setDirect(RelCommon.Direct.newBuilder()).build();
  }

  /** A named table with common set. */
  public static Rel namedWithCommon(String table, String pattern) {
    Rel r = named(table, pattern);
    return r.toBuilder().setRead(r.getRead().toBuilder().setCommon(direct())).build();
  }
}
