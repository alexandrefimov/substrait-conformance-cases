"""The return type of every function call in a plan, derived from the plan and the specification.

    python3 -m deriver.calls <plan.json>          # one line per call
    python3 -m deriver.calls --json <plan.json>   # the records, as data
    python3 -m deriver.calls --lied               # the declaration swap, over both corpora

    SUBSTRAIT_DIR=<substrait checkout>            required: the extension files are read from it

A call's `output_type` is the producer's statement of what the call returns, and algebra.proto says
what it has to be: "the return type of the function, exactly as derived using the declaration in
the extension". This file does that derivation, for every call in the plan whether or not it
reaches the output schema, so that a comparison written elsewhere can put each declaration beside
it. Nothing here reads `output_type`: an argument's type comes from deriving the argument, a
column's from the relation rules in deriver/derive.py, and a call's from extensions.resolve().

Each call gets one record:

  path    where the call message is in the protobuf JSON, `relations[0].root.input.project...`
  kind    scalar, aggregate or window: which message it is, not which kind of function it names
  anchor  its function reference; name and urn, what the plan's declaration of that anchor says
  status  derived; unbound, when the rules bind the name, URN and argument types to no
          implementation; declined, when this deriver has no rule for something the call needs
  type    when derived, in the notation DERIVED.txt uses; binding, "signature" or "name"
  reason  one line, when not derived

A call is found in two passes. The first walks the whole document for call messages, so that every
call has a record. The second walks the relations and gives each expression the columns it is
evaluated over; a call only the first pass reached is declined with a reason saying so.
"""
import json, os, subprocess, sys, tempfile

from . import derive, type_model as types
from .type_model import Unbound, Unsupported

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# The Expression fields that are calls, and which message each one is.
CALL_FIELDS = {"scalarFunction": "scalar", "windowFunction": "window"}

# The physical joins say "Same as the Join operator" for their inputs and output order.
JOINS = ("join", "hashJoin", "mergeJoin", "nestedLoopJoin")

# Child relations, walked as relations rather than as expressions.
CHILD_RELS = ("input", "left", "right", "inputs", "viewDefinition")

# Parts of a relation that hold no expression over its input.
NOT_EXPRESSIONS = ("common", "advancedExtension")


def derive_calls(doc):
    """One record per function call in the plan, in document order."""
    walk = _Walk(doc)
    return walk.records()


class _Walk:
    def __init__(self, doc):
        self.doc = doc
        self.plan = derive.Plan(doc)
        self.found = {}
        self.typed = {}
        _scan(doc, "", self.found, None)
        for i, rel in enumerate(doc.get("relations", [])):
            if "root" in rel:
                self.rel(rel["root"].get("input"), "relations[%d].root.input" % i)
            elif "rel" in rel:
                self.rel(rel["rel"], "relations[%d].rel" % i)

    def records(self):
        out = []
        for path, (kind, body) in self.found.items():
            anchor = body.get("functionReference", 0)
            urn, name = self.plan.functions.get(anchor, (None, None))
            if anchor in self.plan.broken:
                name = self.plan.broken[anchor][0]
            record = {"path": path, "kind": kind, "anchor": anchor, "name": name, "urn": urn}
            record.update(self.typed.get(path) or {
                "status": "declined",
                "reason": "no relation rule here gives this call the columns it is evaluated over"})
            out.append(record)
        return out

    # ------------------------------------------------------------------ relations

    def schema(self, node):
        """A relation's output schema, or the reason it is not derived, as (columns, why)."""
        try:
            return derive.rel_schema(node, self.plan), None
        except Unsupported as why:
            return None, str(why)
        except (KeyError, TypeError, ValueError, AttributeError) as why:
            return None, "a malformed relation: %s %s" % (type(why).__name__, why)

    def rel(self, node, path):
        if not isinstance(node, dict) or len(node) != 1:
            return
        (kind, rel), = node.items()
        at = "%s.%s" % (path, kind)
        if not isinstance(rel, dict):
            return
        if kind in JOINS:
            return self._join(kind, rel, at)
        if kind == "lateralJoin":
            return self._lateral_join(rel, at)
        if kind == "read":
            return self._read(rel, at)
        if kind == "update":
            # The condition is "to be met for the update to be applied on a record" of the named
            # table, and a transformation applies to one of its columns: the only record an update
            # has is the table's, which `table_schema` holds ("The full schema of the named_table").
            scope = self._schema_of(lambda: types.from_named_struct(rel["tableSchema"]))
            for key in ("condition", "transformations"):
                self.expr(rel.get(key), "%s.%s" % (at, key), *scope)
            return
        # Every other relation evaluates its expressions over its one input, when it has one.
        scope = self.schema(rel["input"]) if "input" in rel else (None, "%s has no input" % kind)
        for key, value in rel.items():
            here = "%s.%s" % (at, key)
            if key in CHILD_RELS:
                if isinstance(value, list):
                    for i, child in enumerate(value):
                        self.rel(child, "%s[%d]" % (here, i))
                else:
                    self.rel(value, here)
            elif key in NOT_EXPRESSIONS:
                continue
            elif kind == "aggregate" and key == "measures":
                for i, m in enumerate(value):
                    where = "%s[%d]" % (here, i)
                    if isinstance(m.get("measure"), dict):
                        self.call("%s.measure" % where, "aggregate", m["measure"], *scope)
                        self.expr(m["measure"], "%s.measure" % where, *scope)
                    self.expr(m.get("filter"), "%s.filter" % where, *scope)
            elif kind == "window" and key == "windowFunctions":
                for i, w in enumerate(value):
                    self.call("%s[%d]" % (here, i), "window", w, *scope)
                    self.expr(w, "%s[%d]" % (here, i), *scope)
            else:
                self.expr(value, here, *scope)

    def _schema_of(self, compute):
        try:
            return compute(), None
        except Unsupported as why:
            return None, str(why)
        except (KeyError, TypeError, ValueError, AttributeError) as why:
            return None, "a malformed relation: %s %s" % (type(why).__name__, why)

    def _read(self, rel, at):
        # "A filter expression must be interpreted against the direct schema before the projection
        # expression has been applied", and the best effort filter "should be interpreted against
        # the direct schema" too - logical_relations.md, Read Operation.
        direct = self._schema_of(lambda: types.from_named_struct(rel["baseSchema"]))
        for key in ("filter", "bestEffortFilter"):
            self.expr(rel.get(key), "%s.%s" % (at, key), *direct)
        # A virtual table's rows are "literal values or expressions that can be resolved without
        # referencing any input data": evaluated over no columns at all.
        table = rel.get("virtualTable")
        if isinstance(table, dict):
            self.expr(table.get("expressions"), "%s.virtualTable.expressions" % at, [], None)

    def _join(self, kind, rel, at, left=None, right=None):
        # "All field references of Join Properties except Post-Join Filter are over this order",
        # the input order, left then right; the post-join filter's "correspond to the direct output
        # order of the join operation" - logical_relations.md, Join Operation. The direct output is
        # the relation's rule before its emit, which is what derive.RULES gives.
        left = left or self.schema(rel.get("left"))
        right = right or self.schema(rel.get("right"))
        both = ((left[0] + right[0], None) if left[0] is not None and right[0] is not None
                else (None, left[1] or right[1]))
        for key in ("expression", "residualExpression"):
            self.expr(rel.get(key), "%s.%s" % (at, key), *both)
        if "postJoinFilter" in rel:
            direct = self._schema_of(lambda: derive.RULES[kind](rel, self.plan))
            self.expr(rel["postJoinFilter"], "%s.postJoinFilter" % at, *direct)
        self.rel(rel.get("left"), "%s.left" % at)
        if kind != "lateralJoin":
            self.rel(rel.get("right"), "%s.right" % at)

    def _lateral_join(self, rel, at):
        # The right input "may reference fields of the current left row via
        # OuterReference.rel_reference", so it is walked with the join's rel_anchor bound to the
        # left input's columns, as derive._lateral_join binds it to derive the right side.
        left = self.schema(rel.get("left"))
        anchor = (rel.get("common") or {}).get("relAnchor")
        bind = anchor is not None and left[0] is not None and anchor not in self.plan.outer
        if bind:
            self.plan.outer[anchor] = left[0]
        try:
            right = self.schema(rel.get("right"))
            self.rel(rel.get("right"), "%s.right" % at)
        finally:
            if bind:
                del self.plan.outer[anchor]
        self._join("lateralJoin", rel, at, left, right)

    # ---------------------------------------------------------------- expressions

    def expr(self, node, path, fields, why):
        """Every call under this part of an expression, over the columns `fields`."""
        if isinstance(node, list):
            for i, item in enumerate(node):
                self.expr(item, "%s[%d]" % (path, i), fields, why)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            here = "%s.%s" % (path, key)
            if key in CALL_FIELDS and isinstance(value, dict):
                self.call(here, CALL_FIELDS[key], value, fields, why)
                self.expr(value, here, fields, why)
            elif key == "subquery" and isinstance(value, dict):
                self._subquery(value, here, fields, why)
            else:
                self.expr(value, here, fields, why)

    def _subquery(self, node, path, fields, why):
        # A subquery holds relations, which are walked as relations; its other parts - the
        # needles of an IN, the left side of a comparison - are expressions of the enclosing input.
        for kind, body in node.items():
            if not isinstance(body, dict):
                continue
            for key, value in body.items():
                here = "%s.%s.%s" % (path, kind, key)
                if key in ("input", "haystack", "tuples", "right"):
                    self.rel(value, here)
                else:
                    self.expr(value, here, fields, why)

    def call(self, path, kind, body, fields, why):
        if fields is None:
            self.typed[path] = {"status": "declined",
                                "reason": "the columns this call reads are not derived: %s" % why}
            return
        try:
            derived, how = derive.call_type(body, fields, self.plan, kind)
        except Unbound as refused:
            self.typed[path] = {"status": "unbound", "reason": str(refused)}
        except Unsupported as unknown:
            self.typed[path] = {"status": "declined", "reason": str(unknown)}
        except (KeyError, TypeError, ValueError, AttributeError) as bad:
            self.typed[path] = {"status": "declined",
                                "reason": "a malformed call: %s %s" % (type(bad).__name__, bad)}
        else:
            self.typed[path] = {"status": "derived", "type": types.render_field(derived),
                                "binding": how}


def _scan(node, path, found, parent):
    """Every call message in the document, found by its field name alone."""
    if isinstance(node, list):
        for i, item in enumerate(node):
            _scan(item, "%s[%d]" % (path, i), found, parent)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        here = "%s.%s" % (path, key) if path else key
        if key in CALL_FIELDS and isinstance(value, dict):
            found[here] = (CALL_FIELDS[key], value)
        elif key == "measure" and parent == "measures" and isinstance(value, dict):
            found[here] = ("aggregate", value)
        elif key == "windowFunctions" and isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    found["%s[%d]" % (here, i)] = ("window", item)
        _scan(value, here, found, key)


# ---------------------------------------------------------------- the declaration swap

# The two corpora the swap is run over: the plans, and the same plans reading virtual tables.
CORPORA = ("derived-schema", "derived-schema-virtual-tables")

def lied_check(corpus=None):
    """Derive every plan the declaration swap changes, before and after, and compare.

    probe/make_lied_corpus.py replaces each declared `output_type` it can with a wrong one and
    writes the plans it changed. If anything here read a declaration, some record or schema would
    move with it. Returns (plans compared, plans whose records or schema moved).
    """
    corpus = corpus or os.path.join(ROOT, "derived-schema")
    with tempfile.TemporaryDirectory() as out:
        subprocess.run([sys.executable, os.path.join(ROOT, "probe", "make_lied_corpus.py"),
                        corpus, out], check=True, capture_output=True)
        names = sorted(n for n in os.listdir(out) if n.endswith(".json"))
        moved = []
        for name in names:
            before = json.load(open(os.path.join(corpus, name), encoding="utf-8"))
            after = json.load(open(os.path.join(out, name), encoding="utf-8"))
            if (derive_calls(before) != derive_calls(after)
                    or _schema_or_reason(before) != _schema_or_reason(after)):
                moved.append(name[:-5])
    return len(names), moved


def _schema_or_reason(doc):
    try:
        return types.render_schema(derive.schema_of(doc))
    except Unsupported as why:
        return "not derived: %s" % why


def main(argv):
    if "--lied" in argv:
        failed = 0
        for corpus in CORPORA:
            compared, moved = lied_check(os.path.join(ROOT, corpus))
            if not compared:
                print("FAILED: the declaration swap changed no plan in %s, so nothing was compared"
                      % corpus)
                failed = 1
            elif moved:
                print("FAILED: the declaration swap moved the call records or schema of %d of %d "
                      "plans in %s: %s" % (len(moved), compared, corpus, ", ".join(moved)))
                failed = 1
            else:
                print("ok      the declaration swap changes %d plans in %s and moves no call "
                      "record or schema" % (compared, corpus))
        return failed
    paths = [a for a in argv[1:] if not a.startswith("--")]
    if len(paths) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    records = derive_calls(json.load(open(paths[0], encoding="utf-8")))
    if "--json" in argv:
        print(json.dumps(records, indent=1))
        return 0
    for r in records:
        detail = r["type"] if r["status"] == "derived" else r["reason"]
        print("%s  %s %s  %s  %s" % (r["path"], r["kind"], r["name"], r["status"], detail))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
