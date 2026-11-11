# Author, manage, and update layers

This walkthrough creates a Git repository of definitions and a separate generated workspace. A definition is the source of truth; a projection is a disposable workspace built from it. Commands below run from the definition repository unless they use `git -C`. Install layerctl as described in the [utility README](../../../README.md), and configure Git's author and committer identity before creating projections.

## Start a definition

Create a new Git repository and a first layer. Set `url` and `commit` to a real source repository and commit you can access. Use an absolute path for a local source. Do not create `upstream.json`, which selects legacy mode.

```sh
mkdir definitions
cd definitions
git init
mkdir -p layers/0001-base
```

Write `layers/0001-base/layer.toml`:

```toml
[vcs]
commit-msg = "Import source\n"

[[operation]]
[operation.git-clone]
url = "https://example.com/project.git"
dir = ""
commit = "0123456789abcdef0123456789abcdef01234567"
```

The commit is a placeholder: replace it and the URL. `dir = ""` places the source at the workspace root; use a relative directory for another source. Add optional `ref = "refs/heads/main"` to require the selected commit to be reachable from that ref, or `depth = 20` to limit imported history. A shallow clone can prevent reachability checks, and overlapping shallow histories are rejected. An unpinned ref can move. Each imported commit becomes a parent of the layer's workspace commit. See the README for clone overlap and submodule limits.

## Create a layer from an edit

Create a projection through the last layer that should precede the new one. The worktree path must not already exist. Edit the workspace, commit the intended result, and capture it as the next layer:

```sh
layerctl projection create edit-new --worktree /tmp/layerctl-edit-new --through 0001-base
# Edit files in /tmp/layerctl-edit-new.
git -C /tmp/layerctl-edit-new add -A
git -C /tmp/layerctl-edit-new commit -m "Add feature"
layerctl layer add 0002-feature --from edit-new
layerctl check
```

Review `layers/0002-feature/` and commit the definitions to their Git repository. Capture uses the committed tree and final commit message; commit all intended changes first. It refuses to capture merge commits: declare imported sources with `git-clone` instead. You can also author a `layer.toml` and its patch or overlay directly. Paths for those inputs are relative to the layer directory, and operations run in manifest order.

## Update a layer

Create a fresh projection through the layer to update, edit it, and commit the result. The worktree must be clean when refreshing:

```sh
layerctl projection create edit-existing --worktree /tmp/layerctl-edit-existing --through 0002-feature
# Edit files in /tmp/layerctl-edit-existing.
git -C /tmp/layerctl-edit-existing add -A
git -C /tmp/layerctl-edit-existing commit -m "Improve feature"
layerctl layer refresh 0002-feature --from edit-existing
layerctl check
```

Refresh preserves the existing operations and adds a patch for the committed edits. It replays the candidate and checks its tree, message, and imported parents. It currently refuses manifests containing comments, so keep manifests intended for refresh comment-free. Inspect the resulting diff and commit the definition changes. Refresh and check replay scripts, so inspect their external effects before running them.

To update a cloned source, change its pinned `commit` and, if used, its `ref`, then rebuild and run `layerctl check`. Later patches may conflict with the new source. `projection continue NAME` resumes a projection after resolving its reported conflict, but that resolution is not automatically saved into the definition. Update the affected patch or other operation explicitly and rebuild to verify it; keep the old pin and definitions in Git until the new result is verified.

## Manage layers and projections

- Set `[layer] enabled = false` to skip a layer. Use `depends-on = ["0001-base"]` under `[layer]` to declare an earlier enabled prerequisite. Dependencies do not reorder layers.
- Run `layerctl graph` for DOT or `layerctl graph --format mermaid` for Mermaid. Dashed edges show order; solid edges show declared dependencies.
- Run `layerctl projection list` to find workspaces and `layerctl projection path NAME` to print one. A failed `check` can leave a projection for inspection.
- After a conflict, resolve the indicated files and run `layerctl projection continue NAME`. If an operation was interrupted, inspect the workspace before recreating it. Unlock a stale lock only after verifying no layerctl process uses it: `layerctl projection unlock NAME`.
- Once needed work is captured, `layerctl projection delete NAME` removes that owned workspace and any uncaptured changes.

A script operation runs an executable with the workspace as its current directory. It receives `LAYERCTL_WORKTREE_DIR`, `LAYERCTL_DEFINITION_DIR`, `LAYERCTL_LAYER_DIR`, `LAYERCTL_LAYER_ID`, and `LAYERCTL_OPERATION_INDEX`. Scripts can change resources outside the workspace, and projection creation, refresh verification, and checks can run them more than once. Inspect their effects before running them.
