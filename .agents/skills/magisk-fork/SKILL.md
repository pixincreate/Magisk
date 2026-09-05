---
name: magisk-fork
description: >-
  Maintain the pixincreate/Magisk fork: rebase the fork's commit stack onto upstream, resolve conflicts by porting fork features, amend CI inside its original commit, build, and force-push.
  Use when working in a Magisk repository on syncing with upstream, rebase conflicts, fork CI failures (update_fork or build workflows), or fork releases.
triggers:
  - "update the fork"
  - "sync with upstream"
  - "rebase magisk"
  - "magisk ci failed"
  - "fork release"
---

# Magisk fork maintenance

## Invariants (never break these)

- The fork is exactly the fork commits rebased on top of `upstream/master`. Never add a commit for a fix that belongs in an existing fork commit; fold it in.
- Zero divergence in upstream-tracked files beyond what the fork commits change. Prefer runtime overrides (`.git/info/attributes`, CI steps) over editing upstream files.
- Never interact with upstream (topjohnwu/Magisk): no PRs, no issues, no comments. Read-only access (fetch, `gh api` reads) is fine.
- Commits are SSH-signed with `--signoff`. Push only `master`, only with `--force-with-lease`, and only when the user asks or has clearly delegated the update.

## Current fork commits (subjects, bottom to top)

1. `refactor(url): point to pixincreate/magisk`
2. `ci(gh-actions): setup ci for auto update` — owns `.github/workflows/update_fork.yml` and all fork changes to `build.yml`
3. `feat(zygisk): add grapheneos support` — native code
4. `docs: add a disclaimer about this project`
5. `feat(zygisk): support GrapheneOS secure app spawning (#34)` — native code
6. `feat(app): hide direct install and uninstall when bootloader is locked (#29)` — `app/apk` Compose (`HomeScreen.kt`, `InstallDialog.kt`, `InstallViewModel.kt`), `app/apk-legacy` XML layouts, `app/core/.../Info.kt`
7. `docs(skill): add fork maintenance skill` — owns `.agents/skills/magisk-fork/`

SHAs churn on every rebase; identify commits by subject.

## Sync workflow

1. `git fetch upstream master`, review `git log --oneline <old-base>..upstream/master` and which touched files overlap fork commits.
2. `git rebase upstream/master`.
3. On conflicts: resolve by feature intent, not by file. When upstream refactors or deletes a module, delete the fork's changes there and port the feature into the surviving module (precedent: apk-ng was deleted; bootloader-lock was rewritten in the `app/apk` Compose module). Follow the resolving-merge-conflicts skill; never abort.
4. Verify: no conflict markers (`git grep '^<<<<<<<'`), guard sites intact (`git grep -n isBootloaderLocked -- app/`), stack is the expected commits on the new base.
5. Build (see below), then `git push origin master --force-with-lease`.

## Amending a fork commit (e.g. CI fixes)

```sh
git commit --signoff --fixup=<commit-sha-by-subject>
GIT_SEQUENCE_EDITOR=: git rebase --autosquash $(git merge-base master upstream/master)
```

Run the global pre-commit inspections and key-watch scan first.

## Known traps

- **futility renormalization:** upstream's `.gitattributes` marks `/tools/keys/futility binary` but the ELF is at `/tools/futility`, so `* text eol=lf` dirties the tree on fresh checkouts and blocks rebases. Fix per clone: `echo '/tools/futility binary' >> .git/info/attributes`. CI writes this itself in `update_fork.yml`.
- **Workflow-file token limit:** the Actions `GITHUB_TOKEN` cannot push any ref whose tree changes `.github/workflows` — upstream tags trip this because upstream's workflow files differ from the fork's. Releases therefore create the fork's own tag via `gh release create --target`; never try to push upstream's tags from CI.
- **Repo URL:** the GitHub repo is `pixincreate/Magisk` (capital M). Update `origin` if git warns about the moved repository.
- **`local.properties`** is not gitignored in this repo; never commit it. Use env vars instead.
- **`.agents/skills/` is upstream's** except `magisk-fork/`, which the fork adds in its own commit (symlinked from `~/.claude/skills/magisk-fork` for Claude Code). Do not add other files there.

## Build (macOS)

```sh
export ANDROID_HOME=~/Library/Android/sdk
export ANDROID_NDK_HOME=$ANDROID_HOME/ndk
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"
./build.py app    # app only; use `all` after native changes
```

First-time setup: `git submodule update --init --recursive` and `./build.py ndk` (installs the Magisk-pinned NDK; the SDK's own NDK will not work). App builds need native output in `native/out` (`./build.py all` once).

## CI overview

- `update_fork.yml`: every 3 days (and on dispatch), rebases master onto upstream and force-pushes; a real conflict fails the run — resolve locally and push.
- `build.yml`: on push, builds signed release + debug APKs, then auto-releases upstream's latest release if the fork lacks it and its commit is in master (prerelease flag mirrors upstream). The `workflow_dispatch` forced path always marks prerelease and derives the tag from `magisk.versionCode`.
