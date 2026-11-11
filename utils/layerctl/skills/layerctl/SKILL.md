---
name: layerctl
description: Author, compose, inspect, capture, or update Git-backed layerctl layers and projections, including git-clone, patches, scripts, and merge ancestry.
---

# layerctl

Use this skill when working with a layerctl definition repository or converting a Git history into layers. Read the project's [README](../../README.md) for the supported schema and current limits. A definition repository is a Git repository containing ordered `layers/NNNN-slug/layer.toml` files; run `layerctl` from that repository or a subdirectory. Build or install the utility from its source directory with `go build ./cmd/layerctl` or `go install ./cmd/layerctl`.

## Author layers

A layer creates one commit in the composed workspace. Operations run in manifest order. For example:

```toml
[layer]
enabled = true
depends-on = ["0001-base"]

[vcs]
commit-msg = "Compose sources\n"
co-authors = ["Example Contributor <contributor@example.com>"]

[[operation]]
[operation.git-clone]
url = "https://example.com/source.git"
dir = ""
ref = "refs/heads/main"
commit = "0123456789abcdef0123456789abcdef01234567"

[[operation]]
[operation.patch]
file = "changes.patch"

[[operation]]
[operation.overlay]
directory = "overlay"

[[operation]]
[operation.script]
file = "scripts/configure.sh"
args = ["example"]
```

Replace the example URL and commit with an accessible source and revision. `ref`, `commit`, `depth`, `depends-on`, and co-authors are optional. Paths for patches, overlays, and scripts are relative to the layer directory. Clone destinations are relative to the workspace; `dir = ""` means its root. A clone does not overwrite existing files. Imported source commits become additional parents of the layer commit; the previous workspace commit is the first parent when present. `ref` and `commit` together require the commit to be reachable from the ref. Pin commits for reproducibility; a depth limit can prevent ancestry verification. Overlapping source histories are rejected when either is shallow, and submodules are not supported.

Layers are enabled by default. Disabled layers are skipped; an enabled layer's dependencies must exist earlier in the numbered order and be enabled. `vcs.co-authors` adds standard `Co-authored-by` trailers. Without co-authors, the exact commit message is retained.

A script-bearing layer can include supporting files accessible through `LAYERCTL_LAYER_DIR`. A script is a trusted executable run directly with the workspace as its current directory. It receives `LAYERCTL_WORKTREE_DIR`, `LAYERCTL_DEFINITION_DIR`, `LAYERCTL_LAYER_DIR`, `LAYERCTL_LAYER_ID`, and one-based `LAYERCTL_OPERATION_INDEX`. On success, tracked changes and non-ignored new files are staged. Scripts can access and change resources outside the workspace. Inspect them and establish permission for their effects before running a projection or `check`.

## Work on layers

For a complete example from a new definition through adding, updating, inspecting, and cleaning up layers, read the [authoring and management walkthrough](references/authoring.md).

From the definition repository, choose a new, nonexistent workspace path and create a projection through the predecessor:

```sh
layerctl projection create edit-feature --worktree /path/to/new-workspace --through 0001-base
# Edit and commit the desired change in /path/to/new-workspace.
layerctl layer add 0002-feature --from edit-feature
layerctl check
layerctl graph                    # DOT on stdout
layerctl graph --format mermaid   # Mermaid on stdout
```

To update a layer, create a projection through that layer, commit the desired changes in its workspace, then run `layerctl layer refresh 0002-feature --from edit-feature`. Refresh validates the candidate against the accepted tree and message. For a manifest layer, it preserves the original operations and source parents and appends a patch; it currently refuses manifests containing comments rather than discarding them. Verification replays scripts, which can repeat their external side effects. A source ref that moved can make replay fail; use an exact commit when the original ancestry must stay fixed.

`layerctl check` rebuilds the definition and executes its scripts. `layerctl projection list` shows projections and `layerctl projection path NAME` finds a workspace. A reported conflict leaves an owned workspace: resolve the indicated operation there and run `layerctl projection continue NAME`. If execution was interrupted while an operation was running, layerctl refuses to guess whether it completed; inspect the workspace, then delete and recreate the projection if appropriate. Resolving a projection conflict does not save the resolution back to the layer definition; update the affected operation and rebuild to verify it. If a lock is stale, verify no layerctl process is using the projection before `layerctl projection unlock NAME`.

`layerctl projection delete NAME` removes the owned workspace, including uncaptured work. Do not run it until the user has authorized deletion or the workspace is disposable and its needed work is captured. Do not publish or push a projection unless asked.

## Legacy definitions

An existing `upstream.json` selects the original single-repository compatibility mode. `layerctl layer migrate ID` converts a legacy `COMMIT_EDITMSG`/`patch`/`overlay` layer into a manifest. That file has no clone URL, so converting the base to `git-clone` requires the correct source URL and revision; do not guess them. Preserve the original definitions until the converted projection has been checked against the accepted source tree and history.
