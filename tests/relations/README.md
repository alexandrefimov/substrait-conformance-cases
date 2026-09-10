# Relation test vectors

Executable cases for the behaviour the relation documentation states: what schema a
relation produces, and where the rules are explicit enough, what rows it produces. Each
case names the sentence it pins, so a disagreement between two consumers is traceable to
a line of the specification rather than to a difference of opinion.

A case is authored once, in YAML, and compiled to one serialized
`substrait.test.RelationTestCase` under `bundles/`. Reading the corpus needs protobuf
bindings and nothing else: no YAML, no authoring parser, no text format. The contract is
40 lines of `proto/substrait/test/relation_test.proto` and carries no version-specific
content, so a consumer compiles it against whatever Substrait protos it already uses.

```
cases/<area>/<name>.yaml      the case, hand written and reviewed
bundles/<area>/<name>.pb      what it compiles to, committed
coverage.json                 what the corpus covers, as a ratchet
lib/                          the compiler, the renderer and the checks
```

## Running

```sh
pytest tests/relations           # every case against every check
python3 tests/relations/build.py --write   # recompile bundles after editing a case
```

`build.py --check` reports what would change without writing, which is the form CI wants.
A case edit that is not followed by `--write` fails the drift check, because the bundle is
what a consumer actually reads.

## Writing a case

```yaml
id: join/left/output-nullability
spec_ref: relations/logical_relations.md#join-types
kind: KIND_POSITIVE
notes: >-
  Left returns all records from the left input, padding the right side with nulls
  where there is no partner.
inputs:
  t_left:
    schema: "a0:i64, a1:i64?"
    rows: [["1::i64", "null::i64?"], ["2::i64", "2::i64?"]]
plan:
  ...
expect:
  schema: "a0:i64, a1:i64?, b0:i64?, b1:i64?"
```

The `plan` block is the protobuf shape of `substrait.Plan`, field for field, with
shorthand only where the descriptor expects a type, a named struct, an expression or a
literal: `i64?`, `a:i64, b:string`, `$0`, `1::i64`, `cmp.equal:any_any($0, $2):bool`. A
misspelled field name is an error rather than a silently ignored key, and so is a
duplicate YAML key. `$table: t_left` binds a read to a named fixture so a schema case is
not also a virtual-table support test.

A struct column carries the names of its fields inside the type, as
`s:struct<x:i64, y:i64?>`, because `NamedStruct.names` is one depth-first list over the
whole tree rather than one name per column. Writing them where they belong is what keeps
the count right: the specification's own example, `a:struct<b:i64, c:i64>,
d:struct<e:i64, f:i64, g:i64>`, is two columns and seven names.

Input data lives outside the plan in `inputs`, and reaches a consumer as
`RelationTestCase.tables`. A harness that cannot bind external tables may build a
virtual-table plan from the same rows.

Three kinds of case:

- `KIND_POSITIVE` asserts the schema, and the rows when it declares them.
- `KIND_INVALID_PLAN` violates a stated validity rule. Whether a given consumer API has
  to reject it is not settled here; a harness reports what it observed.
- `KIND_UNRESOLVED` ships without an expectation and is never scored. It exists so a
  question the specification has not answered is recorded as a case rather than as an
  argument, and it must name where the question is tracked.

One case family is about the wire and not about a relation's rules. `JoinRel` and the three
physical join messages number their `JoinType` enum differently for four values: 6, 7, 8 and 9
mean left anti, left single, right semi and right anti in the logical message and right semi,
left anti, right anti and left single in the physical ones. The cases under `join_physical/`
carry those four numbers on a `HashJoinRel` and assert what the physical numbering says they
are, so a tool that rewrites a logical join into a physical one by copying the number, or that
resolves a physical join with `JoinRel`'s enum, answers them differently. `hash_right_anti` is
the one worth reading: right anti and right semi emit the same columns with the same
nullability, so nothing but the rows tells them apart, and a harness comparing types alone
reports whichever the consumer picked as a pass.

## What the checks establish

Eleven checks run over every case, in `lib/gate.py`, and `test_negative.py` breaks each one
in turn and requires that check, by name, to catch it. A check that has never been shown
to fail is a comment the interpreter happens to run.

The schema a case declares is reproduced by an independent derivation from the relation
rules and the extension files, so an authored expectation and the tool have to agree.
That redundancy has a limit worth stating: the same derivation backs the check that every
declared `output_type` matches what the extension derives, so those two are one
implementation, and a mistaken rule inside it would be reflected in both. What they cannot
both be wrong about at once is a schema a person wrote by hand.

Two of the ten guard the tooling rather than the cases. The round-trip check fails if the
renderer returns a document that lowers to a different program, which is how a corpus
starts testing something nobody wrote. The drift check fails if a committed bundle is not
what its case compiles to today.

`coverage.json` counts relations, join types, set operations and read kinds. It may grow
and may not shrink, so removing the last case covering a relation is a deliberate diff on
a committed file rather than a number nobody looks at.

## Limits

The row expectations are the rows the specification's rules imply, computed by hand, not
output captured from an engine. Most cases declare `ORDER_MULTISET`, because most
relations fix no order and a harness must compare as a multiset there. The cases under
`sort/` and `fetch/` declare `ORDER_SEQUENCE` instead: a sort sets the orderedness and a
fetch maintains it, so the plan fixes which row comes first and a harness that compares
those as a multiset is not running them. A sort that ignores where nulls go passes the
multiset comparison and fails the sequence one, which is the whole difference between the
two cases under `sort/`.

`KIND_INVALID_PLAN` currently covers one class of invalidity: a declared `output_type`
that disagrees with the extension the function resolves to. A case may not claim
invalidity the corpus cannot demonstrate, so widening that class means teaching the
checker first.

## Running this outside the specification repository

Upstream, `buf generate` writes the protobuf bindings and `pytest` already has them on its
path, and nothing here needs configuring. Elsewhere, `vendor/` holds the extension files
and the Substrait protos at the release the cases were authored against, and
`bootstrap.sh` generates the bindings into an ignored `.bindings/`. `lib/paths.py` prefers
the repository's own `extensions/` and `proto/` whenever they are present, so porting this
directory upstream is deleting `vendor/` and `bootstrap.sh`.
