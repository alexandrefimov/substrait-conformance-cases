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
  git worktree add <worktree-path> -b <agent>/<short-task>-<date> <base-sha>
  ```

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

## Integration and cleanup

- Keep changes task-scoped and stage explicit paths; do not use `git add .` or
  `git add -A` in a shared repository.
- Before handoff, inspect `git status --short --branch` and the complete diff
  from the recorded base. If the integration branch advanced, update the task
  branch in its own worktree and rerun the relevant checks.
- A local commit, push, pull request, merge, and cleanup are separate actions.
  Do not infer authorization for a later action from an earlier one.
- Remove only the task worktree you own, and only after its work is integrated
  or explicitly abandoned, the worktree is clean, and no process uses it. Never
  force-remove a worktree or force-delete its branch as routine cleanup.

## Validation

The fast repository gates are:

```sh
bash probe/selfcheck.sh
bash probe/selfcheck-negative.sh
git diff --check
```

Run focused participant or runtime probes when the changed surface requires
them. `probe/reverify.sh` is the broad consumer sweep and needs external
toolchains; do not present a partial or skipped sweep as full validation.
