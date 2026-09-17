"""Runs the deriver over the corpus and compares its answers with the saved expectations.

    python3 -m deriver.run                # the report: agreements, differences, declined cases
    python3 -m deriver.run --column       # one line per case, "<case> <schema>"
    python3 -m deriver.run --json         # the same, as data

    SUBSTRAIT_DIR=<substrait checkout>    required: the extension files are read from it

The comparison is the point of the program and also its only defence. `probe/expected.py` writes an
expectation case by case; this derives one from the same specification by a different route, so a
case where the two agree has had its rule read twice. A case where they differ is either a mistake
here, a mistake there, or a sentence in the specification that does not decide the question - and
the third kind is what nobody finds by reading a rule once.

Which is why a difference is printed with the expectation's own stated source beside it, and why a
case this deriver cannot answer is counted separately from one it answers wrongly. Declining is an
answer; guessing would be indistinguishable from deriving.
"""
import json, os, sys

from . import derive, extensions, types
from .types import Unsupported

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CASES = os.path.join(ROOT, "derived-schema")


def expectations():
    doc = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))
    return doc["expected"], doc["disputed"], set(doc["spec_silent"]) | set(doc["spec_says_invalid"])


def cases():
    manifest = json.load(open(os.path.join(CASES, "manifest.json"), encoding="utf-8"))
    return [(e["case"], os.path.join(CASES, e["plan"])) for e in manifest]


def derived(path):
    """This deriver's answer for one plan: a column list, or the reason it declined."""
    doc = json.load(open(path, encoding="utf-8"))
    try:
        return derive.schema_of(doc), None
    except Unsupported as why:
        return None, str(why)


def main(argv):
    expected, disputed, unscored = expectations()
    rows, report = [], []
    for name, path in cases():
        schema, why = derived(path)
        rows.append((name, types.render_schema(schema) if schema else None, why))
        if name in expected:
            want = [[t, bool(n)] for t, n in expected[name]["schema"]]
            got = None if schema is None else [[types.render(f), f.nullable] for f in schema]
            report.append((name, "declined" if got is None else
                           "agree" if got == want else "differ", got, want,
                           expected[name].get("source", ""), why))
        else:
            report.append((name, "unscored" if name in unscored or name in disputed
                           else "no expectation", None if schema is None else
                           [[types.render(f), f.nullable] for f in schema], None, "", why))

    if "--column" in argv:
        # The saved answers, with what they were derived from at the top. No date: unlike a
        # participant column, nothing here is a measurement of a build, so two runs against the
        # same pinned files must print the same bytes, and deriver/check.py can diff them.
        print("DERIVER: relation output schemas derived from the Substrait specification at %s"
              % extensions.SPEC_REF)
        for path, sha in sorted(extensions.library().read.items()):
            if path in extensions.pinned():
                print("#  %s  %s" % (sha, path))
        print()
        for name, schema, why in rows:
            print("%-46s %s" % (name, schema if schema else "not-derived: %s" % why))
        return 0
    if "--json" in argv:
        print(json.dumps([{"case": n, "verdict": v, "derived": g, "expected": w,
                           "source": s, "declined": d}
                          for n, v, g, w, s, d in report], indent=1))
        return 0

    tally = {}
    for _, verdict, _, _, _, _ in report:
        tally[verdict] = tally.get(verdict, 0) + 1
    print("extension files read at %s:" % extensions.SPEC_REF)
    for path, sha in sorted(extensions.library().read.items()):
        if path in extensions.pinned():
            print("  %s  %s" % (sha, path))
    print()
    print("%d cases: %s" % (len(report), ", ".join("%s %d" % (k, tally[k])
                                                   for k in sorted(tally))))
    for kind, title in (("differ", "differs from the expectation"),
                        ("declined", "not derived")):
        named = [r for r in report if r[1] == kind]
        if not named:
            continue
        print("\n%s (%d):" % (title, len(named)))
        for name, _, got, want, source, why in named:
            if kind == "differ":
                print("  %s\n    derived  %s\n    expected %s\n    from     %s"
                      % (name, _render(got), _render(want), source))
            else:
                print("  %-46s %s" % (name, why))
    unanswered = [r for r in report if r[1] in ("unscored", "no expectation")]
    if unanswered:
        print("\nno expectation to compare against (%d):" % len(unanswered))
        for name, verdict, got, _, _, why in unanswered:
            print("  %-46s %s" % (name, _render(got) if got else "not derived: %s" % why))
    return 1 if tally.get("differ") else 0


def _render(schema):
    if schema is None:
        return "-"
    return "[%s]" % ", ".join(t + ("?" if n else "") for t, n in schema)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
