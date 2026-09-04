"""Compares a participant's answer against the independent expectations (expected.json).

    python3 probe/check_expected.py <column file> [java|py|df|duckdb|acero|go|spark|calcite]

The participant's format is parsed into a normalized (type, nullable) form and compared with the
expectation computed from the spec in expected.py. Exit code 1 if any case differs - so this is a
check with a verdict, not only a measurement.

Cases with no independent expectation are skipped and counted separately: staying silent about them
is more honest than comparing them with the same implementation's own answer.

THE CAVEAT, without which this check misleads. Some of the agreement is NOT independent evidence:
the implementation repeats the output_type declared in the plan, and this project's own generator
wrote that declaration from the same formula, so there the check catches generator drift rather than
what the consumer derives.

Which cases those are is measured, not guessed: every declared `outputType` is swapped for a false
one (probe/make_lied_corpus.py) and the answers that move with it are the copied ones. Nothing else
about the plan changes, so an answer that moves is an answer that depends on the declaration.

For substrait-java ten answers move: the five decimal cases, `narrowing_count`, `narrowing_is_null`,
`narrowing_is_not_null`, `phase_final` and `ctas_keeps_declared_schema`. The last of those carries no
expectation. substrait-python and the validator move on ten each, all ten carrying an expectation;
DuckDB moves on none. An earlier wording said "the five decimal cases" and called the rest
independent, which understated the circular part by half.

One case the swap cannot judge: on `phase_intermediate` it turns a struct output_type into a scalar,
which leaves three names in `Plan.Root` above a single column, and substrait-java rejects the plan
over the names rather than over the type. Neither copied nor derived - not measured. So for
substrait-java 63 of the 73 expectations are checked against an answer known not to be copied, nine
are circular, and one is unknown.

Two limits on reading "not copied" as "derived". The swap perturbs output_type and nothing else, so
a relation schema taken from ReadRel.base_schema is untouched by it. And only substrait-java,
substrait-python, the validator and DuckDB were measured this way.
"""
import json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_DOC = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))
EXPECTED, DISPUTED = _DOC["expected"], _DOC["disputed"]

JAVA_FIELD = re.compile(r"(Decimal|PrecisionTimestamp|VarChar|FixedChar|FixedBinary|"
                        r"I64|I32|Str|Bool|Fp64|I8|I16)\{([^}]*)\}")

def _nested_java(inner):
    """A nested struct in java notation: Struct{...fields=[I64{..}, I64{..}]}."""
    m = re.search(r"Struct\{nullable=(true|false), fields=\[(.*)\]\}\s*\]?\s*$", inner)
    if not m:
        return None
    kinds = [k.lower() for k, _ in JAVA_FIELD.findall(m.group(2))]
    return ["struct(%s)" % ",".join(kinds), m.group(1) == "true"] if kinds else None

def parse_java(s):
    """Struct{nullable=false, fields=[Decimal{nullable=false, scale=9, precision=38}]}"""
    inner = s[s.index("fields=[") + 8:] if "fields=[" in s else ""
    nested = _nested_java(inner)
    if nested is not None:
        return [nested]
    out = []
    for kind, attrs in JAVA_FIELD.findall(inner):
        nullable = "nullable=true" in attrs
        if kind == "Decimal":
            prec = re.search(r"precision=(\d+)", attrs).group(1)
            scale = re.search(r"scale=(\d+)", attrs).group(1)
            out.append(["dec(%s,%s)" % (prec, scale), nullable])
        elif kind == "PrecisionTimestamp":
            out.append(["precision_timestamp(%s)" % re.search(r"precision=(\d+)", attrs).group(1), nullable])
        elif kind in ("VarChar", "FixedChar", "FixedBinary"):
            short = {"VarChar": "vchar", "FixedChar": "fchar", "FixedBinary": "fbin"}[kind]
            out.append(["%s(%s)" % (short, re.search(r"length=(\d+)", attrs).group(1)), nullable])
        else:
            out.append([{"I64": "i64", "I32": "i32", "Str": "str", "Bool": "bool",
                         "Fp64": "fp64", "I8": "i8", "I16": "i16"}[kind], nullable])
    return out

def _nested_bracket(s):
    """substrait-python and the validator print a nested struct as [i64, i64] inside the column.

    The trailing "!! names N, types M" is this project's own probe marker, not part of the answer.
    """
    s = re.sub(r"\s*!!.*$", "", s.strip())
    m = re.match(r"^\[(?:[^:\[\]]*:)?\[([^\[\]]+)\]\]$", s)
    if not m:
        return None
    return [["struct(%s)" % ",".join(x.strip() for x in m.group(1).split(",")), False]]

def parse_py(s):
    """[c0:i64, c1:i64?], [r:dec(38,9)], or a bare type i64 (how the validator prints a single one)."""
    nested = _nested_bracket(s)
    if nested is not None:
        return nested
    s = s.strip()
    if s and "[" not in s and "]" not in s and " " not in s:
        return [[s.rstrip("?"), s.endswith("?")]]
    # The python probe appends "!! names N, types M" when the two counts disagree - that marker is
    # part of the finding rather than noise, but what has to be parsed is the part before the
    # closing bracket.
    if "]" in s:
        s = s[: s.rindex("]") + 1]
    if not (s.startswith("[") and s.endswith("]")):
        return None
    body = s[1:-1].strip()
    if not body:
        return []
    out = []
    # A comma separates columns only when it is not inside a type's parameters. The brackets can
    # be round (Decimal128(38,9)) or angled (decimal<38,9>): without the second branch substrait-go
    # split into two columns, and that looked like a divergence in derivation.
    for part in re.split(r",\s*(?![^()]*\))(?![^<>]*>)", body):
        t = part.split(":", 1)[1] if ":" in part else part
        t = t.strip()
        out.append([t.rstrip("?"), t.endswith("?")])
    return out

ARROW_TIME_UNIT = {"Second": 0, "Millisecond": 3, "Microsecond": 6, "Nanosecond": 9}

ARROW = {"Int64": "i64", "Int32": "i32", "Int8": "i8", "Int16": "i16", "Utf8": "str",
         "Boolean": "bool", "Float64": "fp64", "Float32": "fp32", "Binary": "bin"}

def parse_df(s):
    """[c:Utf8?, a:Int64?] - the DataFusion format: Arrow type names instead of Substrait ones."""
    got = parse_py(s)
    if got is None:
        return None
    out = []
    for t, nullable in got:
        if t.startswith("Decimal128("):
            p_, sc = t[len("Decimal128("):-1].split(",")
            out.append(["dec(%s,%s)" % (p_.strip(), sc.strip()), nullable])
        elif t.startswith("FixedSizeBinary("):
            out.append(["fbin(%s)" % t[len("FixedSizeBinary("):-1].strip(), nullable])
        elif t.startswith("Timestamp("):
            # Arrow names precision by unit rather than by digit count. The mapping is one to one,
            # so comparing the strings as they are would count a difference in vocabulary as a
            # divergence: Timestamp(Second) and precision_timestamp(0) are the same type.
            unit = t[len("Timestamp("):-1].split(",")[0].strip()
            tz = t[len("Timestamp("):-1].split(",")[1].strip() if "," in t else "None"
            digits = ARROW_TIME_UNIT.get(unit)
            if digits is None or tz != "None":
                out.append([t, nullable])
            else:
                out.append(["precision_timestamp(%d)" % digits, nullable])
        else:
            out.append([ARROW.get(t, t), nullable])
    return out

# Type vocabularies for the engines that name types their own way. Separate from parse_df: DuckDB's
# names are SQL ones and Acero's are lowercase Arrow ones, and running both through one parser would
# count a difference in vocabulary as a divergence.
DUCKDB_T = {"BIGINT": "i64", "INTEGER": "i32", "SMALLINT": "i16", "TINYINT": "i8",
            "VARCHAR": "str", "BOOLEAN": "bool", "DOUBLE": "fp64", "FLOAT": "fp32",
            "BLOB": "bin", "TIMESTAMP": "precision_timestamp(6)"}
ACERO_T = {"int64": "i64", "int32": "i32", "int16": "i16", "int8": "i8", "string": "str",
           "bool": "bool", "double": "fp64", "float": "fp32", "binary": "bin"}

def _mapped(s, table):
    got = parse_py(s)
    if got is None:
        return None
    out = []
    for t, nullable in got:
        # DuckDB's DECIMAL(p,s) and Acero's decimal128(p, s) are the same thing spelled differently.
        if re.match(r"(?i)^decimal\d*\(", t):
            p_, sc = t[t.index("(") + 1:-1].split(",")
            out.append(["dec(%s,%s)" % (p_.strip(), sc.strip()), nullable])
        else:
            out.append([table.get(t, table.get(t.lower(), t)), nullable])
    return out

GO_T = {"string": "str", "boolean": "bool", "fp64": "fp64", "fp32": "fp32", "binary": "bin"}

def parse_go(s):
    """[r:decimal<11,2>, c:precision_timestamp<6>] - parameters in angle brackets, own names."""
    got = parse_py(s)
    if got is None:
        return None
    out = []
    for t, nullable in got:
        if t.startswith("struct<"):
            inner = t[len("struct<"):-1]
            out.append(["struct(%s)" % ",".join(x.strip() for x in inner.split(",")), nullable])
        elif "<" in t:
            base, args = t[:t.index("<")], t[t.index("<") + 1:-1]
            base = {"decimal": "dec", "varchar": "vchar", "fixedchar": "fchar",
                    "fixedbinary": "fbin"}.get(base, base)
            out.append(["%s(%s)" % (base, args), nullable])
        else:
            out.append([GO_T.get(t, t), nullable])
    return out

# Spark stores time in microseconds, so timestamp_ntz is exactly precision_timestamp(6).
SPARK_T = {"timestamp_ntz": "precision_timestamp(6)", "bigint": "i64", "int": "i32", "smallint": "i16", "tinyint": "i8", "string": "str",
           "boolean": "bool", "double": "fp64", "float": "fp32", "binary": "bin"}
CALCITE_T = {"BIGINT": "i64", "INTEGER": "i32", "SMALLINT": "i16", "TINYINT": "i8",
             "VARCHAR": "str", "CHAR": "str", "BOOLEAN": "bool", "DOUBLE": "fp64",
             "FLOAT": "fp32", "REAL": "fp32", "VARBINARY": "bin", "BINARY": "bin"}

def parse_spark(s):
    """[c0:bigint, r:decimal(11,2)?] - Spark type names."""
    return _mapped(s, SPARK_T)

def parse_calcite(s):
    """[c0:BIGINT, r:DECIMAL(11,2)?] - Calcite type names.

    Calcite names parameterized strings and time its own way: VARCHAR(10) is vchar(10), CHAR(5) is
    fchar(5), BINARY(4) is fbin(4), and TIMESTAMP(n) is precision_timestamp(n). Without this
    mapping the difference in vocabulary would count as a divergence in derivation.
    """
    m = re.match(r"^\[(?:[^:\[\]]*:)?ROW\[([^\[\]]+)\](\??)\]$", s.strip())
    if m:
        inner = [CALCITE_T.get(x.strip().split(":")[-1], x.strip().split(":")[-1])
                 for x in m.group(1).split(",")]
        return [["struct(%s)" % ",".join(inner), m.group(2) == "?"]]
    got = _mapped(s, CALCITE_T)
    if got is None:
        return None
    out = []
    for t, nullable in got:
        m = re.match(r"^(VARCHAR|CHAR|BINARY|TIMESTAMP)\((\d+)\)$", t)
        if m:
            base = {"VARCHAR": "vchar", "CHAR": "fchar", "BINARY": "fbin",
                    "TIMESTAMP": "precision_timestamp"}[m.group(1)]
            out.append(["%s(%s)" % (base, m.group(2)), nullable])
        else:
            out.append([t, nullable])
    return out

def parse_duckdb(s):
    """[c0:BIGINT, c1:VARCHAR] - SQL type names."""
    return _mapped(s, DUCKDB_T)

def parse_acero(s):
    """[c0:int64, c1:string?] - lowercase Arrow names."""
    return _mapped(s, ACERO_T)

path, fmt = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "java")
parse = {"java": parse_java, "py": parse_py, "df": parse_df,
         "duckdb": parse_duckdb, "acero": parse_acero, "go": parse_go,
         "spark": parse_spark, "calcite": parse_calcite}[fmt]
# Participants that carry no nullability in a comparable form. For them types, arity and column
# order are compared; comparing nullability would record the boundary of their type system as a
# divergence.
# Acero is NOT here: its probe prints f.nullable from the Arrow schema, so the participant does
# carry nullability and it can be compared. Switching that comparison off was a mistake - it
# inflated the number of matches.
TYPES_ONLY = {"duckdb"}

ok = bad = skipped = unparsed = disputed = unsupported = 0
seen = {}
unknown = []
# A column's header is separated from its data by a blank line - that is how normalize.py writes it.
# The header is cut off structurally rather than by the look of its first word: a boundary line can
# start with a lowercase letter, and guessing by look took it for a substituted case name.
in_header = True
for line in open(path, encoding="utf-8"):
    line = line.rstrip()
    if in_header:
        if not line:
            in_header = False
        continue
    if not line:
        continue
    name, _, rest = line.partition(" ")
    name = name.strip()
    # A name that is in neither the expectations nor the disputed list is not a case: it is a
    # column header, a boundary line or noise. Such lines used to count as a case "without an
    # expectation", so the header added a spurious one to the report.
    if name not in EXPECTED and name not in DISPUTED:
        unknown.append(name)
        continue
    seen[name] = seen.get(name, 0) + 1
    exp = EXPECTED.get(name)
    if exp is None:
        skipped += 1
        disputed += 1
        continue
    answer = rest.strip()
    # "The participant does not support this case" and "we could not read the answer" are different
    # things and must not be merged: the first is a fact about the implementation, the second a
    # defect in the check.
    if answer in ("", "—") or answer.startswith(("ERROR", "— ", "—\t")):
        unsupported += 1
        continue
    got = parse(answer)
    if got is None:
        unparsed += 1
        print("  %-34s unparsed answer: %s" % (name, answer[:50]))
        continue
    want = exp["schema"]
    if fmt in TYPES_ONLY:
        got = [[t, None] for t, _ in got]
        want = [[t, None] for t, _ in want]
    if got == want:
        ok += 1
    else:
        bad += 1
        print("  %-34s expected %s" % (name, want))
        print("  %-34s got      %s" % ("", got))

# Completeness of the set is checked separately and before the summary. Without it an empty file
# gave "matched: 0, differed: 0" and exit 0, so an absence of data looked like success; and a column
# with one case duplicated in place of another passed on line count.
# The set is checked for exact equality with EXPECTED union DISPUTED rather than for covering the
# expectations alone: otherwise a disputed case could be replaced with an invented one and the check
# still returned zero.
incomplete = 0
WANT = set(EXPECTED) | set(DISPUTED)
missing = sorted(WANT - set(seen))
dupes = sorted(n for n, c in seen.items() if c > 1)
if missing:
    incomplete = 1
    print("INCOMPLETE: the column has no answer for %d cases: %s"
          % (len(missing), ", ".join(missing[:6]) + (" ..." if len(missing) > 6 else "")))
if dupes:
    incomplete = 1
    print("INCOMPLETE: cases appearing more than once: %s" % ", ".join(dupes[:6]))
# Header and boundary lines are dropped in silence; a name that looks like a case is not, because a
# substituted name has to surface rather than dissolve into "other".
suspect = [u for u in unknown if "_" in u and not u.endswith(":")]
if suspect:
    incomplete = 1
    print("INCOMPLETE: the column has names that are in neither the expectations nor the disputed list: %s"
          % ", ".join(sorted(set(suspect))[:6]))

if fmt in TYPES_ONLY:
    print("(compared without nullability: the participant does not carry it in its logical types)")
print("matched: %d, differed: %d, unsupported by the participant: %d, unparsed by the check: %d, "
      "without an expectation: %d (of which disputed by the spec: %d)"
      % (ok, bad, unsupported, unparsed, skipped, disputed))
sys.exit(1 if bad or unparsed or incomplete else 0)
