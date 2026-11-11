# layerctl

`layerctl` manages ordered Git patch layers and materializes them as projection worktrees. This is a standalone extraction of the tool from [abg-OAI/codex](https://github.com/abg-OAI/codex), at commit [`a780a437d8a29c0cb76067d4f540c0a03c301a3d`](https://github.com/abg-OAI/codex/commit/a780a437d8a29c0cb76067d4f540c0a03c301a3d). The module path and imports were changed for this copy, and two tests were adapted for filesystem behavior on macOS. The tool's behavior is otherwise retained. The upstream project is copyright OpenAI and distributed under the [Apache License 2.0](LICENSE).

## Build and test

Go 1.26 and Git are required. From this directory:

```sh
go test ./...
go install ./cmd/layerctl
```

Run the installed `layerctl` from the root or a subdirectory of the repository containing the layer definitions. `go install` places it in `GOBIN`, or `$(go env GOPATH)/bin` when `GOBIN` is unset.

## Repository format and usage

The target repository must contain `upstream.json` with an exact Git tag and commit, plus ordered `layers/NNNN-slug/` directories. The first layer must be `0000-foundation`. Each layer has a `COMMIT_EDITMSG` and may contain a `patch` and an `overlay/` of complete added files. See [the upstream guide](UPSTREAM_GUIDE.md) for the format, commands, conflict handling, and safety rules. Its `go run ./cmd/layerctl` examples assume the original source checkout; use the installed `layerctl` binary instead.

This extraction retains Saffrodex-specific behavior: `upstream advance` accepts Codex `rust-v...` release tags, and `check` requires and validates the upstream `codex-rs/Cargo.lock`. It is not yet a general-purpose layer manager for arbitrary upstream projects. Projection refs and worktrees are local. **`layerctl projection delete` deletes the named projection without checking whether work was captured.**
