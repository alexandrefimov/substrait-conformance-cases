# Vendored copies

These are Apache-2.0 copies of the specification dependencies used outside its repository:

- `extensions/`: four extension files from Substrait v0.102.0, the authored case baseline.
  The corpus also passed against the files at `8ca7db0`, spec main on 2026-09-10.
- `proto/`: the five v0.102.0 Substrait proto files imported transitively by the test contract.

`lib/paths.py` prefers the specification repository's own `extensions/` and `proto/`. Porting
upstream removes this directory and `../bootstrap.sh`. Update vendored files with
`TARGET_RELEASE` in `lib/paths.py`, then recompile bundles. Files retain their SPDX headers.
