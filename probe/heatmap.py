"""Draws the matrix: the SVG the README shows and the page the site serves, from one model.

    python3 probe/heatmap.py svg-light > docs/matrix.svg
    python3 probe/heatmap.py svg-dark  > docs/matrix-dark.svg
    python3 probe/heatmap.py page      > docs/index.html

Every cell is a verdict, and the verdicts are not recomputed here: this imports the parsers and the
expectations out of probe/check_expected.py and compares the same way it does, so a picture that
disagrees with the numbers in the README is not possible - it would have to disagree with the check
that produces them. probe/selfcheck.sh diffs each output against the committed file.

Three drawing decisions carry the reading of the matrix and are not cosmetic:

  - Silence is never a colour. A participant that refuses a plan gets an empty outline, because
    "does not accept this plan" is a fact about support, and painting it on a good-to-bad ramp
    would read as a wrong answer. Acero alone refuses 55 of the 73 scored cases.
  - A limit of a type system is drawn apart from a divergence. DuckDB carries no nullability and
    neither it nor DataFusion has a string with a length; those cells are hatched, not red.
  - Matched is the quiet fill and divergence the only loud one, so the eye lands on the 83 cells
    where a participant could have given the expected answer and gave another.
"""
import html, io, json, os, re, sys

import script_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The columns, in the order the README lists them. Gluten is not here: its column is taken in a
# cluster, carries its own date, and is not scored against the expectations.
COLUMNS = [("substrait-java", "JAVA", "java"), ("substrait-python", "PYTHON", "py"),
           ("substrait-go", "GO", "go"), ("substrait-validator", "VALIDATOR", "py"),
           ("Isthmus/Calcite", "ISTHMUS", "calcite"), ("DataFusion", "DATAFUSION", "df"),
           ("DuckDB", "DUCKDB", "duckdb"), ("Spark", "SPARK", "spark"), ("Acero", "ACERO", "acero")]
SHORT = {"substrait-java": "java", "substrait-python": "python", "substrait-go": "go",
         "substrait-validator": "validator", "Isthmus/Calcite": "Isthmus",
         "DataFusion": "DataFusion", "DuckDB": "DuckDB", "Spark": "Spark", "Acero": "Acero"}

# Cases are grouped by the prefix of their name, which is how the generators name them. A prefix
# with no label here still gets its own group under its own name rather than dissolving into the
# previous one, so a case added later is visible in the picture without editing this list.
GROUP_ORDER = ["read", "control", "virtual", "aggregate", "join", "joineq", "setop", "setdata",
               "emit", "decimal", "phase", "precision", "narrowing", "stringlen", "ctas"]
GROUP_LABEL = {"read": "Column selection at the read", "control": "Controls",
               "virtual": "Virtual table rows against the declared schema",
               "aggregate": "Grouping sets", "join": "Joins, condition true",
               "joineq": "Joins, equality condition", "setop": "Set operations: schema",
               "setdata": "Set operations: rows", "emit": "Emit mapping",
               "decimal": "Decimal arithmetic", "phase": "Aggregation phase",
               "precision": "precision_timestamp", "narrowing": "Narrowing to required",
               "stringlen": "String types carrying a length", "ctas": "CTAS",
               "window": "Window frames and bounds", "expand": "Expand",
               "cross": "Cross product", "topn": "Top-N",
               "physjoin": "Physical joins"}

MATCH, DIVERGENCE, BOUNDARY, UNRESOLVED, UNSUPPORTED, NOSPEC = range(6)
STATE_NAME = {MATCH: "matched", DIVERGENCE: "divergence", BOUNDARY: "type-system boundary",
              UNRESOLVED: "unresolved", UNSUPPORTED: "not accepted", NOSPEC: "no expectation"}
STATE_NOTE = {
    MATCH: "the derived schema is the expected one",
    DIVERGENCE: "a different answer, and the type system could have given the expected one",
    BOUNDARY: "the expectation is not expressible in this type system",
    UNRESOLVED: "no type came back rather than a different one",
    UNSUPPORTED: "the implementation does not accept this plan",
    NOSPEC: "the spec does not settle this case",
}
KIND_STATE = {"divergence": DIVERGENCE, "boundary": BOUNDARY, "unresolved": UNRESOLVED}


def check_expected():
    """probe/check_expected.py, up to the point where it starts reading argv.

    Importing it whole is not possible - it runs on import - and rewriting its parsers here would
    put a second implementation of the comparison next to the first, which is the failure this
    repository is about."""
    src = io.open(os.path.join(ROOT, "probe/check_expected.py"), encoding="utf-8").read()
    ns = {"__name__": "check_expected", "__file__": os.path.join(ROOT, "probe/check_expected.py")}
    exec(compile(src[:src.index("# --- the command line starts here ---")], "check_expected.py", "exec"), ns)
    return ns


def build():
    ns = check_expected()
    expected, disputed = ns["EXPECTED"], ns["DISPUTED"]
    differed = json.load(io.open(os.path.join(ROOT, "differed.json"), encoding="utf-8"))
    refused = json.load(io.open(os.path.join(ROOT, "refused.json"), encoding="utf-8"))
    overlap = set(differed["rules"]) & set(refused["rules"])
    if overlap:
        raise SystemExit("FAILED: differed.json and refused.json reuse rule ids: %s"
                         % ", ".join(sorted(overlap)))
    # DuckDB is the one participant compared without nullability; check_expected.py says why.
    types_only = {"duckdb"}

    taken, versions, boundaries, cells, answers, tracking = set(), {}, {}, {}, {}, {}
    for label, name, fmt in COLUMNS:
        path = os.path.join(ROOT, "results/%s.txt" % name)
        lines = io.open(path, encoding="utf-8").read().splitlines()
        head = re.match(r"^%s: column from run (\S+?)T\S+, (.+)$" % name, lines[0])
        if not head:
            raise SystemExit("FAILED: %s.txt does not start with a run header" % name)
        taken.add(head.group(1))
        versions[label] = head.group(2)
        note = [l for l in lines[1:4] if l.startswith("BOUNDARY:")]
        boundaries[label] = note[0][len("BOUNDARY:"):].strip() if note else ""

        parse = ns["parse_%s" % fmt]
        in_header, seen = True, set()
        for line in lines:
            if in_header:
                if not line.strip():
                    in_header = False
                continue
            if not line.strip():
                continue
            case, _, rest = line.partition(" ")
            case, answer = case.strip(), rest.strip()
            if case not in expected and case not in disputed:
                continue
            seen.add(case)
            cell = cells.setdefault(case, {})
            tracked = tracking.setdefault(case, {})
            tracked[label] = None
            answers.setdefault(case, {})[label] = [answer, ""]
            if case in disputed:
                cell[label] = NOSPEC
            elif answer in ("", "—") or answer.startswith(("ERROR", "— ", "—\t")):
                cell[label] = UNSUPPORTED
                rule = refused["cells"].get(name, {}).get(case)
                if rule:
                    answers[case][label][1] = rule
                    tracked[label] = refused["rules"].get(rule, {}).get("triage", {}).get(name)
            else:
                got = parse(answer)
                if got is None:
                    # An answer the check cannot read is a defect in the check, and drawing it as
                    # anything at all would hide that. The README numbers refuse it too.
                    raise SystemExit("FAILED: %s: cannot parse the answer for %s" % (name, case))
                want = expected[case]["schema"]
                if fmt in types_only:
                    got = [[t, None] for t, _ in got]
                    want = [[t, None] for t, _ in want]
                if got == want:
                    cell[label] = MATCH
                else:
                    rule = differed["cells"].get(name, {}).get(case)
                    kind = differed["rules"].get(rule, {}).get("kind", "divergence")
                    cell[label] = KIND_STATE[kind] if rule else DIVERGENCE
                    answers[case][label][1] = rule or ""
                    tracked[label] = differed["rules"].get(rule, {}).get("triage", {}).get(name)
        missing = (set(expected) | set(disputed)) - seen
        if missing:
            raise SystemExit("FAILED: %s.txt has no answer for %d cases: %s"
                             % (name, len(missing), ", ".join(sorted(missing)[:4])))
    prefixes = {}
    for case in sorted(cells):
        prefixes.setdefault(case.split("_")[0], []).append(case)
    order = [p for p in GROUP_ORDER if p in prefixes] + sorted(set(prefixes) - set(GROUP_ORDER))
    groups = [{"label": GROUP_LABEL.get(p, p), "cases": prefixes[p]} for p in order]

    labels = [c[0] for c in COLUMNS]
    return {
        "participants": labels,
        "versions": versions,
        "boundaries": boundaries,
        "taken": ", ".join(sorted(taken)),
        "groups": [{"label": g["label"], "n": len(g["cases"])} for g in groups],
        "cases": [c for g in groups for c in g["cases"]],
        "cells": [[cells[c][p] for p in labels] for g in groups for c in g["cases"]],
        "answers": [[answers[c][p] for p in labels] for g in groups for c in g["cases"]],
        # Triage is recorded once per reason and participant in differed.json or refused.json. The
        # page gets a cell-shaped view so it cannot apply one participant's report to another.
        "tracking": [[tracking[c][p] for p in labels] for g in groups for c in g["cases"]],
        "expected": {c: fmt_schema(expected[c]["schema"]) for c in expected},
        "why": {c: expected[c].get("source", "") for c in expected},
        "disputed": dict(disputed),
        "rules": {k: {"kind": v["kind"], "what": v["what"]}
                  for doc in (differed, refused) for k, v in doc["rules"].items()},
    }


def short_version(text):
    """The tail of a column header: `substrait-validator 0.1.4 at 2a10470` -> `2a10470`.

    The picture has one line for nine of these, so the part that identifies the build is kept and
    the name dropped - the column above it already says whose it is. A pseudo-version keeps only its
    commit, which is the part a reader can look up."""
    tail = text.split()[-1]
    return tail.rsplit("-", 1)[-1] if len(tail) > 14 else tail


def fmt_schema(schema):
    return "[" + ", ".join("%s%s" % (t, "?" if n else "") for t, n in schema) + "]"


def tally(model):
    counts = {}
    for row in model["cells"]:
        for state in row:
            counts[state] = counts.get(state, 0) + 1
    return counts


def scored(model, participant):
    """matched / differed / unsupported over the cases that carry an expectation."""
    col = model["participants"].index(participant)
    m = d = u = 0
    for row in model["cells"]:
        state = row[col]
        m += state == MATCH
        d += state in (DIVERGENCE, BOUNDARY, UNRESOLVED)
        u += state == UNSUPPORTED
    return m, d, u


# --------------------------------------------------------------------------------------- SVG ----

THEMES = {
    "light": dict(surface="#fdfdfc", rule="#dcdcd6", rule2="#c2c2ba", ink="#14161a",
                  ink2="#55575c", ink3="#8a8b88", divergence="#d03b3b", unresolved="#4a3aa7",
                  hatch="#8a8b88", match="#d6d6d1"),
    "dark":  dict(surface="#171a1e", rule="#2b2f35", rule2="#3d434b", ink="#eef0ee",
                  ink2="#b3b6b3", ink3="#7e827f", divergence="#e05a58", unresolved="#9085e9",
                  hatch="#7e827f", match="#363a40"),
}
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "system-ui, -apple-system, Segoe UI, sans-serif"
NAME_W, COL_W, ROW_H, GROUP_H, PAD, HEAD_H = 252, 62, 13, 17, 14, 120
CELL_W, CELL_H = COL_W - 8, ROW_H - 3


def svg(model, theme):
    t = THEMES[theme]
    width = PAD * 2 + NAME_W + COL_W * len(model["participants"])
    footer_lines = 1 + max(1, (len(" · ".join(
        ["columns taken %s" % model["taken"]]
        + ["%s %s" % (SHORT[p], short_version(model["versions"][p]))
           for p in model["participants"]])) * 4.85) // (width - PAD * 2) + 1)
    height = HEAD_H + sum(GROUP_H + g["n"] * ROW_H for g in model["groups"]) + 24 + int(footer_lines) * 11
    out = []

    def text(x, y, s, fill, size=9.5, weight="normal", anchor="start", family=MONO, spacing=None):
        out.append('<text x="%.1f" y="%.1f" fill="%s" font-size="%.1f" font-weight="%s" '
                   'text-anchor="%s" font-family="%s"%s>%s</text>'
                   % (x, y, fill, size, weight, anchor, family,
                      ' letter-spacing="%s"' % spacing if spacing else "", html.escape(s)))

    def box(x, y, w, h, fill=None, stroke=None, sw=0.8):
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="%s"%s/>'
                   % (x, y, w, h, fill or "none",
                      ' stroke="%s" stroke-width="%s"' % (stroke, sw) if stroke else ""))

    out.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
               % (width, height, width, height))
    out.append('<defs>'
               '<pattern id="hatch" width="4" height="4" patternTransform="rotate(135)" '
               'patternUnits="userSpaceOnUse">'
               '<line x1="0" y1="0" x2="0" y2="4" stroke="%s" stroke-width="1.6"/></pattern>'
               '<pattern id="dots" width="4" height="4" patternTransform="rotate(45)" '
               'patternUnits="userSpaceOnUse">'
               '<line x1="0" y1="0" x2="0" y2="4" stroke="%s" stroke-width="0.8"/></pattern>'
               '</defs>' % (t["hatch"], t["rule2"]))
    box(0, 0, width, height, fill=t["surface"])

    counts = tally(model)
    text(PAD, 26, "Declared against derived", t["ink"], 15, "600", family=SANS)
    text(PAD, 43, "%d plans read by %d implementations, each answer compared with an expectation "
                  "written from the spec." % (len(model["cases"]), len(model["participants"])),
         t["ink2"], 10, family=SANS)
    text(PAD, 57, "An empty cell is silence — the implementation does not accept that plan "
                  "— and is never drawn as a colour.", t["ink2"], 10, family=SANS)

    x = PAD
    for state in (MATCH, DIVERGENCE, UNRESOLVED, BOUNDARY, UNSUPPORTED, NOSPEC):
        cell(out, box, x, 68, 11, 9, state, t)
        label = STATE_NAME[state]
        text(x + 15, 76, label, t["ink2"], 9.5, family=SANS)
        x += 15 + len(label) * 5.6 + 16

    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
               % (PAD, HEAD_H - 5, width - PAD, HEAD_H - 5, t["rule2"]))
    for c, p in enumerate(model["participants"]):
        text(PAD + NAME_W + c * COL_W + COL_W / 2, HEAD_H - 11, SHORT[p], t["ink2"], 9, "500",
             anchor="middle")

    y, at = HEAD_H, 0
    for g in model["groups"]:
        text(PAD, y + 11, g["label"].upper(), t["ink3"], 8, "600", family=SANS, spacing="0.06em")
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="0.6"/>'
                   % (PAD, y + GROUP_H - 3, width - PAD, y + GROUP_H - 3, t["rule"]))
        y += GROUP_H
        for _ in range(g["n"]):
            text(PAD, y + CELL_H - 0.5, model["cases"][at], t["ink2"], 8.2)
            for c in range(len(model["participants"])):
                cell(out, box, PAD + NAME_W + c * COL_W + (COL_W - CELL_W) / 2, y,
                     CELL_W, CELL_H, model["cells"][at][c], t)
            y += ROW_H
            at += 1

    text(PAD, y + 20,
         "%d cells: %d matched, %d divergences, %d unresolved, %d at a type-system boundary, "
         "%d not accepted, %d without an expectation."
         % (sum(counts.values()), counts.get(MATCH, 0), counts.get(DIVERGENCE, 0),
            counts.get(UNRESOLVED, 0), counts.get(BOUNDARY, 0), counts.get(UNSUPPORTED, 0),
            counts.get(NOSPEC, 0)),
         t["ink3"], 9, family=SANS)
    # What was measured, in the picture itself: a screenshot of it travels without the README, and a
    # matrix that does not say which builds it read is a claim nobody can check or repeat. The line
    # is wrapped rather than sized to fit, so a longer commit or one more participant moves the text
    # down instead of past the right edge.
    parts = ["columns taken %s" % model["taken"]] + [
        "%s %s" % (SHORT[p], short_version(model["versions"][p])) for p in model["participants"]]
    room = int((width - PAD * 2) / 4.85)   # characters per line at font-size 8 in the mono face
    lines, line = [], ""
    for part in parts:
        candidate = part if not line else line + " · " + part
        if len(candidate) > room and line:
            lines.append(line)
            line = part
        else:
            line = candidate
    lines.append(line)
    for n, one in enumerate(lines):
        text(PAD, y + 32 + n * 11, one, t["ink3"], 8)
    out.append('</svg>')
    return "\n".join(out) + "\n"


def cell(out, box, x, y, w, h, state, t):
    if state == MATCH:
        box(x, y, w, h, fill=t["match"])
    elif state == DIVERGENCE:
        box(x, y, w, h, fill=t["divergence"])
    elif state == UNRESOLVED:
        box(x, y, w, h, fill=t["unresolved"])
    elif state == BOUNDARY:
        box(x, y, w, h, fill="url(#hatch)")
        box(x, y, w, h, stroke=t["rule2"], sw=0.6)
    elif state == NOSPEC:
        box(x, y, w, h, fill="url(#dots)")
    else:
        box(x, y, w, h, stroke=t["rule"])


# -------------------------------------------------------------------------------------- page ----

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Declared against derived</title>
<meta name="description" content="%(cases)d Substrait plans read by %(participants)d implementations, each derived schema against an expectation written from the spec.">
<link rel="icon" href="%(favicon)s">
<style>
:root {
  color-scheme: light dark;
  --ground: #f4f4f1; --surface: #fdfdfc; --rule: #dcdcd6; --rule-strong: #c2c2ba;
  --ink: #14161a; --ink-2: #55575c; --ink-3: #8a8b88;
  --divergence: #d03b3b; --unresolved: #4a3aa7; --boundary: #8a8b88;
  --match: #d6d6d1; --selected: #f5f5f1; --detail: #fafaf7;
  --mono: %(mono)s; --sans: %(sans)s;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ground: #101215; --surface: #171a1e; --rule: #2b2f35; --rule-strong: #3d434b;
    --ink: #eef0ee; --ink-2: #b3b6b3; --ink-3: #7e827f;
    --divergence: #e05a58; --unresolved: #9085e9; --boundary: #7e827f; --match: #363a40;
    --selected: #20242a; --detail: #1c2025;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 0 24px; background: var(--ground); color: var(--ink);
       font: 15px/1.55 var(--sans); }
.page { max-width: 1140px; margin: 0 auto; }
header { padding: 44px 0 26px; border-bottom: 1px solid var(--rule); }
h1 { font-size: 30px; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 14px; }
.lede { margin: 0 0 12px; color: var(--ink-2); }
.lede strong { color: var(--ink); font-weight: 600; }
.meta { font: 12px/1.5 var(--mono); color: var(--ink-3); margin: 0; overflow-wrap: anywhere; }
.meta a, footer a { color: var(--ink-2); }
h2 { font: 500 11px/1.4 var(--mono); letter-spacing: 0.09em; text-transform: uppercase;
     color: var(--ink-3); margin: 30px 0 12px; }
.rollup { display: grid; grid-template-columns: 150px minmax(0, 1fr) max-content;
          align-items: center; gap: 7px 14px; }
.row { display: contents; }
.row .name { font-size: 13px; color: var(--ink-2); }
.bar { display: flex; height: 15px; gap: 2px; }
.bar span { display: block; border-radius: 1px; }
.bar .m { background: var(--match); }
.bar .d { background: var(--divergence); }
.bar .u { box-shadow: inset 0 0 0 1px var(--rule-strong); }
/* The relation corpus's fourth tone: agreement on the schema of a case that also asserts rows.
   Hatched rather than a shade of the match colour, because it is a limit of what was measured and
   not a weaker agreement - the same distinction the matrix above draws for a type-system boundary. */
.bar .s { background: var(--match);
          background-image: repeating-linear-gradient(135deg, var(--boundary) 0 1px, transparent 1px 4px); }
.rel-legend { margin: 14px 0 0; }
.rel-legend .sw i.m { background: var(--match); }
.rel-legend .sw i.s { background: var(--match);
                      background-image: repeating-linear-gradient(135deg, var(--boundary) 0 1px, transparent 1px 4px); }
.rel-legend .sw i.d { background: var(--divergence); }
.rel-legend .sw i.u { box-shadow: inset 0 0 0 1px var(--rule-strong); }
.rel-legend .sw i.o { background-image: repeating-linear-gradient(45deg, var(--rule-strong) 0 1px, transparent 1px 4px); }
.rel-note { margin: 12px 0 4px; }
/* The relation table's five states, in the order probe/relations/check_column.py numbers them.
   Its own prefix, because the matrix above has six states of its own under .st0 to .st5 and the
   two sets mean different things. */
.rst0 i { background: var(--match); }
.rst1 i { background: var(--match);
          background-image: repeating-linear-gradient(135deg, var(--boundary) 0 1px, transparent 1px 4px); }
.rst2 i { background: var(--divergence); }
.rst3 i { box-shadow: inset 0 0 0 1px var(--rule); }
.rst4 i { background: repeating-linear-gradient(45deg, var(--rule-strong) 0 1px, transparent 1px 4px); }
/* The bar that marks a case asserting rows, in the gutter of its name, the way the picture draws
   it. A space when the case asserts none, so the names still line up. */
#rel-matrix .rel-rowmark { display: inline-block; width: 8px; color: var(--ink-3); }
/* The relation table's own name column is wider than the matrix's: its case names carry a group
   prefix and a rule, where the other corpus names a case in one word. */
#rel-matrix tbody th.case { padding-right: 22px; }
/* No width in pixels: the relation picture sizes its name column from the longest case name, so a
   number written here would rot the next time the corpus grows. The SVG carries its own. */
.rel-grid { display: block; max-width: 100%%; height: auto; margin: 8px 0 6px; }
.row .num { font: 11.5px var(--mono); color: var(--ink-3); font-variant-numeric: tabular-nums;
            text-align: right; white-space: nowrap; }
.row .num b { color: var(--divergence); font-weight: 500; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 20px; align-items: center;
          font-size: 12.5px; color: var(--ink-2); }
.key { display: inline-flex; align-items: center; gap: 7px; }
.sw { width: 15px; height: 15px; flex: none; }
.sw i { display: block; height: 100%%; border-radius: 2px; }
.controls { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; margin: 16px 0 8px; }
button { font: 12.5px var(--sans); color: var(--ink-2); background: var(--surface);
         border: 1px solid var(--rule-strong); border-radius: 3px; padding: 5px 11px; cursor: pointer; }
button[aria-pressed="true"] { color: var(--surface); background: var(--ink); border-color: var(--ink); }
button:focus-visible, select:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.track-filter { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ink-2); }
select { font: 12.5px var(--sans); color: var(--ink); background: var(--surface);
         border: 1px solid var(--rule-strong); border-radius: 3px; padding: 5px 28px 5px 9px; }
.matrix-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 18px;
               margin: 0 0 10px; }
.tracking-summary { font-size: 12.5px; color: var(--ink-2); }
.tracking-summary::before { content: ""; display: inline-block; width: 5px; height: 5px;
                            margin: 0 7px 1px 1px; background: var(--ink); }
.hint { font-size: 12.5px; color: var(--ink-3); }
.matrix-pane { min-width: 0; }
.scroll { overflow-x: auto; padding-right: 12px; background: var(--surface);
          border: 1px solid var(--rule); border-radius: 3px; }
table { border-collapse: separate; border-spacing: 0; font-size: 12px;
        table-layout: auto; width: 100%%; min-width: 658px; }
thead th { position: sticky; top: 0; z-index: 2; background: var(--surface);
           border-bottom: 1px solid var(--rule-strong); font: 500 11px var(--mono);
           color: var(--ink-2); padding: 10px 6px; text-align: center; height: 42px;
           vertical-align: middle; }
thead th:not(.corner) { width: auto; min-width: 68px; }
thead th .column-name { display: inline-block; white-space: nowrap; }
thead th.corner { text-align: left; padding-left: 14px; width: 1%%; white-space: nowrap;
                  left: 0; z-index: 3; }
thead th.selected-column { color: var(--ink); background: var(--selected);
                           box-shadow: inset 0 -3px var(--ink); }
tbody th.case { position: sticky; left: 0; z-index: 1; background: var(--surface);
                font: 400 11px var(--mono); color: var(--ink-2); text-align: left;
                width: 1%%; padding: 3px 30px 3px 14px; line-height: 1.4; white-space: nowrap; }
tbody tr.group th { position: sticky; left: 0; background: var(--surface);
                    font: 600 11px var(--sans); letter-spacing: 0.05em; text-transform: uppercase;
                    color: var(--ink-3); padding: 16px 14px 5px; text-align: left; }
tbody tr.group td { border-bottom: 1px solid var(--rule); }
td.cell { padding: 0 1px; height: 22px; cursor: pointer; }
td.cell i { display: block; position: relative; height: 18px; border-radius: 2px; }
.svg-defs { position: absolute; width: 0; height: 0; overflow: hidden; }
td.cell .github-mark { position: absolute; top: 1px; right: 3px; width: 16px; height: 16px;
                       fill: var(--ink); }
.st0 i { background: var(--match); }
.st1 i { background: var(--divergence); }
.st2 i { background: repeating-linear-gradient(135deg, var(--boundary) 0 2px, transparent 2px 5px);
         box-shadow: inset 0 0 0 1px var(--rule-strong); }
.st3 i { background: var(--unresolved); }
.st4 i { box-shadow: inset 0 0 0 1px var(--rule); }
.st5 i { background: repeating-linear-gradient(45deg, var(--rule-strong) 0 1px, transparent 1px 4px); }
tbody tr:hover th.case { color: var(--ink); }
tbody tr.selected-row th.case { color: var(--ink); font-weight: 600; background: var(--selected);
                                box-shadow: inset 3px 0 var(--ink); }
td.cell:focus-visible { outline: none; }
td.cell:focus-visible i { outline: 2px solid var(--ink); outline-offset: 1px; }
@media (hover: hover) {
  td.cell:hover i { outline: 2px solid var(--ink); outline-offset: 1px; }
}
td.cell.on { position: relative; z-index: 2; }
td.cell.on i { outline: 2px solid var(--ink); outline-offset: 1px; }
td.cell.on::after { content: ""; position: absolute; left: 50%%; bottom: -15px; width: 2px;
                    height: 15px; background: var(--ink); transform: translateX(-1px); }
.detail-row td { padding: 14px 10px 15px; background: var(--surface); }
.detail { width: 82%%; min-width: 0; margin-inline: auto;
          background: var(--detail); border: 1px solid var(--rule-strong);
          border-top: 3px solid var(--ink); border-radius: 4px; padding: 18px 20px;
          box-shadow: 0 5px 18px #0000000a; }
.detail-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px;
                  border-bottom: 1px solid var(--rule); padding-bottom: 12px; margin-bottom: 14px; }
.detail h3 { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 9px;
             font: 600 17px/1.4 var(--sans); margin: 0; }
.detail h3 .case-name { font-family: var(--mono); overflow-wrap: anywhere; }
.detail h3 .pair-mark { color: var(--ink-3); font-weight: 400; }
.detail h3 .state { border-left: 1px solid var(--rule-strong); padding-left: 10px;
                    font: 500 13px var(--sans); }
.detail-close { flex: none; }
.detail-body { display: grid; grid-template-columns: minmax(250px, 0.9fr) minmax(320px, 1.1fr);
               gap: 18px 28px; align-items: start; }
.detail .status-note { font-size: 12.5px; color: var(--ink-3); margin: 0 0 14px; }
.detail dl { display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 7px 14px; margin: 0;
             font: 13px/1.5 var(--mono); }
.detail dt { color: var(--ink-3); }
.detail dd { margin: 0; color: var(--ink); overflow-wrap: anywhere; }
.detail .why { font: 14px/1.6 var(--sans); color: var(--ink-2); margin: 16px 0 0;
               border-top: 1px solid var(--rule); padding-top: 16px; overflow-wrap: anywhere; }
.detail-explanation > :first-child { margin-top: 0; padding-top: 0; border-top: 0; }
.tracking { border-top: 1px solid var(--rule); margin-top: 16px; padding-top: 14px; }
.tracking h4 { font: 600 13px/1.4 var(--sans); margin: 0; }
.tracking-links { display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 7px 0 0; padding: 0;
                  list-style: none; }
.tracking-links a { display: inline-flex; flex-wrap: wrap; gap: 4px; align-items: baseline;
                    font: 12px/1.5 var(--mono); overflow-wrap: anywhere; }
.tracking-link-kind { color: var(--ink); font: 600 12px/1.5 var(--sans); }
.tracking-link-out { text-decoration: none; }
.tracking-state, .tracking-empty { font: 12px/1.5 var(--sans); color: var(--ink-3); margin: 8px 0 0; }
.tracking-state span { color: var(--ink-2); font-weight: 600; }
.tracking-note { font: 13px/1.55 var(--sans); color: var(--ink-2); margin: 9px 0 0;
                 overflow-wrap: anywhere; }
.c-div { color: var(--divergence); }
.c-unr { color: var(--unresolved); }
.c-bnd { color: var(--ink-3); }
footer { border-top: 1px solid var(--rule); margin-top: 26px; padding: 18px 0 40px;
         font-size: 12.5px; color: var(--ink-3); }
footer dl { display: grid; grid-template-columns: 150px 1fr; gap: 2px 14px; font: 11.5px var(--mono); margin: 10px 0 16px; }
footer dt { color: var(--ink-3); }
footer dd { margin: 0; color: var(--ink-2); overflow-wrap: anywhere; }
@media (max-width: 840px) {
  .detail-body { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 620px) {
  body { padding: 0 16px; }
  header { padding-top: 28px; }
  .rollup { grid-template-columns: 112px minmax(0, 1fr); }
  .row .num { grid-column: 1 / -1; text-align: left; white-space: normal; margin-bottom: 7px; }
  table { min-width: 558px; }
  .detail-row td { padding-right: 6px; padding-left: 6px; }
  .detail { padding: 16px; }
  .detail dl { grid-template-columns: minmax(0, 1fr); gap: 5px; }
  .detail dd { margin-bottom: 12px; }
  footer dl { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<svg class="svg-defs" aria-hidden="true">
  <!-- https://github.com/primer/octicons/blob/main/icons/mark-github-16.svg -->
  <symbol id="github-mark" viewBox="0 0 16 16">
    <path d="M6.766 11.328c-2.063-.25-3.516-1.734-3.516-3.656 0-.781.281-1.625.75-2.188-.203-.515-.172-1.609.063-2.062.625-.078 1.468.25 1.968.703.594-.187 1.219-.281 1.985-.281.765 0 1.39.094 1.953.265.484-.437 1.344-.765 1.969-.687.218.422.25 1.515.046 2.047.5.593.766 1.39.766 2.203 0 1.922-1.453 3.375-3.547 3.64.531.344.89 1.094.89 1.954v1.625c0 .468.391.734.86.547C13.781 14.359 16 11.53 16 8.03 16 3.61 12.406 0 7.984 0 3.563 0 0 3.61 0 8.031a7.88 7.88 0 0 0 5.172 7.422c.422.156.828-.125.828-.547v-1.25c-.219.094-.5.156-.75.156-1.031 0-1.64-.562-2.078-1.609-.172-.422-.36-.672-.719-.719-.187-.015-.25-.093-.25-.187 0-.188.313-.328.625-.328.453 0 .844.281 1.25.86.313.452.64.655 1.031.655s.641-.14 1-.5c.266-.265.47-.5.657-.656"/>
  </symbol>
</svg>
<div class="page">
  <header>
    <h1>Declared against derived</h1>
    <p class="lede">A plan declares its types; a consumer derives them again &mdash; or copies what
      the plan declared. When the two disagree, nothing in the format notices. Each cell below is
      one of %(cases)d plans read by one of %(participants)d implementations, compared against an
      expectation written from the spec rather than from any implementation.</p>
    <p class="lede"><strong>An empty cell is silence, not a wrong answer.</strong> It means the
      implementation does not accept that plan at all &mdash; which is why silence is drawn as an
      outline and never as a colour.</p>
    <p class="lede">A second corpus is measured below the matrix: %(relcases)d relation cases
      written by hand against the sentences of the relation documentation, read by
      %(relparticipants)d implementations &mdash; <a href="#relations">what they answer</a>.</p>
    <p class="meta">%(cases)d cases &middot; %(scored)d with an expectation &middot; columns taken
      %(taken)s &middot; <a href="%(repo)s">substrait-conformance-cases</a></p>
  </header>

  <h2>By implementation, over the %(scored)d scored cases</h2>
  <div class="rollup" id="rollup"></div>

  <h2>Every case, every implementation</h2>
  <div class="legend" id="legend"></div>
  <div class="controls">
    <button id="f-all" aria-pressed="true">All %(cases)d cases</button>
    <button id="f-diff" aria-pressed="false">Only rows where someone differs</button>
    <label class="track-filter" for="f-track">Tracking
      <select id="f-track"><option value="">All statuses</option></select>
    </label>
    <label class="track-filter" for="f-who">Differs for
      <select id="f-who"><option value="">Anyone</option></select>
    </label>
  </div>
  <div class="matrix-meta">
    <span class="tracking-summary" id="tracking-summary"></span>
    <span class="hint">Click or tap a cell to open details below its row. The outlined cell is the
      source; a GitHub mark means an issue or PR is linked.</span>
  </div>

  <div class="matrix-pane">
    <div class="scroll" tabindex="0" role="region" aria-label="Conformance matrix">
      <table id="matrix"><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table>
    </div>
  </div>

  <section class="relations">%(relations)s</section>

  <footer>
    <p>What each column was taken against:</p>
    <dl>%(versions)s</dl>
    <p>%(boundaries)s</p>
    <p>A separate <a href="%(repo)s/blob/main/results/impala-types/README.md">Isthmus comparison using
      Impala's type factory</a> measures schema conversion through Isthmus. It does not run Impala's
      optimizer or executor.</p>
    <p>Gluten/Velox is a tenth column in the corpus and is not scored here: it runs in a cluster and
      four cases are not expressible in its proto. %(nospec)d cases carry no expectation &mdash; the
      spec does not say whether a virtual table's rows or its declared schema wins, and one case is
      invalid on purpose. The corpus, the probes and the expectations behind this page are in
      <a href="%(repo)s">substrait-conformance-cases</a>, and
      <a href="%(repo)s/blob/main/METHOD.md">METHOD.md</a> says where an expectation comes from and
      what a matching answer proves; this page is built by <code>probe/heatmap.py</code> from the
      saved columns.</p>
    <p>Tracking is the corpus's triage record, not a live GitHub status. Closing a linked issue does
      not change a cell; only a new saved run that returns the expected answer does.</p>
  </footer>
</div>

<script type="application/json" id="data">%(data)s</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById("data").textContent);
  var STATES = %(states)s;
  var TRACKING = {
    "reported": "Reported",
    "open": "Investigation open",
    "spec-question": "Spec question",
    "ours": "Corpus correction"
  };

  var rollup = document.getElementById("rollup");
  D.participants.forEach(function (p, c) {
    var s = D.scored[p], total = s[0] + s[1] + s[2];
    var row = document.createElement("div");
    row.className = "row";
    row.innerHTML = '<div class="name">' + p + '</div><div class="bar">' +
      seg("m", s[0]) + seg("d", s[1]) + seg("u", s[2]) + '</div>' +
      '<div class="num">' + s[0] + ' matched \\u00b7 ' + (s[1] ? '<b>' + s[1] + '</b>' : '0') +
      ' differ \\u00b7 ' + s[2] + ' silent</div>';
    rollup.appendChild(row);
  });
  function seg(cls, n) { return n ? '<span class="' + cls + '" style="flex:' + n + '"></span>' : ''; }

  var legend = document.getElementById("legend");
  [0, 1, 3, 2, 4, 5].forEach(function (i) {
    var el = document.createElement("span");
    el.className = "key";
    el.innerHTML = '<span class="sw st' + i + '"><i></i></span>' + STATES[i].name;
    legend.appendChild(el);
  });

  document.getElementById("head").innerHTML = '<th class="corner">case</th>' +
    D.participants.map(function (p) {
      return '<th title="' + p + '"><span class="column-name">' + D.short[p] + '</span></th>';
    }).join("");

  var body = document.getElementById("body"), at = 0;
  D.groups.forEach(function (g) {
    var gr = document.createElement("tr");
    gr.className = "group";
    gr.innerHTML = '<th>' + g.label + '</th><td colspan="' + D.participants.length + '"></td>';
    body.appendChild(gr);
    for (var k = 0; k < g.n; k++, at++) {
      var tr = document.createElement("tr");
      tr.dataset.r = at;
      var cells = '<th class="case">' + esc(D.cases[at]) + '</th>';
      for (var c = 0; c < D.participants.length; c++) {
        var st = D.cells[at][c], tracked = D.tracking[at][c];
        var ruleId = D.answers[at][c][1], reason = D.rules[ruleId];
        var stateName = reason && reason.kind === "crash" ? "crash" : STATES[st].name;
        var trackingMark = tracked && (tracked.at || []).length ?
          '<svg class="github-mark" aria-hidden="true" focusable="false"><use href="#github-mark"></use></svg>' : '';
        var trackingTitle = tracked ? ' \\u00b7 tracking: ' + TRACKING[tracked.outcome].toLowerCase() : '';
        cells += '<td class="cell st' + st + (tracked ? ' tracked' : '') + '" data-r="' + at +
                 '" data-c="' + c + '" tabindex="0" aria-controls="cell-detail" aria-expanded="false" title="' +
                 D.short[D.participants[c]] + ' \\u00b7 ' +
                 stateName + trackingTitle + '"><i>' + trackingMark + '</i></td>';
      }
      tr.innerHTML = cells;
      body.appendChild(tr);
    }
  });

  var current = null, activeCell = null, activeHeader = null;
  var detailRow = document.createElement("tr"), detailCell = document.createElement("td");
  detailRow.className = "detail-row";
  detailCell.colSpan = D.participants.length + 1;
  detailRow.appendChild(detailCell);
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function escAttr(s) { return esc(s).replace(/"/g, "&quot;"); }
  function githubRef(url) {
    var m = String(url).match(/^https:\\/\\/github\\.com\\/([^/]+\\/[^/]+)\\/(issues|pull)\\/(\\d+)$/);
    return m ? { label: m[1] + "#" + m[3], kind: m[2] === "pull" ? "GitHub PR" : "GitHub issue" } :
      { label: url, kind: "GitHub" };
  }
  function trackingHtml(tracked) {
    if (!tracked) { return ""; }
    var links = (tracked.at || []).map(function (url) {
      var ref = githubRef(url);
      return '<li><a href="' + escAttr(url) + '" target="_blank" rel="noopener noreferrer">' +
             '<span class="tracking-link-kind">' + ref.kind + '</span><span>' + esc(ref.label) +
             '</span><span class="tracking-link-out" aria-hidden="true">\\u2197</span></a></li>';
    }).join("");
    return '<section class="tracking" aria-label="Issue tracking"><h4>Tracking</h4>' +
      (links ? '<ul class="tracking-links">' + links + '</ul>' :
        '<p class="tracking-empty">No GitHub issue or PR yet.</p>') +
      '<p class="tracking-state"><span>Corpus status</span> \\u00b7 ' + esc(TRACKING[tracked.outcome]) + '</p>' +
      (tracked.note ? '<p class="tracking-note">' + esc(tracked.note) + '</p>' : '') + '</section>';
  }
  function closeDetails(restoreFocus) {
    if (!current) { return; }
    if (activeCell) {
      activeCell.classList.remove("on");
      activeCell.setAttribute("aria-expanded", "false");
      if (activeCell.parentElement) { activeCell.parentElement.classList.remove("selected-row"); }
    }
    if (activeHeader) { activeHeader.classList.remove("selected-column"); }
    if (detailRow.parentNode) { detailRow.parentNode.removeChild(detailRow); }
    var previous = activeCell;
    current = null;
    activeCell = null;
    activeHeader = null;
    if (restoreFocus && previous) { previous.focus(); }
  }
  function show(r, c) {
    closeDetails(false);
    current = [r, c];
    var name = D.cases[r], p = D.participants[c], st = D.cells[r][c], S = STATES[st];
    var answer = D.answers[r][c], got = answer[0], rule = answer[1], tracked = D.tracking[r][c];
    var want = D.expected[name];
    var reason = rule && D.rules[rule];
    if (reason && reason.kind === "crash") {
      S = { name: "crash", note: "the participant process died instead of returning an answer",
            tone: "c-div" };
    }
    var why = reason ? reason.what : (D.disputed[name] || D.why[name] || "");
    var td = document.querySelector('td.cell[data-r="' + r + '"][data-c="' + c + '"]');
    if (!td) { current = null; return; }
    activeCell = td;
    activeHeader = document.querySelectorAll("#head th")[c + 1];
    td.classList.add("on");
    td.setAttribute("aria-expanded", "true");
    td.parentElement.classList.add("selected-row");
    if (activeHeader) { activeHeader.classList.add("selected-column"); }
    detailCell.innerHTML = '<section class="detail" id="cell-detail" aria-labelledby="detail-title">' +
      '<div class="detail-toolbar"><h3 id="detail-title"><span class="case-name">' +
      esc(name).replace(/_/g, "_<wbr>") + '</span><span class="pair-mark">\\u00d7</span><span>' +
      esc(p) + '</span><span class="state ' + S.tone + '">' + esc(S.name) + '</span></h3>' +
      '<button class="detail-close" type="button" aria-label="Close cell details">Close</button></div>' +
      '<div class="detail-body"><div class="detail-values"><p class="status-note">' + esc(S.note) + '</p>' +
      '<dl><dt>Expected</dt><dd>' + (want ? esc(want) : "\\u2014 the spec does not settle this case") + '</dd>' +
      '<dt>Returned</dt><dd>' + (got ? esc(got) : "\\u2014") + '</dd></dl></div>' +
      '<div class="detail-explanation">' + trackingHtml(tracked) +
      (why ? '<p class="why">' + esc(why) + '</p>' : "") + '</div></div></section>';
    td.parentElement.insertAdjacentElement("afterend", detailRow);
    window.requestAnimationFrame(function () { detailRow.scrollIntoView({ block: "nearest" }); });
  }
  var matrix = document.getElementById("matrix");
  function toggleDetails(td) {
    var r = +td.dataset.r, c = +td.dataset.c;
    if (current && current[0] === r && current[1] === c) { closeDetails(false); }
    else { show(r, c); }
  }
  matrix.addEventListener("click", function (e) {
    var td = e.target.closest && e.target.closest("td.cell");
    if (td) { toggleDetails(td); }
  });
  matrix.addEventListener("keydown", function (e) {
    var td = e.target.closest && e.target.closest("td.cell");
    if (!td || (e.key !== "Enter" && e.key !== " ")) { return; }
    e.preventDefault();
    toggleDetails(td);
  });
  detailRow.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest(".detail-close")) { closeDetails(true); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && current) { closeDetails(true); }
  });

  var all = document.getElementById("f-all"), diff = document.getElementById("f-diff");
  var trackFilter = document.getElementById("f-track"), onlyDiff = false;
  // A maintainer arriving from their own issue wants one column's differences and nothing else,
  // which is the row set results/DIFFS.md lists for them. It composes with the other two filters
  // rather than replacing them.
  var whoFilter = document.getElementById("f-who");
  function differs(state) { return state > 0 && state < 4; }
  D.participants.forEach(function (p, i) {
    var option = document.createElement("option");
    option.value = i;
    option.textContent = p;
    whoFilter.appendChild(option);
  });
  var trackingCounts = {}, trackingKinds = {}, linked = {};
  D.tracking.forEach(function (row, r) {
    row.forEach(function (tracked, c) {
      if (!tracked) { return; }
      trackingCounts[tracked.outcome] = (trackingCounts[tracked.outcome] || 0) + 1;
      var rule = D.answers[r][c][1], kind = D.rules[rule] ? D.rules[rule].kind : "divergence";
      trackingKinds[kind] = (trackingKinds[kind] || 0) + 1;
      (tracked.at || []).forEach(function (url) { linked[url] = true; });
    });
  });
  ["reported", "open", "spec-question", "ours"].forEach(function (outcome) {
    if (!trackingCounts[outcome]) { return; }
    var option = document.createElement("option");
    option.value = outcome;
    option.textContent = TRACKING[outcome] + " (" + trackingCounts[outcome] + ")";
    trackFilter.appendChild(option);
  });
  document.getElementById("tracking-summary").textContent = "Triaged: " +
    (trackingKinds.divergence || 0) + " divergences and " + (trackingKinds.crash || 0) +
    " crashes \\u00b7 " + Object.keys(linked).length +
    " linked issues or PRs \\u00b7 " + (trackingCounts.open || 0) + " still under investigation";
  function apply(diffOnly) {
    closeDetails(false);
    onlyDiff = Boolean(diffOnly);
    all.setAttribute("aria-pressed", String(!onlyDiff));
    diff.setAttribute("aria-pressed", String(onlyDiff));
    var group = null, shown = 0;
    Array.prototype.forEach.call(body.children, function (tr) {
      if (tr.classList.contains("group")) {
        if (group) { group.hidden = shown === 0; }
        group = tr; shown = 0; tr.hidden = false;
        return;
      }
      var r = +tr.dataset.r;
      var keep = (!onlyDiff || D.cells[r].some(differs)) &&
        (!trackFilter.value || D.tracking[r].some(function (tracked) {
          return tracked && tracked.outcome === trackFilter.value;
        })) &&
        (whoFilter.value === "" || differs(D.cells[r][+whoFilter.value]));
      tr.hidden = !keep;
      if (keep) { shown++; }
    });
    if (group) { group.hidden = shown === 0; }
  }
  all.addEventListener("click", function () { apply(false); });
  diff.addEventListener("click", function () { apply(true); });
  trackFilter.addEventListener("change", function () { apply(onlyDiff); });
  whoFilter.addEventListener("change", function () { apply(onlyDiff); });
})();
</script>
</body>
</html>
"""

REPO = "https://github.com/alexandrefimov/substrait-conformance-cases"

# The tab icon: four cells in the states the matrix is mostly made of, drawn in the light palette so
# it reads on either browser chrome. Inline rather than a file, so docs/ stays what heatmap.py
# writes and nothing else.
FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
    "%3Crect width='16' height='16' rx='3' fill='%23fdfdfc'/%3E"
    "%3Crect x='2.5' y='3' width='5' height='4' rx='1' fill='%23d6d6d1'/%3E"
    "%3Crect x='8.5' y='3' width='5' height='4' rx='1' fill='%23d03b3b'/%3E"
    "%3Crect x='2.5' y='9' width='5' height='4' rx='1' fill='%23d6d6d1'/%3E"
    "%3Crect x='8.5' y='9' width='5' height='4' rx='1' fill='none' stroke='%23c2c2ba'/%3E"
    "%3C/svg%3E")


def page(model):
    counts = tally(model)
    data = {
        "participants": model["participants"],
        "short": {p: SHORT[p] for p in model["participants"]},
        "cases": model["cases"],
        "groups": model["groups"],
        "cells": model["cells"],
        "answers": model["answers"],
        "tracking": model["tracking"],
        "expected": model["expected"],
        "why": model["why"],
        "disputed": model["disputed"],
        "rules": model["rules"],
        "scored": {p: list(scored(model, p)) for p in model["participants"]},
    }
    states = [{"name": STATE_NAME[s], "note": STATE_NOTE[s],
               "tone": {DIVERGENCE: "c-div", UNRESOLVED: "c-unr"}.get(s, "c-bnd")}
              for s in range(6)]
    boundaries = " ".join("%s: %s" % (p, model["boundaries"][p])
                          for p in model["participants"] if model["boundaries"][p])
    # "substrait-java: substrait-java fff63906" reads as a stutter, so a leading word that only
    # repeats the participant's own name is dropped. It is kept where it says something the name
    # does not - pyarrow for Acero, substrait-java for Isthmus, the module path for substrait-go.
    def build(participant):
        text = model["versions"][participant]
        first, _, rest = text.partition(" ")
        return rest if rest and first.lower() == participant.lower() else text

    versions = "".join("<dt>%s</dt><dd>%s</dd>" % (html.escape(p), html.escape(build(p)))
                       for p in model["participants"])
    # The relation corpus is a second measurement on a second set of cases, and its verdicts are
    # formed by probe/relations/check_column.py rather than here. Imported inside the function
    # because that module imports this one for the palette, and at module level the two would each
    # be waiting for the other.
    sys.path.insert(0, os.path.join(ROOT, "probe", "relations"))
    import picture

    rel = picture.page_model()
    return PAGE % {
        "relations": picture.section(REPO),
        "relcases": len(rel["cases"]),
        "relparticipants": len(rel["participants"]),
        "mono": MONO, "sans": SANS, "favicon": FAVICON,
        "cases": len(model["cases"]),
        "scored": len([c for c in model["cases"] if c in model["expected"]]),
        "nospec": len([c for c in model["cases"] if c not in model["expected"]]),
        "participants": len(model["participants"]),
        "taken": model["taken"],
        "repo": REPO,
        "versions": versions,
        "boundaries": html.escape(boundaries),
        "data": script_data.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "states": script_data.dumps(states, ensure_ascii=False),
    }


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    model = build()
    if what == "svg-light":
        sys.stdout.write(svg(model, "light"))
    elif what == "svg-dark":
        sys.stdout.write(svg(model, "dark"))
    elif what == "page":
        sys.stdout.write(page(model))
    else:
        raise SystemExit(__doc__)
