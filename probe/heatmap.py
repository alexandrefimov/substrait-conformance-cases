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
  - Matched is the quiet fill and divergence the only loud one, so the eye lands on the 84 cells
    where a participant could have given the expected answer and gave another.
"""
import html, io, json, os, re, sys

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
               "stringlen": "String types carrying a length", "ctas": "CTAS"}

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
    exec(compile(src[:src.index("path, fmt = sys.argv[1]")], "check_expected.py", "exec"), ns)
    return ns


def build():
    ns = check_expected()
    expected, disputed = ns["EXPECTED"], ns["DISPUTED"]
    differed = json.load(io.open(os.path.join(ROOT, "differed.json"), encoding="utf-8"))
    # DuckDB is the one participant compared without nullability; check_expected.py says why.
    types_only = {"duckdb"}

    taken, versions, boundaries, cells, answers = set(), {}, {}, {}, {}
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
            answers.setdefault(case, {})[label] = [answer, ""]
            if case in disputed:
                cell[label] = NOSPEC
            elif answer in ("", "—") or answer.startswith(("ERROR", "— ", "—\t")):
                cell[label] = UNSUPPORTED
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
        missing = (set(expected) | set(disputed)) - seen
        if missing:
            raise SystemExit("FAILED: %s.txt has no answer for %d cases: %s"
                             % (name, len(missing), ", ".join(sorted(missing)[:4])))
    if len(taken) != 1:
        raise SystemExit("FAILED: the columns were taken on different days: %s"
                         % ", ".join(sorted(taken)))

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
        "taken": taken.pop(),
        "groups": [{"label": g["label"], "n": len(g["cases"])} for g in groups],
        "cases": [c for g in groups for c in g["cases"]],
        "cells": [[cells[c][p] for p in labels] for g in groups for c in g["cases"]],
        "answers": [[answers[c][p] for p in labels] for g in groups for c in g["cases"]],
        "expected": {c: fmt_schema(expected[c]["schema"]) for c in expected},
        "why": {c: expected[c].get("source", "") for c in expected},
        "disputed": dict(disputed),
        "rules": {k: {"kind": v["kind"], "what": v["what"]} for k, v in differed["rules"].items()},
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
  --match: #d6d6d1; --mono: %(mono)s; --sans: %(sans)s;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ground: #101215; --surface: #171a1e; --rule: #2b2f35; --rule-strong: #3d434b;
    --ink: #eef0ee; --ink-2: #b3b6b3; --ink-3: #7e827f;
    --divergence: #e05a58; --unresolved: #9085e9; --boundary: #7e827f; --match: #363a40;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 0 20px; background: var(--ground); color: var(--ink);
       font: 15px/1.55 var(--sans); }
.page { max-width: 1080px; margin: 0 auto; }
header { padding: 44px 0 26px; border-bottom: 1px solid var(--rule); }
h1 { font-size: 30px; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 14px; }
.lede { max-width: 63ch; margin: 0 0 12px; color: var(--ink-2); }
.lede strong { color: var(--ink); font-weight: 600; }
.meta { font: 12px/1.5 var(--mono); color: var(--ink-3); margin: 0; }
.meta a, footer a { color: var(--ink-2); }
h2 { font: 500 11px/1.4 var(--mono); letter-spacing: 0.09em; text-transform: uppercase;
     color: var(--ink-3); margin: 30px 0 12px; }
.rollup { display: grid; gap: 5px; }
.row { display: grid; grid-template-columns: 150px 1fr 208px; align-items: center; gap: 14px; }
.row .name { font-size: 13px; color: var(--ink-2); }
.bar { display: flex; height: 15px; gap: 2px; }
.bar span { display: block; border-radius: 1px; }
.bar .m { background: var(--match); }
.bar .d { background: var(--divergence); }
.bar .u { box-shadow: inset 0 0 0 1px var(--rule-strong); }
.row .num { font: 11.5px var(--mono); color: var(--ink-3); font-variant-numeric: tabular-nums;
            text-align: right; white-space: nowrap; }
.row .num b { color: var(--divergence); font-weight: 500; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 20px; align-items: center;
          font-size: 12.5px; color: var(--ink-2); }
.key { display: inline-flex; align-items: center; gap: 7px; }
.sw { width: 15px; height: 15px; flex: none; }
.sw i { display: block; height: 100%%; border-radius: 2px; }
.controls { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; margin: 16px 0 10px; }
button { font: 12.5px var(--sans); color: var(--ink-2); background: var(--surface);
         border: 1px solid var(--rule-strong); border-radius: 3px; padding: 5px 11px; cursor: pointer; }
button[aria-pressed="true"] { color: var(--surface); background: var(--ink); border-color: var(--ink); }
button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.hint { font-size: 12.5px; color: var(--ink-3); }
.scroll { overflow-x: auto; background: var(--surface); border: 1px solid var(--rule); border-radius: 3px; }
table { border-collapse: separate; border-spacing: 0; font-size: 12px; }
thead th { position: sticky; top: 0; z-index: 2; background: var(--surface);
           border-bottom: 1px solid var(--rule-strong); font: 500 11px var(--mono);
           color: var(--ink-2); padding: 9px 4px; text-align: center; width: 78px; min-width: 78px; }
thead th.corner { text-align: left; padding-left: 14px; width: 258px; min-width: 258px; left: 0; z-index: 3; }
tbody th.case { position: sticky; left: 0; z-index: 1; background: var(--surface);
                font: 400 11px var(--mono); color: var(--ink-2); text-align: left;
                padding: 0 10px 0 14px; white-space: nowrap; }
tbody tr.group th { position: sticky; left: 0; background: var(--surface);
                    font: 600 11px var(--sans); letter-spacing: 0.05em; text-transform: uppercase;
                    color: var(--ink-3); padding: 16px 14px 5px; text-align: left; white-space: nowrap; }
tbody tr.group td { border-bottom: 1px solid var(--rule); }
td.cell { padding: 0 1px; height: 19px; }
td.cell i { display: block; height: 15px; border-radius: 2px; }
.st0 i { background: var(--match); }
.st1 i { background: var(--divergence); }
.st2 i { background: repeating-linear-gradient(135deg, var(--boundary) 0 2px, transparent 2px 5px);
         box-shadow: inset 0 0 0 1px var(--rule-strong); }
.st3 i { background: var(--unresolved); }
.st4 i { box-shadow: inset 0 0 0 1px var(--rule); }
.st5 i { background: repeating-linear-gradient(45deg, var(--rule-strong) 0 1px, transparent 1px 4px); }
tbody tr:hover th.case { color: var(--ink); }
td.cell.on i { outline: 2px solid var(--ink); outline-offset: 1px; }
.detail { position: sticky; bottom: 0; margin-top: 10px; z-index: 4; background: var(--surface);
          border: 1px solid var(--rule); border-radius: 3px; padding: 12px 14px; }
.detail .head { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; font: 12px var(--mono); }
.detail .head .who { color: var(--ink); font-weight: 500; }
.detail .head .state { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }
.detail dl { display: grid; grid-template-columns: 76px 1fr; gap: 3px 12px; margin: 9px 0 0; font: 12px var(--mono); }
.detail dt { color: var(--ink-3); }
.detail dd { margin: 0; color: var(--ink); overflow-wrap: anywhere; }
.detail .why { font: 12.5px var(--sans); color: var(--ink-2); margin: 9px 0 0; max-width: 78ch; }
.c-div { color: var(--divergence); }
.c-unr { color: var(--unresolved); }
.c-bnd { color: var(--ink-3); }
footer { border-top: 1px solid var(--rule); margin-top: 26px; padding: 18px 0 40px;
         font-size: 12.5px; color: var(--ink-3); }
footer dl { display: grid; grid-template-columns: 150px 1fr; gap: 2px 14px; font: 11.5px var(--mono); margin: 10px 0 16px; }
footer dt { color: var(--ink-3); }
footer dd { margin: 0; color: var(--ink-2); overflow-wrap: anywhere; }
footer p { max-width: 72ch; }
@media (max-width: 620px) {
  .row { grid-template-columns: 112px 1fr; }
  .row .num { grid-column: 2; text-align: left; }
  footer dl { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
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
    <span class="hint">Hover or tap a cell for the two answers.</span>
  </div>

  <div class="scroll">
    <table id="matrix"><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table>
  </div>

  <div class="detail" id="detail"></div>

  <footer>
    <p>What each column was taken against:</p>
    <dl>%(versions)s</dl>
    <p>%(boundaries)s</p>
    <p>Gluten/Velox is a tenth column in the corpus and is not scored here: it runs in a cluster and
      four cases are not expressible in its proto. %(nospec)d cases carry no expectation &mdash; the
      spec does not say whether a virtual table's rows or its declared schema wins, and one case is
      invalid on purpose. The corpus, the probes and the expectations behind this page are in
      <a href="%(repo)s">substrait-conformance-cases</a>, and
      <a href="%(repo)s/blob/main/METHOD.md">METHOD.md</a> says where an expectation comes from and
      what a matching answer proves; this page is built by <code>probe/heatmap.py</code> from the
      saved columns.</p>
  </footer>
</div>

<script type="application/json" id="data">%(data)s</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById("data").textContent);
  var STATES = %(states)s;

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
    D.participants.map(function (p) { return '<th title="' + p + '">' + D.short[p] + '</th>'; }).join("");

  var body = document.getElementById("body"), at = 0;
  D.groups.forEach(function (g) {
    var gr = document.createElement("tr");
    gr.className = "group";
    gr.innerHTML = '<th>' + g.label + '</th><td colspan="' + D.participants.length + '"></td>';
    body.appendChild(gr);
    for (var k = 0; k < g.n; k++, at++) {
      var tr = document.createElement("tr");
      tr.dataset.r = at;
      var cells = '<th class="case">' + D.cases[at] + '</th>';
      for (var c = 0; c < D.participants.length; c++) {
        var st = D.cells[at][c];
        cells += '<td class="cell st' + st + '" data-r="' + at + '" data-c="' + c + '" title="' +
                 D.short[D.participants[c]] + ' \\u00b7 ' + STATES[st].name + '"><i></i></td>';
      }
      tr.innerHTML = cells;
      body.appendChild(tr);
    }
  });

  var detail = document.getElementById("detail"), pinned = null, current = null;
  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function show(r, c) {
    if (current && current[0] === r && current[1] === c) { return; }
    current = [r, c];
    var name = D.cases[r], p = D.participants[c], st = D.cells[r][c], S = STATES[st];
    var answer = D.answers[r][c], got = answer[0], rule = answer[1];
    var want = D.expected[name];
    var why = rule && D.rules[rule] ? D.rules[rule].what : (D.disputed[name] || D.why[name] || "");
    detail.innerHTML =
      '<div class="head"><span class="who">' + p + '</span>' +
      '<span class="state ' + S.tone + '">' + S.name + '</span>' +
      '<span class="state c-bnd">' + S.note + '</span></div>' +
      '<dl><dt>case</dt><dd>' + name + '</dd>' +
      '<dt>expected</dt><dd>' + (want ? esc(want) : "\\u2014 the spec does not settle this case") + '</dd>' +
      '<dt>' + D.short[p] + '</dt><dd>' + (got ? esc(got) : "\\u2014") + '</dd></dl>' +
      (why ? '<p class="why">' + esc(why) + '</p>' : "");
    var prev = document.querySelector("td.cell.on");
    if (prev) { prev.classList.remove("on"); }
    var td = document.querySelector('td.cell[data-r="' + r + '"][data-c="' + c + '"]');
    if (td) { td.classList.add("on"); }
  }
  var matrix = document.getElementById("matrix");
  matrix.addEventListener("mouseover", function (e) {
    var td = e.target.closest && e.target.closest("td.cell");
    if (td && !pinned) { show(+td.dataset.r, +td.dataset.c); }
  });
  matrix.addEventListener("click", function (e) {
    var td = e.target.closest && e.target.closest("td.cell");
    if (!td) { return; }
    var same = pinned && pinned[0] === +td.dataset.r && pinned[1] === +td.dataset.c;
    pinned = same ? null : [+td.dataset.r, +td.dataset.c];
    if (pinned) { show(pinned[0], pinned[1]); }
  });

  var all = document.getElementById("f-all"), diff = document.getElementById("f-diff");
  function apply(onlyDiff) {
    all.setAttribute("aria-pressed", String(!onlyDiff));
    diff.setAttribute("aria-pressed", String(onlyDiff));
    var group = null, shown = 0;
    Array.prototype.forEach.call(body.children, function (tr) {
      if (tr.classList.contains("group")) {
        if (group) { group.hidden = shown === 0; }
        group = tr; shown = 0; tr.hidden = false;
        return;
      }
      var keep = !onlyDiff || D.cells[+tr.dataset.r].some(function (s) { return s > 0 && s < 4; });
      tr.hidden = !keep;
      if (keep) { shown++; }
    });
    if (group) { group.hidden = shown === 0; }
  }
  all.addEventListener("click", function () { apply(false); });
  diff.addEventListener("click", function () { apply(true); });

  var start = D.cases.indexOf("decimal_divide");
  show(start < 0 ? 0 : start, D.participants.indexOf("DuckDB"));
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
    return PAGE % {
        "mono": MONO, "sans": SANS, "favicon": FAVICON,
        "cases": len(model["cases"]),
        "scored": len([c for c in model["cases"] if c in model["expected"]]),
        "nospec": len([c for c in model["cases"] if c not in model["expected"]]),
        "participants": len(model["participants"]),
        "taken": model["taken"],
        "repo": REPO,
        "versions": versions,
        "boundaries": html.escape(boundaries),
        "data": json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "states": json.dumps(states, ensure_ascii=False),
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
