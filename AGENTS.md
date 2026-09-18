# Working in this repository

This repository holds Substrait plans, the output schema the spec says each should produce, and what
each implementation answers. An implementation's answers to the whole corpus are its column,
`results/<NAME>.txt`. [README.md](README.md) says what the columns found; [METHOD.md](METHOD.md) is
how an expectation is made and what a match proves; [gen/README.md](gen/README.md) is how the plans
are built; [probe/README.md](probe/README.md) is how each participant is run and what it needs
installed; [deriver/README.md](deriver/README.md) is a second, independent reading of the rules.

## What has to stay true

- **An expectation comes from the spec text and nothing else.** `probe/expected.py` writes one per
  case and reads no plan, no generator and no participant's answer. An expectation copied from an
  answer turns a divergence into an agreement.
- **The deriver is a second reading only while it stays independent.** `deriver/` works from the
  spec text and the plan, and reads neither `probe/expected.py`, `expected.json` nor any declared
  `output_type`, and neither does whoever writes its rules. A rule written with the expectations
  open agrees by construction, and nothing afterwards can tell.
- **Every check can fail, on its own invariant.** Each check in `probe/selfcheck.sh` has a mutation
  in `probe/selfcheck-negative.sh` that breaks the invariant and requires the check's failure output
  to contain a given fragment. Make that fragment the invariant's name from the check's `FAILED`
  line, not a sentence of prose that the next edit will reword.
- **A tracked file is public.** No machine-local absolute paths, credentials, private endpoints, raw
  logs or tool caches. `probe/selfcheck.sh` rejects absolute paths and Cyrillic text; it looks for
  nothing else.
- **Generated files are regenerated, never edited.** Change the source, then rerun what writes the
  output:

  | output | written by |
  | --- | --- |
  | `derived-schema/`, `derived-schema-virtual-tables/`, `expected.json` | `probe/reverify.sh` with `UPDATE_CORPUS=1` |
  | `results/<NAME>.txt`, `results/MATRIX.txt`, `results/DIFFS.md`, `docs/` | `probe/reverify.sh` with `UPDATE_COLUMNS=1` |
  | the coverage block in `METHOD.md` | `probe/coverage.py`, whose output is pasted in |
  | `deriver/DERIVED.txt` | `python3 -m deriver.run --column` |
  | `deriver/COVERAGE.txt`, `deriver/PINNED.txt` | `python3 -m deriver.mutants --verbose`, `--per-case` |

  Written by hand: `probe/expected.py`, `differed.json`, `refused.json`, `gen/sources.json`, the
  prose of `README.md`, `METHOD.md`, `FINDINGS.md` and the directory READMEs, and the headers of
  `results/LIE.txt` and `results/BINDING.txt`.
- **A column is a measurement against `probe/versions.env`.** Changing a version there means
  retaking that participant's column in the same change; the column's first line names the run and
  the revision it was taken from. A drift run against today's releases (`LATEST=1`, or the weekly
  `drift` workflow) is an observation, not a new baseline: `results/DRIFT.txt` gains its block
  through a reviewed pull request, and the column stays as it was. `probe/reverify.sh` only reports
  unless given an update flag; use one only when your change is meant to change those outputs, read
  the whole generated diff afterwards, and never use one to make a failing check pass.

## Adding a case

1. **The plan.** Write or extend a generator in `gen/`; a new generator's class goes into `GENS` in
   both `gen/make_manifest.sh` and `probe/reverify.sh`. Leaves are shared named tables, which the
   engine probes create: a new table goes into `probe/acero_one.py`, `probe/duckdb_one.py` and
   `probe/datafusion_corpus_probe.rs`, and a table with rows also into `DATA` in
   `probe/to_virtual_tables.py`.
2. **The expectation.** Add it to `probe/expected.py`, with the sentence of the spec it rests on as
   its source. If the spec does not decide, the case goes into `SPEC_SILENT` with the reason and is
   measured without being scored; if the plan is invalid on purpose, into `SPEC_SAYS_INVALID`.
3. **The corpus and the columns, in one run.**
   `UPDATE_CORPUS=1 UPDATE_COLUMNS=1 bash probe/reverify.sh`, at the pins: it needs the probe
   environment from `probe/setup.sh`, and `SUBSTRAIT_JAVA_DIR` and `DF_DIR`. Afterwards check that
   in every column only the new case's row moved; anything else changing is a finding about the
   harness, not about the case. Gluten is not in this run: its column is taken by hand in a cluster,
   keeps the date of its last run, and has no answer for the new case until it is retaken.
4. **Reasons.** Every new differing cell needs a rule in `differed.json` with a `check` that
   `probe/check_differed.py` can test, and a triage per participant: `reported`, `spec-question`,
   `ours` or `open`. `open` means nobody has taken the difference anywhere yet, so before writing it
   search that implementation's tracker and `FINDINGS.md`: an `open` entry for a difference that was
   already reported is wrong in a way no check catches.
5. **The declaration experiments,** if the case declares an `output_type` or calls a function.
   `probe/lie_matrix.sh` swaps the declared output types and shows who repeats them;
   `probe/binding_matrix.sh` renames the declared functions and shows who resolves the call anyway.
   Rerun both and put their tables under the hand-written headers of `results/LIE.txt` and
   `results/BINDING.txt`.
6. **The deriver.** Regenerate `deriver/DERIVED.txt`, `deriver/COVERAGE.txt` and
   `deriver/PINNED.txt`; `probe/selfcheck.sh` then compares each derived schema with its
   expectation. Where the deriver has no rule for the case it declines, and a declined case passes.
   A case where the two differ fails, and it is settled by finding which reading of the spec is
   wrong, or that the spec does not decide, not by changing whichever is easier to change. A missing
   rule in `deriver/derive.py` is written by someone who has not read the expectation from step 2 -
   another contributor, or an agent session that never opened it. It gets a test in
   `deriver/test_derive.py` and, if the corpus reaches it, a mutant in `deriver/mutants.py`: a
   plausible wrong reading of the rule, so that `deriver/COVERAGE.txt` shows whether any case tells
   the two apart.
7. **The pages.** `probe/check_pages.py`, run by `probe/selfcheck.sh`, checks each count in the
   prose it has an entry for, and fails when the count no longer matches its file or the sentence no
   longer matches its pattern. A count without an entry goes unchecked, so search the pages for the
   old numbers yourself. When the new case splits a group that a sentence counted, the sentence is
   wrong rather than out of date: rewrite it, and its pattern in the same commit.

## Gates

The fast repository gates are:

```sh
bash probe/selfcheck.sh
bash probe/selfcheck-negative.sh
git diff --check
```

Passing them establishes that the repository agrees with itself; it reruns no participant and proves
nothing about the spec. For a change to a participant's runner, setup, normalization or column, run
`bash probe/replay_column.sh <NAME>` at the pinned version. CI runs the first two gates and replays
each of the nine columns at its pin. `probe/reverify.sh` is the full sweep and needs external
toolchains; do not present a partial or skipped sweep as a full one.

## Traps

- **`probe/lie_matrix.sh` and `probe/binding_matrix.sh` do not put `~/.cargo/bin` on `PATH`**, as
  `probe/reverify.sh` does. Without `cargo` on `PATH` they skip DataFusion and still succeed,
  leaving a table one column short.
- **Their raw output is not the saved file.** `results/LIE.txt` and `results/BINDING.txt` are the
  script's table under a header written by hand. The raw output also names temporary directories,
  which the absolute-path check rejects, and pads its table with trailing spaces, which
  `git diff --check` rejects.
- **`differed.json` is kept in its own key order.** Re-serializing it sorted turns a change to a few
  entries into a diff of hundreds of lines.
- **A module in `deriver/` named after a standard-library module shadows it** whenever a file in
  that directory is run directly, as `deriver/check.py` is. That is why the type model is
  `type_model.py`: Python 3.14 has `types` loaded before the script starts, so a local `types.py`
  went unnoticed there, and the 3.12 in CI imported it instead.
- **In a shell mutation, `"\n"` inside double quotes is a backslash and an `n`.** A replacement that
  spans a line break goes through `python3 -c`, where the escape is Python's.

## Working in parallel

Several agents work in this repository at once. Each task gets its own branch and its own worktree,
created from `origin/main` as a sibling of the primary checkout. The primary checkout is for
coordination only: do not edit in it or run generators there. Every other worktree, with its branch,
files and processes, belongs to someone else. Before editing, `git status --short --branch` and
`git worktree list` show what is already in flight; if another task touches the same files, agree
who owns them before either edits. Stage explicit paths, never `git add -A` or `git add .`.

A commit, a push, a pull request, a merge and a cleanup are separate actions, and authority for one
is not authority for the next. After a verified merge, remove your worktree and local branch, and
the remote branch when that was agreed.

## Commits and pull requests

- Name a branch after the task. A merge commit keeps the name, and `claude/...` or `codex/...` puts
  a tool into the history of a repository people read to learn what the cases say.
- No agent attribution: no `Co-Authored-By` for an agent and no "Generated with" line.
- In a commit message or a PR description, name another project's issue or pull request in words
  ("DataFusion issue 25208"), not as `owner/repo#N` or a link. Either form posts an event in that
  thread, and each one is noise for the people following it; links inside the repository's files
  post nothing.
