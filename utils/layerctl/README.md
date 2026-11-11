# layerctl

`layerctl` manages ordered Git patch layers and materializes them as projection worktrees. This is a standalone extraction of the tool from [abg-OAI/codex](https://github.com/abg-OAI/codex), at commit [`a780a437d8a29c0cb76067d4f540c0a03c301a3d`](https://github.com/abg-OAI/codex/commit/a780a437d8a29c0cb76067d4f540c0a03c301a3d). This copy changes the module path and adds manifest-defined operations and legacy migration; two upstream tests were also adapted for filesystem behavior on macOS. The upstream project is copyright OpenAI and distributed under the [Apache License 2.0](LICENSE).

## Build and test

Go 1.26 and Git are required. From this directory:

```sh
go test ./...
go install ./cmd/layerctl
```

Run the installed `layerctl` from the root or a subdirectory of the repository containing the layer definitions. `go install` places it in `GOBIN`, or `$(go env GOPATH)/bin` when `GOBIN` is unset.

## Repository format and usage

The target repository has `upstream.json` with an exact Git tag and commit, plus ordered `layers/NNNN-slug/` directories. The first layer must be `0000-foundation`. Each layer describes one generated commit in `layer.toml`:

```toml
[vcs]
commit-msg = "Add a feature\n\nExplain the change.\n"

[[operation]]
[operation.patch]
file = "changes.patch"

[[operation]]
[operation.overlay]
directory = "overlay"
```

Operations run in the order listed and create one commit per layer. The commit message must be nonempty UTF-8 without NUL; its exact bytes, including trailing newlines, are preserved. Patch paths and overlay directories are relative to the layer directory. An overlay holds complete added files, including executable files and symlinks. An overlay cannot silently replace a path that exists at that point in the sequence. Paths may not escape the layer or traverse symlinks. Unknown operations and unreferenced layer files are rejected. See [the upstream guide](UPSTREAM_GUIDE.md) for the original workflow and conflict model; its `go run ./cmd/layerctl` examples assume the original source checkout, so use the installed `layerctl` binary instead.

If an operation conflicts during an upstream advance, resolve that operation in the reported worktree and run `layerctl upstream continue`; remaining operations run before the layer is committed. If a process stops while an operation is running, its outcome may be uncertain; the tool requires `layerctl upstream abort` instead of guessing whether to replay it. Legacy patch and overlay changes continue to apply together. Existing `COMMIT_EDITMSG`/`patch`/`overlay` layers remain readable. Convert a legacy layer with `layerctl layer migrate 0001-example`. `layerctl layer add` and `layerctl layer refresh` generate manifests and may rewrite a layer's operation structure; both verify the generated tree and commit message before replacing a layer.

This extraction retains Saffrodex-specific behavior: `upstream advance` accepts Codex `rust-v...` release tags, and `check` requires and validates the upstream `codex-rs/Cargo.lock`. It is not yet a general-purpose layer manager for arbitrary upstream projects. Projection refs and worktrees are local. **`layerctl projection delete` deletes the named projection without checking whether work was captured.**
