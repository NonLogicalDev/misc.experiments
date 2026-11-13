# layerctl owner guidance

Read [MEMORY.md](MEMORY.md) first and verify authority in [OWNERS.md](OWNERS.md). Keep the layer-format plan and execution state current before changing implementation. The active request makes repository composition and git-clone operations the model; remove the legacy upstream and layer formats as directed while preserving current composition, conflict recovery, and user data. Test the actual CLI, capture, and replay. Keep modifications and license attribution traceable. Do not publish without a new user request.

Name related source files from least specific to most specific, such as `git_clone_pre_checkout_test.go`, so related files sort together. Keep operation implementations in `internal/operations/`.
