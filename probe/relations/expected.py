"""Writes results/relations/expected.json: what each committed bundle asks for, as plain text.

    python3 probe/relations/expected.py --write
    python3 probe/relations/expected.py --check     # what would change, without writing

A bundle is protobuf, and probe/selfcheck.sh is contracted to need python3 and nothing else. So the
expectations are extracted once, by this file, into a form the self-check, the checker and the page
can read without protobuf bindings - the same arrangement expected.json has for the 98-case corpus,
and for the same reason.

The extract is worth only as much as its tie to the bundles, so each entry carries the SHA-256 of
the file it came from. A bundle edited without rerunning this script fails the self-check on the
hash rather than on a number nobody recomputes, and no participant's column is ever compared with
an expectation taken from a case that has since changed.

Nothing here is a judgement. The schema and the rows are the ones the case declares, rendered by
probe/relations/corpus.py; what a case may declare is settled by the ten checks in
tests/relations/lib/gate.py before a bundle exists.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus  # noqa: E402

OUT = os.path.join(corpus.ROOT, "results", "relations", "expected.json")


def build():
    cases = []
    for path in corpus.bundle_paths():
        case = corpus.read(path)
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        rows = corpus.expected_rows(case)
        mark = corpus.KIND_MARK.get(case.kind)
        if mark is None:
            sys.exit("%s: %s carries no marker" % (case.id, corpus.KIND_NAME.get(case.kind)))
        cases.append({
            "id": case.id,
            "bundle": os.path.relpath(path, corpus.BUNDLES),
            "sha256": digest,
            "kind": corpus.KIND_NAME[case.kind],
            "mark": mark,
            "spec_ref": case.spec_ref,
            # A case that is never scored ships without an expectation, and null here says so; an
            # empty schema string would read as "expects no columns".
            "schema": corpus.render_named_struct(case.expect.schema) if mark == corpus.SCORED else None,
            "rows": (corpus.render_rows(rows, corpus.in_sequence(case))
                     if rows is not None else None),
        })
    # One value over the whole corpus, written into every column's head. Per-case hashes catch a
    # bundle edited under a saved extract; this catches the other direction - a column taken
    # against one set of cases and later scored against another, where each side is internally
    # consistent and only their pairing is wrong.
    digest = hashlib.sha256(
        "".join("%s\t%s\n" % (c["id"], c["sha256"]) for c in cases).encode()
    ).hexdigest()[:12]
    return {
        "corpus": os.path.relpath(corpus.BUNDLES, corpus.ROOT),
        "generator": "probe/relations/expected.py",
        "fingerprint": digest,
        "cases": cases,
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if mode == "--write":
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % os.path.relpath(OUT, corpus.ROOT))
        return 0
    if mode != "--check":
        sys.exit("usage: expected.py --write|--check")
    if not os.path.exists(OUT):
        print("MISSING: %s" % os.path.relpath(OUT, corpus.ROOT), file=sys.stderr)
        return 1
    with open(OUT, encoding="utf-8") as fh:
        saved = fh.read()
    if saved == text:
        print("expected.json is what the bundles compile to: %d cases" % len(build()["cases"]))
        return 0
    print("DIFFERS: %s is not what the bundles produce today; rerun with --write"
          % os.path.relpath(OUT, corpus.ROOT), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
