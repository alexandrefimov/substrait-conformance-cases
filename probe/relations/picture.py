"""Draws the relation corpus as a grid: cases down, participants across.

    python3 probe/relations/picture.py svg-light > docs/relations.svg
    python3 probe/relations/picture.py svg-dark  > docs/relations-dark.svg

No cell is decided here. The verdicts come from probe/relations/check_column.py, the one procedure
that reads a saved column, so a picture disagreeing with the numbers beside it would have to
disagree with the check that produces them. probe/selfcheck.sh diffs the drawn files against the
committed ones and counts the shapes against the same model.

The palette is probe/heatmap.py's, imported rather than copied: the two corpora are measured apart
and drawn alike, and a reader who has learnt one picture should not have to learn a second grammar.
Three of that grammar's decisions carry over unchanged.

  - Silence is never a colour. A participant that refuses a plan gets an empty outline, because
    "does not accept this plan" is a fact about support and a good-to-bad ramp would read as a
    wrong answer. DuckDB refuses or crashes on a large share of the scored cases.
  - A limit is drawn apart from a divergence, and here the limit is the corpus's own second half.
    Most cases assert rows as well as a schema; a participant that derives schemas without
    executing is hatched on those, because it agreed with half of what the case says and never saw
    the rest. Without that, substrait-java's agreements would all read as whole when most of them
    are half of one.
  - A case that carries no expectation is dotted, not filled. Some ship without one on purpose,
    and a colour on that row would be an answer to a question the corpus does not ask.
"""

import html
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "probe"))

import check_column as cc  # noqa: E402
import script_data         # noqa: E402
# The palette and the fonts, nothing else. This file is picture.py rather than heatmap.py for that
# import: with both directories on the path, a second module of that name resolves to whichever
# came first, and the drawing would have imported itself.
import heatmap as base     # noqa: E402

# The order the page lists them in: most of the corpus answered first. Fixed here rather than
# sorted by result, so that a column moving does not silently reorder the picture.
COLUMNS = [("substrait-java", "JAVA"), ("DataFusion", "DATAFUSION"), ("substrait-go", "GO"),
           ("DuckDB", "DUCKDB")]

GROUP_LABEL = {
    "read": "Read: schema, projection and masks", "names": "Names, depth first through a struct",
    "project": "Project: appended columns, decimals", "temporal": "Dates and timestamps",
    "aggregate": "Aggregate: grouping sets", "join": "Joins, logical",
    "join_physical": "Joins, physical: numbers that mean two things",
    "cross": "Cross product", "set": "Set operations", "emit": "Emit mapping",
    "sort": "Sort", "fetch": "Fetch", "window": "Window", "expand": "Expand",
    "exchange": "Exchange", "reference": "Reference to a shared subtree", "write": "Write",
    "invalid": "Invalid on purpose", "unresolved": "Unsettled by the specification",
}
# A group with no entry above still gets its own heading under its own name, so a case added later
# is visible in the picture without editing this list.
GROUP_ORDER = ["read", "names", "project", "temporal", "aggregate", "join", "join_physical",
               "cross", "set", "emit", "sort", "fetch", "window", "expand", "exchange",
               "reference", "write", "invalid", "unresolved"]

STATE_NOTE = {
    cc.MATCHED: "the answer is the one the case asserts, rows included where it asserts rows",
    cc.SCHEMA_ONLY: "the schema agrees and the rows this case asserts were never observed",
    cc.DIFFERED: "a different answer, and this participant could have given the expected one",
    cc.UNSUPPORTED: "the participant does not accept this plan",
    cc.OBSERVED: "the case carries no expectation and is never scored",
}

# GUTTER is the strip left of the names where a case that asserts rows is marked. It is a column of
# its own rather than a mark beside the first cell, which is what it looked like when it sat there.
COL_W, ROW_H, GROUP_H, PAD, HEAD_H, GUTTER = 66, 13, 18, 14, 118, 9
CELL_W, CELL_H = COL_W - 8, ROW_H - 3
# The width of the name column is measured from the names rather than picked, because a case added
# later is not going to be shorter on request: at a fixed width the longest name ran under the
# first cell, and nothing failed - a drawing has no way to notice that it overflowed.
NAME_CHAR_W, NAME_MIN = 5.15, 240


def name_width(groups):
    longest = max((len(short_name(c)) for g in groups for c in g["cases"]), default=0)
    return max(NAME_MIN, int(longest * NAME_CHAR_W) + 12)


def build():
    """One model for both themes: the cases in drawing order and every participant's verdict."""
    models, versions = {}, {}
    for label, name in COLUMNS:
        path = os.path.join(ROOT, "results", "relations", "%s.txt" % name)
        model = cc.score(path)
        models[label] = model
        # The build, without the module paths - the same for every entry and carrying no version -
        # and without the participant's own name, which the line already begins with.
        parts = []
        for part in model["head"].splitlines()[0].split(", ", 1)[1].split(", "):
            part = part.replace("github.com/substrait-io/", "")
            first = part.split(" ", 1)[0]
            if first.lower() == label.lower() and " " in part:
                part = part.split(" ", 1)[1]
            parts.append(part)
        versions[label] = ", ".join(parts)

    cases = models[COLUMNS[0][0]]["cases"]
    declares_rows = {c["id"]: c["rows"] is not None for c in cases}
    groups, seen = [], {}
    for case in cases:
        seen.setdefault(case["id"].split("/", 1)[0], []).append(case["id"])
    for key in GROUP_ORDER + [k for k in seen if k not in GROUP_ORDER]:
        if key in seen:
            groups.append({"key": key, "label": GROUP_LABEL.get(key, key), "cases": seen[key]})

    cells = {label: models[label]["state"] for label, _ in COLUMNS}
    return {"groups": groups, "cells": cells, "models": models, "versions": versions,
            "declares_rows": declares_rows, "cases": cases,
            "taken": models[COLUMNS[0][0]]["head"].split("from run ", 1)[1][:10]}


def wrap(text, width, first_indent, indent, char_w):
    """Break a version line at its commas so it stays inside the drawing.

    substrait-go's build is three module versions and runs past any width this grid has; cut at a
    character count instead and the commit hash, which is the part a reader looks up, is what gets
    cut in half.
    """
    lines, line, budget = [], "", width - first_indent
    for part in text.split(", "):
        candidate = part if not line else line + ", " + part
        if line and len(candidate) * char_w > budget:
            lines.append(line + ",")
            line, budget = part, width - indent
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def short_name(case_id):
    """The part of the id below its group, which is what the row is about."""
    return case_id.split("/", 1)[1] if "/" in case_id else case_id


def tally(model, label):
    counts = {}
    for state in model["cells"][label].values():
        counts[state] = counts.get(state, 0) + 1
    return counts


def svg(model, theme):
    t = base.THEMES[theme]
    NAME_W = name_width(model["groups"])
    width = PAD * 2 + GUTTER + NAME_W + COL_W * len(COLUMNS)
    rows = sum(len(g["cases"]) for g in model["groups"])
    # The footer is built before the height so a wrapped version line cannot fall off the bottom.
    footer = []
    for label, _ in COLUMNS:
        for i, line in enumerate(wrap(model["versions"][label], width - PAD * 2, 16 * 4.5, 4.5, 4.5)):
            footer.append(("%-15s %s" % (label, line)) if i == 0 else ("%15s %s" % ("", line)))
    footer.append("columns taken %s; probe/relations/replay.sh reproduces one" % model["taken"])
    height = HEAD_H + len(model["groups"]) * GROUP_H + rows * ROW_H + 44 + 11 * len(footer)
    out = []

    def text(x, y, s, fill, size=9.5, weight="normal", anchor="start", family=base.MONO):
        # xml:space when the string is indented: SVG drops leading spaces otherwise, and the
        # continuation of a wrapped version line then started at the margin and read as a fourth
        # participant rather than as more of the third.
        out.append('<text x="%.1f" y="%.1f" fill="%s" font-size="%.1f" font-weight="%s" '
                   'text-anchor="%s" font-family="%s"%s>%s</text>'
                   % (x, y, fill, size, weight, anchor, family,
                      ' xml:space="preserve"' if s.startswith(" ") else "", html.escape(s)))

    def box(x, y, w, h, fill=None, stroke=None, sw=0.8):
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="%s"%s/>'
                   % (x, y, w, h, fill or "none",
                      ' stroke="%s" stroke-width="%s"' % (stroke, sw) if stroke else ""))

    def cell(x, y, state):
        if state == cc.MATCHED:
            box(x, y, CELL_W, CELL_H, fill=t["match"])
        elif state == cc.SCHEMA_ONLY:
            box(x, y, CELL_W, CELL_H, fill=t["match"])
            box(x, y, CELL_W, CELL_H, fill="url(#hatch)")
        elif state == cc.DIFFERED:
            box(x, y, CELL_W, CELL_H, fill=t["divergence"])
        elif state == cc.OBSERVED:
            box(x, y, CELL_W, CELL_H, fill="url(#dots)")
        else:
            box(x, y, CELL_W, CELL_H, stroke=t["rule"])

    out.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
               % (width, height, width, height))
    out.append('<defs>'
               '<pattern id="hatch" width="4" height="4" patternTransform="rotate(135)" '
               'patternUnits="userSpaceOnUse">'
               '<line x1="0" y1="0" x2="0" y2="4" stroke="%s" stroke-width="1.1"/></pattern>'
               '<pattern id="dots" width="4" height="4" patternTransform="rotate(45)" '
               'patternUnits="userSpaceOnUse">'
               '<line x1="0" y1="0" x2="0" y2="4" stroke="%s" stroke-width="0.8"/></pattern>'
               '</defs>' % (t["hatch"], t["rule2"]))
    box(0, 0, width, height, fill=t["surface"])

    text(PAD, 24, "The relation corpus, case by participant", t["ink"], 15, "600", family=base.SANS)
    text(PAD, 40, "%d cases, %d of which assert rows as well as a schema."
                  % (len(model["cases"]), sum(model["declares_rows"].values())),
         t["ink2"], 9.5, family=base.SANS)

    # The legend, one swatch per state, drawn before the grid so the reader meets the vocabulary
    # first. Its swatches are counted by probe/selfcheck.sh along with the cells. Wrapped on width
    # rather than laid out in one row: at five states the row ran off the edge of the drawing, and
    # a legend a reader cannot finish is worse than no legend.
    lx, ly = PAD, 54
    for state in (cc.MATCHED, cc.SCHEMA_ONLY, cc.DIFFERED, cc.UNSUPPORTED, cc.OBSERVED):
        span = CELL_W + 5 + len(cc.STATE_NAME[state]) * 4.6 + 14
        if lx + span > width - PAD:
            lx, ly = PAD, ly + 15
        cell(lx, ly, state)
        text(lx + CELL_W + 5, ly + 8, cc.STATE_NAME[state], t["ink2"], 8.5, family=base.SANS)
        lx += span

    for i, (label, _) in enumerate(COLUMNS):
        x = PAD + GUTTER + NAME_W + i * COL_W + CELL_W / 2
        text(x, HEAD_H - 8, label, t["ink2"], 8.5, anchor="middle", family=base.SANS)

    y = HEAD_H
    for group in model["groups"]:
        text(PAD, y + 11, group["label"], t["ink3"], 9, "500", family=base.SANS)
        y += GROUP_H
        for case_id in group["cases"]:
            if model["declares_rows"][case_id]:
                # Which rows the hatch is about: without it a hatched cell reads as a limit of the
                # participant rather than as half of what this particular case asserts.
                box(PAD, y + 1, 3, CELL_H - 2, fill=t["ink3"])
            text(PAD + GUTTER, y + CELL_H - 2, short_name(case_id), t["ink2"], 8.5)
            for i, (label, _) in enumerate(COLUMNS):
                cell(PAD + GUTTER + NAME_W + i * COL_W, y, model["cells"][label][case_id])
            y += ROW_H

    y += 18
    text(PAD, y, "the bar left of a case marks one that asserts rows", t["ink3"], 8.5,
         family=base.SANS)
    y += 13
    for line in footer:
        text(PAD, y, line, t["ink3"], 7.5)
        y += 11
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------- page ----

SECTION = """
  <h2 id="relations">The relation corpus</h2>
  <p class="lede">A second measurement, on a second corpus: %(cases)d cases written by hand against
    the sentences of the relation documentation, compiled to protobuf and read by %(participants)d
    implementations. It shares no case with the matrix above, so it shares no column.</p>
  <div class="rollup">%(rollup)s</div>
  <div class="legend rel-legend">%(legend)s</div>
  <p class="lede rel-note">%(note)s</p>
  <div class="controls">
    <button id="rel-all" aria-pressed="true">All %(cases)d cases</button>
    <button id="rel-differs" aria-pressed="false">Only rows where someone differs</button>
  </div>
  <div class="matrix-meta">
    <span class="hint">Click or tap a cell to open what that participant answered, what the case
      asserts, and where they differ, why.</span>
  </div>
  <div class="matrix-pane">
    <div class="scroll" tabindex="0" role="region" aria-label="Relation corpus">
      <table id="rel-matrix"><thead><tr id="rel-head"></tr></thead><tbody id="rel-body"></tbody></table>
    </div>
  </div>
  <p class="meta">The saved columns are
    <a href="%(repo)s/blob/main/results/relations">results/relations/</a>, one file per
    participant; <code>probe/relations/replay.sh</code> rebuilds one from nothing and requires it
    back. The cases are <a href="%(repo)s/blob/main/tests/relations">tests/relations/</a>, and the
    reasons behind the differing cells are
    <a href="%(repo)s/blob/main/results/relations/differed.json">differed.json</a>.</p>
  <script type="application/json" id="relations-data">%(data)s</script>
  <script>
  (function () {
    const D = JSON.parse(document.getElementById("relations-data").textContent);
    const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
      ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
    // The five states are the ones probe/relations/check_column.py forms, in its own order, and the
    // fill for each is .rst0 to .rst4 in the stylesheet. Named here so a state added there without
    // a fill here shows as an unstyled cell rather than as a wrong colour.
    const MATCHED = 0, SCHEMA_ONLY = 1, DIFFERED = 2, UNSUPPORTED = 3, OBSERVED = 4;
    let onlyDiffering = false, open = null;

    function differs(caseId) {
      return D.participants.some(p => D.cells[p][caseId] === DIFFERED);
    }

    function detail(caseId, participant) {
      const state = D.cells[participant][caseId];
      const c = D.cases[caseId], answer = D.answers[participant][caseId];
      const reason = (D.reasons[participant] || {})[caseId];
      let out = '<div class="detail"><div class="detail-toolbar">' +
        '<h3><span class="case-name">' + esc(caseId) + '</span>' +
        '<span class="pair-mark">' + esc(participant) + '</span>' +
        '<span class="state">' + esc(D.states[state].name) + '</span></h3>' +
        '<button class="detail-close" type="button">Close</button></div>' +
        '<p class="status-note">' + esc(D.states[state].note) + '</p><dl>';
      out += "<dt>answered</dt><dd>" + esc(answer) + "</dd>";
      if (c.mark === "score") {
        out += "<dt>asserts</dt><dd>" + esc(c.schema) +
               (c.rows === null ? "" : " rows " + esc(c.rows || "(none)")) + "</dd>";
      } else {
        out += "<dt>asserts</dt><dd>nothing; this case ships without an expectation on purpose</dd>";
      }
      out += "<dt>spec</dt><dd>" + esc(c.spec_ref) + "</dd>";
      if (reason) {
        out += "<dt>why</dt><dd>" + esc(reason.what) +
               (reason.same_as ? ' <em>The same cause the 98-plan corpus records as ' +
                 esc(reason.same_as) + ".</em>" : "") +
               (reason.outcome ? " <em>Triaged " + esc(reason.outcome) + ".</em>" : "") + "</dd>";
      }
      return out + "</dl></div>";
    }

    function closeDetail() {
      if (!open) return;
      const row = document.getElementById("rel-detail-row");
      if (row) row.remove();
      open.classList.remove("on");
      open = null;
    }

    function toggle(td, caseId, participant) {
      const same = open === td;
      closeDetail();
      if (same) return;
      const tr = document.createElement("tr");
      tr.id = "rel-detail-row";
      tr.className = "detail-row";
      tr.innerHTML = '<td colspan="' + (D.participants.length + 1) + '">' +
                     detail(caseId, participant) + "</td>";
      td.closest("tr").after(tr);
      td.classList.add("on");
      open = td;
      tr.querySelector(".detail-close").addEventListener("click", closeDetail);
    }

    function draw() {
      const head = document.getElementById("rel-head");
      head.innerHTML = '<th class="corner">case</th>' +
        D.participants.map(p => '<th><span class="column-name">' + esc(p) + "</span></th>").join("");
      const body = document.getElementById("rel-body");
      let html = "";
      for (const group of D.groups) {
        const rows = group.cases.filter(id => !onlyDiffering || differs(id));
        if (!rows.length) continue;
        // The same row shape the matrix above uses: a sticky <th class="case"> that does not wrap,
        // and a group heading in its own <th>. Built out of a <td class="corner"> instead, the case
        // names wrapped onto two lines and the cells stretched to fill what was left.
        html += '<tr class="group"><th>' + esc(group.label) + '</th><td colspan="' +
                D.participants.length + '"></td></tr>';
        for (const id of rows) {
          const short = id.includes("/") ? id.slice(id.indexOf("/") + 1) : id;
          html += '<tr><th class="case" title="' + esc(id) + '">' +
                  '<span class="rel-rowmark">' + (D.declares_rows[id] ? "|" : "&nbsp;") + "</span>" +
                  esc(short) + "</th>";
          for (const p of D.participants) {
            html += '<td class="cell rst' + D.cells[p][id] + '" data-case="' + esc(id) +
                    '" data-p="' + esc(p) + '"><i></i></td>';
          }
          html += "</tr>";
        }
      }
      body.innerHTML = html;
      body.querySelectorAll("td.cell").forEach(td =>
        td.addEventListener("click", () => toggle(td, td.dataset.case, td.dataset.p)));
      open = null;
    }

    document.getElementById("rel-all").addEventListener("click", () => {
      onlyDiffering = false;
      document.getElementById("rel-all").setAttribute("aria-pressed", "true");
      document.getElementById("rel-differs").setAttribute("aria-pressed", "false");
      draw();
    });
    document.getElementById("rel-differs").addEventListener("click", () => {
      onlyDiffering = true;
      document.getElementById("rel-all").setAttribute("aria-pressed", "false");
      document.getElementById("rel-differs").setAttribute("aria-pressed", "true");
      draw();
    });
    draw();
  })();
  </script>
"""

ROLLUP_ROW = """<div class="row"><span class="name">%(name)s</span>
      <span class="bar">%(bar)s</span>
      <span class="num">%(num)s</span></div>"""


def page_model():
    """Everything the page's own table needs, from the same verdicts the picture draws.

    The page carries a table rather than the picture: a reader who wants to know why a cell is red
    can open it there, and the picture cannot answer that. The SVG stays what the README shows,
    where nothing runs.
    """
    model = build()
    triage_path = os.path.join(ROOT, "results", "relations", "differed.json")
    with io.open(triage_path, encoding="utf-8") as fh:
        triage = json.load(fh)

    cases, cells, answers, reasons = {}, {}, {}, {}
    for case in model["cases"]:
        cases[case["id"]] = {"mark": case["mark"], "schema": case["schema"],
                             "rows": case["rows"], "spec_ref": case["spec_ref"]}
    for label, name in COLUMNS:
        one = model["models"][label]
        cells[label] = model["cells"][label]
        answers[label] = {case_id: text for case_id, (_, text) in one["answers"].items()}
        reasons[label] = {}
        for case_id, rule_id in triage["cells"].get(name, {}).items():
            rule = triage["rules"][rule_id]
            reasons[label][case_id] = {
                "id": rule_id, "kind": rule["kind"], "what": rule["what"],
                "same_as": rule.get("same_as"),
                "outcome": rule.get("triage", {}).get(name, {}).get("outcome"),
            }
    return {
        "participants": [label for label, _ in COLUMNS],
        "groups": [{"label": g["label"], "cases": g["cases"]} for g in model["groups"]],
        "cases": cases, "cells": cells, "answers": answers, "reasons": reasons,
        "states": [{"name": cc.STATE_NAME[s], "note": STATE_NOTE[s]}
                   for s in (cc.MATCHED, cc.SCHEMA_ONLY, cc.DIFFERED, cc.UNSUPPORTED, cc.OBSERVED)],
        "declares_rows": model["declares_rows"],
        "versions": model["versions"], "taken": model["taken"],
    }


def section(repo):
    """The block probe/heatmap.py puts on the page, built from the same verdicts as the picture."""
    model = build()
    order = [cc.MATCHED, cc.SCHEMA_ONLY, cc.DIFFERED, cc.UNSUPPORTED]
    tone = {cc.MATCHED: "m", cc.SCHEMA_ONLY: "s", cc.DIFFERED: "d", cc.UNSUPPORTED: "u"}
    scale = 5.2

    rows = []
    for label, _ in COLUMNS:
        counts = tally(model, label)
        bar = "".join('<span class="%s" style="width:%.1fpx"></span>'
                      % (tone[state], counts.get(state, 0) * scale)
                      for state in order if counts.get(state))
        matched = counts.get(cc.MATCHED, 0) + counts.get(cc.SCHEMA_ONLY, 0)
        num = "%d matched" % matched
        if counts.get(cc.SCHEMA_ONLY):
            num += " (%d on the schema alone)" % counts[cc.SCHEMA_ONLY]
        if counts.get(cc.DIFFERED):
            num += ", <b>%d differed</b>" % counts[cc.DIFFERED]
        if counts.get(cc.UNSUPPORTED):
            num += ", %d not accepted" % counts[cc.UNSUPPORTED]
        rows.append(ROLLUP_ROW % {"name": html.escape(label), "bar": bar, "num": num})

    legend = "".join(
        '<span class="key"><span class="sw"><i class="%s"></i></span>%s</span>'
        % (tone.get(state, "o"), html.escape(cc.STATE_NAME[state]))
        for state in order + [cc.OBSERVED])

    rows_declared = sum(model["declares_rows"].values())
    executing = [label for label, _ in COLUMNS if model["models"][label]["caps"]["executes"]]
    note = ("%d of the %d cases assert rows as well as a schema, and only %s executes, so every"
            " other agreement on those is an agreement about half of what the case says. Two of"
            " them, a right semi join and a right anti join, emit the same columns with the same"
            " nullability and are separated by nothing but their rows."
            % (rows_declared, len(model["cases"]), ", ".join(executing) or "no participant here"))

    return SECTION % {"cases": len(model["cases"]), "participants": len(COLUMNS),
                      "rollup": "\n      ".join(rows), "legend": legend,
                      "note": html.escape(note), "repo": repo,
                      "data": script_data.dumps(page_model(), ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":"))}


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what not in ("svg-light", "svg-dark"):
        raise SystemExit(__doc__)
    sys.stdout.write(svg(build(), what.split("-", 1)[1]))
