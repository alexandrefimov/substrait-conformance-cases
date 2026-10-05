# Relation test vectors

Each case pins a specification sentence and asserts an output schema and, where the rules
settle them, rows. YAML sources compile to committed `substrait.test.RelationTestCase` bundles.
Consumers need protobuf bindings, not YAML or the authoring parser. The contract in
`proto/substrait/test/relation_test.proto` contains no version-specific fields and can be
compiled against the consumer's Substrait protos.

```
cases/<area>/<name>.yaml      the case, hand written and reviewed
bundles/<area>/<name>.pb      what it compiles to, committed
coverage.json                 what the corpus covers, as a ratchet
lib/                          the compiler, the renderer and the checks
```

## Using the corpus in a consumer

Read `bundles/*.pb` as `RelationTestCase` messages. Bind the fixtures in `tables`, pass the
embedded plan to your consumer, and compare the returned schema and, if your consumer executes,
the expected rows. Preserve duplicates; compare row order only when the case requires it.
Score positive cases only. Record invalid and unresolved cases as observations.

The [existing runners](../../probe/relations/README.md) show how schema-only libraries and
executing engines use the same bundles. The [saved relation matrix](https://alexandrefimov.github.io/substrait-conformance-cases/#relations)
shows their saved measurements. Authoring or rebuilding bundles needs the setup described
[below](#running-this-outside-the-specification-repository).

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

The `join_physical/` cases also check wire enum numbering. Logical and physical join messages
assign values 6 through 9 differently; copying the numeric logical enum changes the operation.
Logical order is left anti, left single, right semi, right anti; physical order is right semi,
left anti, right anti, left single.
Right semi and right anti have identical schemas, so `hash_right_anti` needs row comparison to
distinguish them. A schema-only harness cannot check that distinction.

## What the checks establish

`lib/gate.py` checks every case; `test_negative.py` breaks each invariant and requires its
named check to fail. The authored schema must agree with a separately encoded derivation from
relation rules and extension files. That same derivation checks declared function output types,
so those two checks share a possible rule error rather than providing two independent readings.

Round-trip checks require rendered YAML to lower to the same program. Drift checks require
committed bundles to match their sources. `coverage.json` tracks relations, join kinds, set
operations and read kinds; coverage may grow but not shrink.

## Limits

Expected rows are authored from the rules, not captured from an engine. Most use
`ORDER_MULTISET`: compare complete rows while preserving duplicates. Sort and fetch cases use
`ORDER_SEQUENCE`; their fixed order is part of the expected result.

`KIND_INVALID_PLAN` covers mismatched declared function return types and structural violations
in `lib/validity.py`: set-input arity, out-of-range emit mappings and project field references.
A new invalidity claim needs a corresponding check. Positive cases undergo the same validity
checks so an invalid plan cannot pass merely by deriving the asserted schema.

## Running this outside the specification repository

Upstream, `buf generate` writes the protobuf bindings and `pytest` already has them on its
path, and nothing here needs configuring. Elsewhere, `vendor/` holds the extension files
and the Substrait protos at the release the cases were authored against, and
`bootstrap.sh` generates the bindings into an ignored `.bindings/`. `lib/paths.py` prefers
the repository's own `extensions/` and `proto/` whenever they are present, so porting this
directory upstream is deleting `vendor/` and `bootstrap.sh`.
