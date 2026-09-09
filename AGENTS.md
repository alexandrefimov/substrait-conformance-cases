# Repository agent instructions

## Parallel worktree contract

This repository is worked on by multiple agents at the same time. Any task that
changes code, documentation, fixtures, generated files, or saved results must
use its own Git branch and registered worktree.

Before editing, run:

```sh
git status --short --branch
git worktree list --porcelain
git branch --show-current
```

- While parallel work is active, treat the primary checkout (the first entry in
  `git worktree list`) as coordination-only. Do not edit or run generators there.
- Use one uniquely named branch and one dedicated worktree per task. Use the
  operator-provided worktree root when one exists; otherwise create the
  worktree as a sibling of the primary checkout, never inside it:

  ```sh
  git worktree add <worktree-path> -b <topic>-<date> <base-sha>
  ```

  Name the branch after the task, not after the tool that runs it. A merge commit
  keeps the branch name forever, so `codex/...` or `claude/...` puts the tool in
  the permanent history of a repository people read to learn what the cases say.
  Which agent did the work belongs in the run, not in `git log`.

- Use the base named by the task. If none is named, resolve `origin/main`, record
  its exact SHA, and say whether the remote-tracking ref was refreshed before
  creating the worktree. Do not use whichever branch happens to be checked out.
- At the first status update, identify the branch, worktree basename, base SHA,
  and intended file scope. A worktree belongs to that task until its owner hands
  it off or removes it.
- Treat every other registered worktree and its dirty files, branch, stashes,
  locks, and processes as another agent's work. Do not edit in it or reset,
  stash, clean, switch, remove, prune, kill, or force-delete its state.
- If another active task overlaps the intended files or generated outputs, stop
  before editing and coordinate ownership. Do not resolve overlap by copying
  changes between dirty worktrees.
- Run generators, formatters, builds, and tests that write files only inside the
  task worktree. Keep temporary outputs out of tracked source directories.

## Repository-specific contracts

- Treat every tracked file as public. Do not commit machine-local absolute
  paths, credentials, private endpoints, raw local logs, or tool caches.
  `probe/selfcheck.sh` rejects absolute paths and untranslated text, but it does
  not replace review for other private material.
- Follow the artifact ownership documented in [README.md](README.md#what-is-here)
  and [probe/README.md](probe/README.md#what-a-run-needs-and-what-fails-it).
  Change the owning source or generator first, then regenerate its outputs. Do
  not independently hand-edit `derived-schema/`,
  `derived-schema-virtual-tables/`, `expected.json`, `results/MATRIX.txt`,
  `docs/matrix*.svg`, or `docs/index.html`.
- `results/<NAME>.txt` records a measurement against `probe/versions.env`.
  Update a pin together with the reproduced column and its provenance. A
  `LATEST=1` drift run is an observation, not a replacement for the pinned
  saved baseline. Preserve the chronological provenance in `results/DRIFT.txt`.
- `probe/reverify.sh` is report-only by default. Use `UPDATE_CORPUS=1` or
  `UPDATE_COLUMNS=1` only when the task explicitly owns those outputs; inspect
  the complete generated diff afterward. Never use an update flag merely to
  make a failing check pass.

## Integration and cleanup

- Keep changes task-scoped and stage explicit paths; do not use `git add .` or
  `git add -A` in a shared repository.
- Before handoff, inspect `git status --short --branch` and the complete diff
  from the recorded base. If the integration branch advanced, update the task
  branch in its own worktree and rerun the relevant checks.
- A local commit, push, pull request, merge, and cleanup are separate actions.
  Do not infer authorization for a later action from an earlier one.
- After a verified integration, clean up the owned task worktree and its local
  branch; when remote cleanup was approved, also delete its non-protected remote
  task branch. Do not retain integrated work merely as evidence or force cleanup
  when its ownership or state is uncertain.
- For a squash merge, verify that the merged tree or patch is equivalent before
  deleting the source branch; retain and report it when equivalence is unclear.

## Validation

The fast repository gates are:

```sh
bash probe/selfcheck.sh
bash probe/selfcheck-negative.sh
git diff --check
```

Passing these gates establishes internal consistency only; it does not rerun a
participant or prove that the expectations match the Substrait specification.
For changes to a participant runner, setup, normalization, or saved column, run
`bash probe/replay_column.sh <NAME>` against the pinned version. Use the focused
runtime probes described in `probe/README.md` when their surface changes.
`probe/reverify.sh` is the broad consumer sweep and needs external toolchains;
do not present a partial or skipped sweep as full validation.
