"""Builds derived-schema/manifest.json: one entry per case, none of it invented.

    python3 gen/make_manifest.py <directory of generator runs>

The directory is what gen/make_manifest.sh produces: for each generator, a subdirectory holding the
cases it wrote and a <generator>.out holding what it printed. Three things are merged:

  the generator      which Gen*.java writes the case - taken from which subdirectory it landed in;
  the note           the one line that generator prints for that case, as it prints it;
  the expectation    the schema and the wording of its source from expected.json, or the reason the
                     case is disputed.

Plus gen/sources.json, which is the only hand-written part: the issue a case comes from, for the few
where that is recorded. Everything else here is harvested, so the manifest cannot drift into saying
something the corpus does not.

Pairing a printed line with a case is not always the identity: some generators label a line with an
abbreviation. The rules are written out in LABEL_RULES below rather than guessed at, and the script
fails if a single case is left without a line.
"""
import glob, json, os, re, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# label as printed -> case name, per generator. Anything not listed pairs by identity, or by the
# label being the tail of the case name (`add` for `decimal_add`).
LABEL_RULES = {
    "GenSetOps":  lambda lab, line: "setop_" + lab.lower(),
    "GenSetData": lambda lab, line: "setdata_" + lab.lower(),
    # `=== true INNER ...` / `=== equality INNER ...`: the first word is the join predicate the case
    # carries, the second is the join type.
    "GenJoins":   lambda lab, line: ("join_" if lab == "true" else "joineq_") + line.split()[1].lower(),
}

# Some generators print their own answer on the same line ("substrait-java: RNN (3 columns)"). That
# is a measurement, and a measurement has no business in the record of what a case asserts: the
# manifest would then be describing the implementation it is used to check. Only the descriptive part
# is kept.
ANSWER = re.compile(r"\s{2,}substrait-java:.*$")

def clean(line):
    return re.sub(r"\s{2,}", "  ", ANSWER.sub("", line)).strip()

def pair(generator, cases, lines):
    """Returns {case: printed line}, or raises if any case is left unpaired."""
    out = {}
    for line in lines:
        label = line.split(None, 1)[0] if line.strip() else ""
        rule = LABEL_RULES.get(generator)
        name = rule(label, line) if rule else label
        if name not in cases:
            tail = [c for c in cases if c == label or c.endswith("_" + label)]
            if len(tail) != 1:
                raise SystemExit("%s: cannot pair the printed line %r with a case" % (generator, line))
            name = tail[0]
        out[name] = line
    missing = sorted(set(cases) - set(out))
    if missing:
        raise SystemExit("%s: no printed line for %s" % (generator, ", ".join(missing)))
    return out

def main(runs):
    exp = json.load(open(os.path.join(ROOT, "expected.json"), encoding="utf-8"))
    sources = json.load(open(os.path.join(ROOT, "gen", "sources.json"), encoding="utf-8"))
    silent, invalid = set(exp.get("spec_silent", [])), set(exp.get("spec_says_invalid", []))

    entries = {}
    for gen_dir in sorted(glob.glob(os.path.join(runs, "*", ""))):
        generator = os.path.basename(os.path.dirname(gen_dir))
        cases = sorted(os.path.basename(f)[:-5] for f in glob.glob(gen_dir + "*.json")
                       if not f.endswith("manifest.json"))
        if not cases:
            continue
        lines = [l[4:].rstrip() for l in open(os.path.join(runs, generator + ".out"), encoding="utf-8")
                 if l.startswith("=== ")]
        for case, line in pair(generator, cases, lines).items():
            if case in entries:
                raise SystemExit("%s is written by two generators: %s and %s"
                                 % (case, entries[case]["generator"], generator))
            note = clean(line)
            entry = {"case": case, "plan": case + ".json", "binary": case + ".bin",
                     "generator": generator, "note": note}
            if case in sources:
                entry["source"] = sources[case]["source"]
                entry["note"] = sources[case]["note"]
                # Keep what the generator says only when it says something the hand-written note does
                # not: for these cases it prints the case name and nothing else.
                if note and note != case:
                    entry["generator_says"] = note
            if case in exp["expected"]:
                entry["expectation"] = {"schema": exp["expected"][case]["schema"],
                                        "from": exp["expected"][case]["source"]}
            else:
                entry["expectation"] = {
                    "none": exp["disputed"].get(case, "no expectation recorded"),
                    "because": "the spec is silent" if case in silent else
                               "the spec says the plan is invalid" if case in invalid else "unclassified"}
            entries[case] = entry

    corpus = {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(ROOT, "derived-schema", "*.json"))
              if not f.endswith("manifest.json")}
    if set(entries) != corpus:
        raise SystemExit("the manifest does not cover the corpus: missing %s, extra %s"
                         % (sorted(corpus - set(entries))[:4], sorted(set(entries) - corpus)[:4]))
    print(json.dumps([entries[c] for c in sorted(entries)], ensure_ascii=False, indent=1))

main(sys.argv[1])
