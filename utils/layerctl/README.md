# layerctl

`layerctl` manages ordered Git patch layers and materializes them as projection worktrees. This is a standalone extraction of the tool from [abg-OAI/codex](https://github.com/abg-OAI/codex), at commit [`a780a437d8a29c0cb76067d4f540c0a03c301a3d`](https://github.com/abg-OAI/codex/commit/a780a437d8a29c0cb76067d4f540c0a03c301a3d). This copy changes the module path and adds manifest-defined operations and legacy migration; two upstream tests were also adapted for filesystem behavior on macOS. The upstream project is copyright OpenAI and distributed under the [Apache License 2.0](LICENSE).

## Build and test

Go 1.26 and Git are required. From this directory:

```sh
go test ./...
go install ./cmd/layerctl
```

Run the installed `layerctl` from the root or a subdirectory of the repository containing the layer definitions. `go install` places it in `GOBIN`, or `$(go env GOPATH)/bin` when `GOBIN` is unset.

## Composition

A definition repository contains ordered `layers/NNNN-slug/layer.toml` files. Each layer runs its operations in order and creates one commit in the composed workspace. `git-clone` imports a source tree and makes its selected source commit a parent of that layer's commit; the preceding workspace commit is the first parent when present. Source Git metadata is not copied into the workspace tree.

```toml
[layer]
enabled = true
# depends-on = ["0001-base"] # optional; each dependency must be earlier and enabled

[vcs]
commit-msg = """
Compose tools
"""
co-authors = ["Example Contributor <contributor@example.com>"] # optional

[[operation]]
[operation.git-clone]
url = "https://example.com/project.git"
dir = "" # empty means the workspace root
ref = "refs/heads/main" # optional branch, tag, or other ref
# commit = "0123456789abcdef0123456789abcdef01234567" # optional exact commit
# depth = 20 # optional positive history depth

[[operation]]
[operation.git-clone]
url = "https://example.com/other.git"
dir = "vendor/other"
ref = "refs/tags/v1.0.0"

[[operation]]
[operation.patch]
file = "changes.patch"

[[operation]]
[operation.script]
file = "scripts/configure.sh"
args = ["example"]
```

When both `ref` and `commit` are set, the commit must be reachable from the ref. A shallow depth can prevent this verification. Pin `commit` for reproducible results; otherwise the selected ref or default HEAD can move. Git shallow boundaries apply to the entire workspace object database, so overlapping source histories are rejected when either import is shallow. Clone imports refuse to overwrite existing files or index entries, and sources containing Git submodules are not supported. Paths must be workspace-relative and may not traverse symlinks or Git metadata.

```sh
layerctl graph                    # Graphviz DOT on stdout
layerctl graph --format mermaid   # Mermaid source on stdout
layerctl projection create demo --worktree /path/to/new-workspace
layerctl projection list
layerctl projection path demo
# After resolving a reported conflict:
layerctl projection continue demo
layerctl check
layerctl projection delete demo
```

After a conflict, resolve the affected files in the reported workspace and run `projection continue`; remaining operations run before the commit. If a process stops during an operation, layerctl refuses to guess whether it completed; delete the owned projection and recreate it. If a process terminates while holding a projection lock, verify that no layerctl command is still operating on that projection before running `layerctl projection unlock NAME`. Refreshing a manifest layer preserves the original operations and appends a patch, but currently refuses manifests with comments rather than discarding them. Refresh verification replays its operations, including scripts.

The graph includes all layers, including disabled ones, and edges show their effective dependencies. A layer that omits `depends-on` depends on the preceding enabled layer; an explicit list replaces that default, and `depends-on = []` declares no dependencies. Layers still execute in numbered order.

A script-bearing layer may include supporting files, which scripts can read through `LAYERCTL_LAYER_DIR`. A script operation executes the layer-relative executable directly, with the workspace as its working directory. It receives `LAYERCTL_WORKTREE_DIR`, `LAYERCTL_DEFINITION_DIR`, `LAYERCTL_LAYER_DIR`, `LAYERCTL_LAYER_ID`, and the one-based `LAYERCTL_OPERATION_INDEX`. A successful script stages tracked changes and non-ignored new files; a nonzero exit stops the projection. Scripts are trusted programs and can have side effects outside the workspace. `layerctl check` also runs them.

The workspace path must not already exist. Without `--worktree`, layerctl creates a workspace in its local Git state directory. `projection delete` removes the owned workspace, including uncaptured changes. Patch files and overlay directories are relative to the layer directory. An overlay adds files without silently replacing an existing path. Commit messages must be nonempty UTF-8 without NUL. Without co-authors their exact bytes, including trailing newlines, are preserved; configured co-authors are added as standard `Co-authored-by` trailers.

## Legacy definitions

Definitions with `upstream.json` use the original single-repository format and its Codex-specific advance workflow. They remain readable; see [the upstream guide](UPSTREAM_GUIDE.md). `upstream.json` records a tag and commit but no source URL, so conversion to `git-clone` requires choosing the source URL rather than guessing it. Legacy `COMMIT_EDITMSG`/`patch`/`overlay` layers can be converted individually with `layerctl layer migrate <layer-id>`.
