"""Can each check fail? Break one invariant at a time and require that check to notice.

The corpus this directory lives in learned the lesson the hard way: three of its own
guards were written, committed, and could never fire. A green run over the whole corpus
establishes nothing until every check has been shown to catch its own violation, and to
be the check that catches it rather than a neighbour that happens to trip first.

Each test below copies the corpus, breaks exactly one thing, and asserts two facts: the
named check reports it, and the same check passes on the case before it was broken.

    python3 -m pytest tests/relations/test_negative.py
"""

import json
import os
import shutil

import pytest

from tests.relations.lib import gate, paths

pytestmark = pytest.mark.skipif(
    not paths.bindings_available(),
    reason="protobuf bindings absent; run tests/relations/bootstrap.sh",
)


@pytest.fixture
def corpus(tmp_path):
    """A throwaway copy of the corpus, so a break cannot escape into the real one."""
    shutil.copytree(paths.cases_dir(), tmp_path / "cases")
    shutil.copytree(paths.bundles_dir(), tmp_path / "bundles")
    shutil.copy(paths.baseline_path(), tmp_path / "coverage.json")
    return tmp_path


def edit(corpus, case, old, new):
    p = corpus / "cases" / f"{case}.yaml"
    s = p.read_text()
    assert old in s, f"{case}: the text to break is not there: {old!r}"
    p.write_text(s.replace(old, new, 1))


def compile_case(corpus, case):
    return gate.Case(str(corpus / "cases" / f"{case}.yaml"), paths.extensions_dir())


def compile_error(corpus, case):
    """The error compiling this case raises, or None if it compiles.

    Reported as text rather than asserted as a type: what matters is that the corpus
    refuses the document, not which layer of it objected first.
    """
    try:
        compile_case(corpus, case)
    except Exception as e:  # noqa: BLE001 - any refusal is the point
        return f"{type(e).__name__}: {e}"
    return None


def run(corpus, case, check):
    """The named check against a case in the broken copy."""
    c = compile_case(corpus, case)
    if check is gate.check_drift:
        return gate.check_drift(c, bundles=str(corpus / "bundles"))
    return check(c)


def assert_caught(corpus, case, check, breaker):
    """The check is satisfied before the break and reports it after."""
    before = run(corpus, case, check)
    assert before in (None, gate.SKIP), "the case was already failing this check"
    breaker()
    got = run(corpus, case, check)
    assert got not in (None, gate.SKIP), f"{check.__name__} did not catch the break"
    return got


# ---------------------------------------------------------------- the case will not load
def test_duplicate_yaml_key(corpus):
    """Two keys with one name: the loser is silently dropped by a permissive loader."""
    edit(
        corpus,
        "join/left",
        "kind: KIND_POSITIVE",
        "kind: KIND_POSITIVE\nkind: KIND_UNRESOLVED",
    )
    assert compile_error(corpus, "join/left") is not None


def test_unknown_protobuf_field(corpus):
    """A misspelled field name must not be accepted and then ignored."""
    edit(corpus, "join/left", "type: JOIN_TYPE_LEFT", "join_type: JOIN_TYPE_LEFT")
    assert compile_error(corpus, "join/left") is not None


def test_expression_is_not_a_string(corpus):
    """A structural mistake in an expression must be an error, not a silent default."""
    edit(
        corpus,
        "join/left",
        'expression: "cmp.equal:any_any($0, $2):bool"',
        "expression: [1, 2]",
    )
    assert compile_error(corpus, "join/left") is not None


# ------------------------------------------------------------------------- the checks
def test_schema_catches_a_corrupted_expectation(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_schema,
        lambda: edit(corpus, "join/left", 'schema: "a0:i64,', 'schema: "a0:i32,'),
    )


def test_schema_catches_a_wrong_nullability(corpus):
    """The single character this whole corpus is mostly about."""
    assert_caught(
        corpus,
        "join/left",
        gate.check_schema,
        lambda: edit(corpus, "join/left", 'b0:i64?, b1:i64?"', 'b0:i64, b1:i64?"'),
    )


def test_declarations_catches_a_falsified_output_type(corpus):
    assert_caught(
        corpus,
        "project/decimal_divide",
        gate.check_declarations,
        lambda: edit(
            corpus, "project/decimal_divide", "):decimal<21,8>", "):decimal<20,2>"
        ),
    )


def test_kind_catches_a_valid_plan_labelled_invalid(corpus):
    """A case may not claim invalidity it cannot demonstrate."""
    assert_caught(
        corpus,
        "join/left",
        gate.check_kind,
        lambda: edit(
            corpus, "join/left", "kind: KIND_POSITIVE", "kind: KIND_INVALID_PLAN"
        ),
    )


def test_unresolved_catches_an_expectation(corpus):
    case = "unresolved/virtual_table_row_type_differs_from_schema"
    assert_caught(
        corpus,
        case,
        gate.check_unresolved,
        lambda: (corpus / "cases" / f"{case}.yaml").write_text(
            (corpus / "cases" / f"{case}.yaml").read_text()
            + 'expect: {schema: "n:i32"}\n'
        ),
    )


def test_unresolved_catches_a_missing_issue(corpus):
    """ "Unsettled" without a reference is an opinion, not a record."""
    case = "unresolved/virtual_table_row_type_differs_from_schema"
    assert_caught(
        corpus,
        case,
        gate.check_unresolved,
        lambda: edit(
            corpus, case, "tracked_in: substrait-io/substrait#1211", 'tracked_in: ""'
        ),
    )


def test_names_catches_renamed_expectation_columns(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_names,
        lambda: edit(
            corpus,
            "join/left",
            'schema: "a0:i64, a1:i64?, b0:i64?',
            'schema: "x0:i64, x1:i64?, x2:i64?',
        ),
    )


def test_names_catches_a_removed_root_name(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_names,
        lambda: edit(
            corpus, "join/left", "names: [a0, a1, b0, b1]", "names: [a0, a1, b0]"
        ),
    )


def test_rows_catches_a_cell_of_the_wrong_type(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_rows,
        lambda: edit(
            corpus,
            "join/left",
            '["2::i64", "2::i64?", "2::i64"',
            '["2::i64", "2::i64?", "\'x\'::string"',
        ),
    )


def test_rows_catches_a_row_that_is_too_wide(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_rows,
        lambda: edit(
            corpus,
            "join/left",
            '- ["2::i64", "2::i64?", "2::i64", "20::i64?"]',
            '- ["2::i64", "2::i64?", "2::i64", "20::i64?", "9::i64"]',
        ),
    )


def test_rows_catches_a_null_in_a_required_column(corpus):
    """The expected first column is a required i64, so no row of it may be null."""
    assert_caught(
        corpus,
        "join/left",
        gate.check_rows,
        lambda: edit(
            corpus,
            "join/left",
            '- ["2::i64", "2::i64?", "2::i64", "20::i64?"]',
            '- ["null::i64?", "2::i64?", "2::i64", "20::i64?"]',
        ),
    )


def test_vt_arity_catches_a_row_with_an_extra_cell(corpus):
    assert_caught(
        corpus,
        "read/virtual_table",
        gate.check_vt_arity,
        lambda: edit(
            corpus,
            "read/virtual_table",
            '{fields: ["1::i64", "\'a\'::string?"]}',
            '{fields: ["1::i64", "\'a\'::string?", "9::i64"]}',
        ),
    )


def test_signature_arity_catches_an_extra_argument_in_the_name(corpus):
    """The mistake this check exists for: I made it, and a consumer caught it, not the gate."""
    assert_caught(
        corpus,
        "window/lead_is_nullable",
        gate.check_signature_arity,
        lambda: edit(
            corpus,
            "window/lead_is_nullable",
            'name: "lead:any"',
            'name: "lead:any_i64"',
        ),
    )


def test_signature_arity_catches_a_bare_name(corpus):
    """`rank` is not a function signature; `rank:` is."""
    assert_caught(
        corpus,
        "window/row_number",
        gate.check_signature_arity,
        lambda: edit(
            corpus, "window/row_number", 'name: "row_number:"', 'name: "row_number"'
        ),
    )


def test_drift_catches_a_tampered_bundle(corpus):
    def tamper():
        p = corpus / "bundles" / "join" / "left.pb"
        blob = bytearray(p.read_bytes())
        blob[-1] ^= 0xFF
        p.write_bytes(bytes(blob))

    assert_caught(corpus, "join/left", gate.check_drift, tamper)


def test_drift_catches_a_missing_bundle(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_drift,
        lambda: os.remove(corpus / "bundles" / "join" / "left.pb"),
    )


def test_identity_catches_a_missing_spec_ref(corpus):
    """A case with nothing to point at records an answer without its question."""
    assert_caught(
        corpus,
        "join/left",
        gate.check_identity,
        lambda: edit(
            corpus,
            "join/left",
            "spec_ref: relations/logical_relations.md#join-types",
            'spec_ref: ""',
        ),
    )


def test_identity_catches_an_id_from_another_area(corpus):
    assert_caught(
        corpus,
        "join/left",
        gate.check_identity,
        lambda: edit(
            corpus,
            "join/left",
            "id: join/left/output-nullability",
            "id: set/left/output-nullability",
        ),
    )


def test_roundtrip_catches_a_renderer_that_alters_the_program(monkeypatch):
    """This check guards the tooling rather than the case.

    Nothing an author can write makes it fail, because the renderer falls back to the
    plain protobuf shape for anything its sugar cannot express. What it does catch is a
    renderer that returns a document lowering to a different program, which is how a
    corpus starts testing something nobody wrote. So the break here is a seeded bug in
    the renderer, not a broken case.
    """
    case = gate.Case(
        os.path.join(paths.cases_dir(), "join", "left.yaml"), paths.extensions_dir()
    )
    assert gate.check_roundtrip(case) is None

    real = gate.render.render

    def altered(plan, case_id="imported"):
        doc, ctx = real(plan, case_id)
        doc["plan"]["relations"][0]["root"]["names"][0] = "renamed"
        return doc, ctx

    monkeypatch.setattr(gate.render, "render", altered)
    assert gate.check_roundtrip(case) is not None


# ----------------------------------------------------------------- the corpus as a whole
def test_ratchet_catches_a_dropped_relation(corpus):
    """Deleting the only cases that cover a relation must not quietly narrow the corpus."""
    for name in os.listdir(corpus / "cases" / "aggregate"):
        os.remove(corpus / "cases" / "aggregate" / name)

    counts = gate.Counter()
    for path in gate.case_files(str(corpus / "cases")):
        gate.coverage(gate.Case(path, paths.extensions_dir()).plan, counts)
    previous = json.loads((corpus / "coverage.json").read_text())
    dropped = {k: v for k, v in previous.items() if counts.get(k, 0) < v}
    assert "rel:aggregate" in dropped
