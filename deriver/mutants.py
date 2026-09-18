"""Which of the deriver's rules the corpus actually pins, measured by breaking them one at a time.

    SUBSTRAIT_DIR=<a substrait checkout> python3 -m deriver.mutants
    SUBSTRAIT_DIR=<...> python3 -m deriver.mutants --verbose   # also name the cases each one moves
    SUBSTRAIT_DIR=<...> python3 -m deriver.mutants --per-case  # what PINNED.txt holds

93 of 93 agreeing says the two readings match. It does not say the corpus would have noticed if
they had not: a rule reached by no case agrees with anything. So each rule here is replaced by
another reading of the same sentence - not by a random error - and the comparison is rerun. A
mutation the corpus catches is a rule some case pins. A mutation nothing catches is a rule this
repository states and does not check, and the agreement on it is worth nothing until a case exists.

The mutations are alternative readings on purpose. `RIGHT_SINGLE` emitting right-then-left rather
than left-then-right is what "the right and left inputs are switched" says on its own; the column
order comes from a different table. If the corpus cannot tell the two apart, then what looks like
a derivation agreeing with an expectation is two coin flips that happened to land alike.
"""
import io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

# (file, label, what the mutated rule would be reading instead, old, new)
MUTATIONS = [
    ("derive.py", "read: the projection mask is ignored",
     "a read whose ReadRel.projection selects nothing",
     "        fields = _mask(rel[\"projection\"], fields)", "        pass"),
    ("derive.py", "read: the mask is read in the order its items are listed",
     "struct_items as an order rather than a selection",
     "    if picked != sorted(picked):", "    if False:"),
    ("derive.py", "project: the new expressions come before the input",
     "\"the list of new expressions ... + the field order of the input\"",
     "    return fields + [expr_type(e, fields, plan) for e in rel.get(\"expressions\", [])]",
     "    return [expr_type(e, fields, plan) for e in rel.get(\"expressions\", [])] + fields"),
    ("derive.py", "emit: the output mapping is ignored",
     "emit as a hint rather than a projection",
     "    return [fields[i] for i in mapping]", "    return fields"),
    ("derive.py", "join inner: the right side becomes nullable",
     "a join making its right side optional in every type",
     '"JOIN_TYPE_INNER": ("both", ()),', '"JOIN_TYPE_INNER": ("both", ("right",)),'),
    ("derive.py", "join left: the right side stays required",
     "\"return the left record\" without the nulls clause",
     '"JOIN_TYPE_LEFT": ("both", ("right",)),', '"JOIN_TYPE_LEFT": ("both", ()),'),
    ("derive.py", "join right: the right side is nulled instead of the left",
     "\"switched\" applied to the nulls rather than to the inputs",
     '"JOIN_TYPE_RIGHT": ("both", ("left",)),', '"JOIN_TYPE_RIGHT": ("both", ("right",)),'),
    ("derive.py", "join left single: the right side stays required",
     "\"exactly one record from the right input matches\" read as a guarantee",
     '"JOIN_TYPE_LEFT_SINGLE": ("both", ("right",)),',
     '"JOIN_TYPE_LEFT_SINGLE": ("both", ()),'),
    ("derive.py", "join right single: the output is right then left",
     "\"the right and left inputs are switched\" applied to the column order",
     '"JOIN_TYPE_RIGHT_SINGLE": ("both", ("left",)),',
     '"JOIN_TYPE_RIGHT_SINGLE": ("both-swapped", ("left",)),'),
    ("derive.py", "join right mark: the mark is appended to the left side",
     "the mark join always keeping the left columns",
     '"JOIN_TYPE_RIGHT_MARK": ("right+mark", ()),', '"JOIN_TYPE_RIGHT_MARK": ("left+mark", ()),'),
    ("derive.py", "join mark: the mark column is required",
     "the mark as a computed flag that always has a value",
     'MARK_COLUMN = Type("boolean", (), True)', 'MARK_COLUMN = Type("boolean", (), False)'),
    ("derive.py", "join outer: neither side becomes nullable",
     "\"Return all records from both\" without the clause about nulls for the opposite input",
     '"JOIN_TYPE_OUTER": ("both", ("left", "right")),', '"JOIN_TYPE_OUTER": ("both", ()),'),
    ("derive.py", "join left anti: both sides are returned",
     "the anti join as a filtered inner join rather than as one side",
     '"JOIN_TYPE_LEFT_ANTI": ("left", ()),', '"JOIN_TYPE_LEFT_ANTI": ("both", ()),'),
    ("derive.py", "join right anti: the left side is returned",
     "\"switched\" applied to the output side rather than to the inputs",
     '"JOIN_TYPE_RIGHT_ANTI": ("right", ()),', '"JOIN_TYPE_RIGHT_ANTI": ("left", ()),'),
    ("derive.py", "join right semi: the left side is returned",
     "the same reading of \"switched\", on the semi join",
     '"JOIN_TYPE_RIGHT_SEMI": ("right", ()),', '"JOIN_TYPE_RIGHT_SEMI": ("left", ()),'),
    ("derive.py", "join left mark: the mark is appended to the right side",
     "the mark column following the side that is probed rather than the side that is returned",
     '"JOIN_TYPE_LEFT_MARK": ("left+mark", ()),', '"JOIN_TYPE_LEFT_MARK": ("right+mark", ()),'),
    ("derive.py", "join semi: both sides are returned",
     "the semi join as an inner join that drops duplicates",
     '"JOIN_TYPE_LEFT_SEMI": ("left", ()),', '"JOIN_TYPE_LEFT_SEMI": ("both", ()),'),
    ("derive.py", "cross: the output becomes nullable",
     "the cross product as an outer join over everything",
     '    return rel_schema(rel["left"], plan) + rel_schema(rel["right"], plan)',
     '    return [f.with_nullable(True) for f in\n'
     '            rel_schema(rel["left"], plan) + rel_schema(rel["right"], plan)]'),
    ("derive.py", "set minus: nullable if any input is",
     "the union rule applied to minus",
     "        return primary                                          "
     '# "The same as the primary input."',
     "        return any(per_input)"),
    ("derive.py", "set intersection primary: the multiset rule",
     "one intersection rule for all three operations",
     "        return primary and any(secondary)", "        return all(per_input)"),
    ("derive.py", "set intersection multiset: nullable if any input is",
     "\"required in any\" read as \"nullable in any\"",
     "        return all(per_input)", "        return any(per_input)"),
    ("derive.py", "set union: required if any input is",
     "\"nullable in any\" read the other way round",
     "        return any(per_input)", "        return all(per_input)"),
    ("derive.py", "set: the field types come from the last input",
     "\"the field order of the inputs\" with no primary",
     "        out.append(column_types[0].with_nullable(",
     "        out.append(column_types[-1].with_nullable("),
    ("derive.py", "aggregate: measures come before the grouping expressions",
     "the measures list read as the left-hand columns",
     "    for m in rel.get(\"measures\", []):\n"
     "        out.append(_call(m[\"measure\"], fields, plan, \"aggregate\"))",
     "    out = [_call(m[\"measure\"], fields, plan, \"aggregate\")\n"
     "           for m in rel.get(\"measures\", [])] + out"),
    ("derive.py", "aggregate: a grouping expression is nullable only if in no set",
     "\"absent from all\" rather than \"absent from some\"",
     "        in_every_set = all(i in g.get(\"expressionReferences\", []) for g in groupings)",
     "        in_every_set = any(i in g.get(\"expressionReferences\", []) for g in groupings)"),
    ("derive.py", "aggregate: the grouping-set index is always appended",
     "\"(if applicable)\" read as unconditional, as Expand's is",
     "    if len(groupings) > 1:", "    if groupings:"),
    ("derive.py", "aggregate: the grouping-set index is never appended",
     "\"(if applicable)\" read as never, since no sentence forces it",
     "    if len(groupings) > 1:", "    if False:"),
    ("derive.py", "the appended index column is nullable",
     "an i32 whose nullability no page states",
     'INDEX_COLUMN = Type("i32", (), False)', 'INDEX_COLUMN = Type("i32", (), True)'),
    ("derive.py", "the appended index column is i64",
     "algebra.proto's int64 rather than the documentation's i32",
     'INDEX_COLUMN = Type("i32", (), False)', 'INDEX_COLUMN = Type("i64", (), False)'),
    ("derive.py", "expand: no duplicate-index column",
     "Expand's index carrying the same \"(if applicable)\" as Aggregate's",
     "    return out + [INDEX_COLUMN]", "    return out"),
    ("derive.py", "expand: the index column comes first",
     "\"followed by\" read as leading the expand fields",
     "    return out + [INDEX_COLUMN]", "    return [INDEX_COLUMN] + out"),
    ("derive.py", "expand: a switching field is required if any duplicate is",
     "the nullability sentence in algebra.proto read the other way",
     "            out.append(duplicates[0].with_nullable(any(t.nullable for t in duplicates)))",
     "            out.append(duplicates[0].with_nullable(all(t.nullable for t in duplicates)))"),
    ("derive.py", "window: the window columns come before the input",
     "\"input followed by each window expression\" reversed",
     "    return fields + [_call(c, fields, plan, \"window\") for c in calls]",
     "    return [_call(c, fields, plan, \"window\") for c in calls] + fields"),
    ("derive.py", "write: the output is the declared table schema",
     "WriteRel.table_schema as the output rather than the input",
     "    return rel_schema(rel[\"input\"], plan)",
     "    return (types.from_named_struct(rel[\"tableSchema\"]) if \"tableSchema\" in rel\n"
     "            else rel_schema(rel[\"input\"], plan))"),
    ("derive.py", "ddl: the output is the declared table schema",
     "DdlRel.table_schema as the output: the view's columns rather than none",
     "    return []", "    return types.from_named_struct(rel[\"tableSchema\"])"),
    ("derive.py", "ddl: the output is the view definition's",
     "the view body as the one input the signature counts, passed through as a write's is",
     "    return []", "    return rel_schema(rel[\"viewDefinition\"], plan)"),
    ("extensions.py", "functions: MIRROR does not propagate nullability",
     "the return type expression alone deciding, as in DECLARED_OUTPUT",
     "        return derived.with_nullable(any(a.nullable for a in args))", "        return derived"),
    ("extensions.py", "functions: DECLARED_OUTPUT mirrors its arguments",
     "MIRROR applied to every function",
     '    if impl.nullability == "MIRROR":', "    if True:"),
    ("extensions.py", "functions: the phase does not select the intermediate type",
     "the phases as execution detail with no effect on the type",
     '    if phase in ("AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE",',
     '    if False and phase in ("AGGREGATION_PHASE_INITIAL_TO_INTERMEDIATE",'),
]

# The mutation above that needs a rule the deriver does not otherwise have: a join emitting its
# right columns before its left ones.
SWAPPED = ('    return {"both": left + right, "left": left, "right": right,',
           '    return {"both": left + right, "both-swapped": right + left,\n'
           '            "left": left, "right": right,')


def expectations():
    doc = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))
    return {c: [[t, bool(n)] for t, n in e["schema"]] for c, e in doc["expected"].items()}


def answers():
    """The deriver's schema per case, in a fresh interpreter so a mutated source is really read.

    A fresh interpreter is not enough on its own. CPython validates a cached .pyc against the
    source's size and its mtime in whole seconds, and several mutations here change neither - `any`
    for `all` is the same length, and a rewrite lands in the same second as the one before it. The
    subprocess then imported the previous mutation's bytecode and the run reported another
    mutation's moved cases as this one's. Writing no bytecode at all removes the question.
    """
    out = subprocess.run([sys.executable, "-B", "-m", "deriver.run", "--column"],
                         capture_output=True, text=True, cwd=ROOT,
                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if out.returncode != 0:
        return None
    got = {}
    for line in out.stdout.splitlines():
        if line.startswith(("#", "DERIVER")) or not line.strip():
            continue
        name, _, answer = line.partition(" ")
        got[name] = answer.strip()
    return got


def per_case(moved_by, want):
    """Per case: how many readings it tells apart, and the ones only it tells apart.

    The count on its own is not a measure of a case. A zero means one of two things, and neither is
    a hole: `setdata_*` asserts the rows of a set operation and its schema rule is pinned by the
    `setop_*` case beside it, and a bare read has no second reading to state - "Direct Schema
    defines the schema of the output of the read" says one thing only. What survives being read
    alone is the second column: a reading only one case tells apart is a reading that stops being
    checked the day that case is removed, and that holds however many readings the battery has.
    """
    counts = {c: 0 for c in want}
    sole = {}
    for label, cases in moved_by.items():
        for c in cases:
            counts[c] += 1
        if len(cases) == 1:
            sole.setdefault(cases[0], []).append(label)
    return counts, sole


def main(argv):
    verbose = "--verbose" in argv
    want = expectations()
    base = answers()
    if base is None:
        print("FAILED: the unmutated deriver does not run", file=sys.stderr)
        return 2
    sources = {name: io.open(os.path.join(HERE, name), encoding="utf-8").read()
               for name in {m[0] for m in MUTATIONS}}
    caught, missed, moved_by = [], [], {}
    try:
        for name, label, reading, old, new in MUTATIONS:
            text = sources[name]
            if old not in text:
                print("FAILED: %s no longer contains the text for %r" % (name, label))
                return 2
            mutated = text.replace(old, new, 1)
            if "both-swapped" in new:
                mutated = mutated.replace(SWAPPED[0], SWAPPED[1], 1)
            io.open(os.path.join(HERE, name), "w", encoding="utf-8").write(mutated)
            got = answers()
            moved = ([] if got is None else
                     sorted(c for c in want if base.get(c) != got.get(c)))
            moved_by[label] = moved
            (caught if (got is None or moved) else missed).append((label, reading, moved))
            io.open(os.path.join(HERE, name), "w", encoding="utf-8").write(text)
    finally:
        for name, text in sources.items():
            io.open(os.path.join(HERE, name), "w", encoding="utf-8").write(text)

    if "--per-case" in argv:
        counts, sole = per_case(moved_by, want)
        print("Which case pins which rule: probe by deriver/mutants.py --per-case.")
        print()
        print("Per scored case: how many of the %d alternative readings in deriver/mutants.py its"
              % len(MUTATIONS))
        print("answer tells apart, and, after ->, the readings no other case tells apart. A case")
        print("with none of the second kind can be removed without any rule going unchecked; one")
        print("with some cannot. A count of 0 is not a hole - see per_case() in that file.")
        print()
        for case in sorted(counts):
            tail = ("  -> " + "; ".join(sorted(sole[case]))) if case in sole else ""
            print("%-46s %d%s" % (case, counts[case], tail))
        return 0

    print("%d alternative readings: %d the corpus tells apart, %d it does not"
          % (len(MUTATIONS), len(caught), len(missed)))
    if verbose:
        print("\ntold apart:")
        for label, _, moved in caught:
            print("  %-56s %d case(s): %s" % (label, len(moved), ", ".join(moved[:3])))
    print("\nnot told apart - the rule is stated here and checked by nothing:")
    for label, reading, _ in missed:
        print("  %s\n      the other reading: %s" % (label, reading))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
