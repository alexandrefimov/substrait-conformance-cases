# Vendored copies

Nothing here belongs to this repository, and none of it exists in the layout this
directory is written for. Upstream, `lib/paths.py` finds the specification's own
`extensions/` and `proto/` at the repository root and never looks in here; porting
`tests/relations/` there is deleting this directory and `../bootstrap.sh`.

- `extensions/` — four extension files from `substrait-io/substrait` at v0.102.0, the
  release the cases were authored against. They are what the derived schemas are computed
  from, so pinning them pins half of every expectation. The corpus also passes against the
  extension files at 8ca7db0, the tip of the specification's main branch on 2026-09-10.
- `proto/` — the Substrait protos the contract imports, from the same release. Only the
  five files `relation_test.proto` reaches transitively are here.

Both are Apache-2.0 and carry their own SPDX headers. Update them together with
`TARGET_RELEASE` in `lib/paths.py`, and recompile the bundles afterwards.
