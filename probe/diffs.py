"""Writes results/DIFFS.md: per implementation, the cases that differ and what came of them.

    python3 probe/diffs.py > results/DIFFS.md

The README asks the maintainer of an implementation to take the cases that differ for theirs. Until
this file existed, that meant joining two levels of `differed.json` by hand - `cells` maps a case to
the key of a reason, `rules` holds the reason and what came of it - and then finding the answer in a
column and the expectation in `expected.json`. Four files to read before seeing one difference is
not an invitation.

So the join is done here, once, per participant: the case, what the spec says it should derive, what
that build answered, why it is recorded as a difference and what came of it. Nothing here is new
evidence; it is the same cells the picture draws, which is why it is built from the same model as
the picture rather than from a second reading of the columns.
"""
import io, json, os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "probe"))

import heatmap  # noqa: E402  - the model the picture is drawn from, read rather than repeated

OUTCOME = {"reported": "reported", "spec-question": "asked of the spec",
           "ours": "ours — the expectation or this harness is wrong", "open": "open"}

# The three kinds differed.json sorts a cell into, in the words the picture's legend uses.
KIND = {"divergence": "a divergence", "boundary": "a limit of this type system",
        "unresolved": "a type this participant never resolved"}


def main():
    model = heatmap.build()
    differed = json.load(io.open(os.path.join(ROOT, "differed.json"), encoding="utf-8"))
    stems = {label: stem for label, stem, _ in heatmap.COLUMNS}
    index = {case: i for i, case in enumerate(model["cases"])}

    out = []
    w = out.append
    w("# Where each implementation differs")
    w("")
    w("Written by `probe/diffs.py`; `probe/selfcheck.sh` checks it against the saved columns.")
    w("")
    w("If you maintain one of these implementations, this page is for you: it lists your cases, what")
    w("the spec says each should derive, what your build answered, why it is recorded as a")
    w("difference, and what came of it. The plans are")
    w("in [`derived-schema/`](../derived-schema), and [`derived-schema-virtual-tables/`]"
      "(../derived-schema-virtual-tables) has the same cases carrying their own rows, which need no")
    w("table registered and no part of this harness. A difference is measured against this")
    w("repository's reading of the spec, not against your own tests: some of these are questions")
    w("for the spec and some are ours, and each says which.")
    w("")
    w("Columns taken %s. [FINDINGS.md](../FINDINGS.md) maps the reports the other way, from a"
      % model["taken"])
    w("finding to its reproducers.")

    for label in model["participants"]:
        stem = stems[label]
        cells = differed["cells"].get(stem, {})
        if not cells:
            continue
        w("")
        w("## %s — %d cases" % (label, len(cells)))
        w("")
        w("`results/%s.txt`, %s." % (stem, model["versions"][label]))
        reach = model["boundaries"].get(label, "")
        if reach:
            w("")
            # Verbatim: these notes start with a name as often as with a verb, and lowercasing the
            # first letter turned DataFusion into dataFusion.
            w("How far this column goes. %s" % reach)
        by_rule = {}
        for case, key in sorted(cells.items()):
            by_rule.setdefault(key, []).append(case)
        for key in sorted(by_rule):
            rule = differed["rules"][key]
            triage = rule.get("triage", {}).get(stem, {})
            state = OUTCOME.get(triage.get("outcome", ""), triage.get("outcome", ""))
            links = " ".join(triage.get("at", []))
            w("")
            w("### `%s`" % key)
            w("")
            w("%s" % rule["what"])
            w("")
            w("Recorded as %s%s%s"
              % (KIND.get(rule["kind"], rule["kind"]),
                 ", %s" % state if state else "",
                 ". %s" % links if links else "."))
            note = triage.get("note")
            if note:
                w("")
                w(note[0].upper() + note[1:] + ("" if note.endswith(".") else "."))
            w("")
            w("| case | expected | %s answered | the expectation comes from |" % label)
            w("| --- | --- | --- | --- |")
            for case in by_rule[key]:
                answer = model["answers"][index[case]][model["participants"].index(label)][0]
                w("| [%s](../derived-schema/%s.json) | `%s` | `%s` | %s |"
                  % (case, case, model["expected"][case], answer, model["why"][case]))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.stdout.write(main())
