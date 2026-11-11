# Layer format

Goal: represent each layer with `layer.toml`, commit message, and ordered patch/overlay operations while preserving legacy layers and providing migration.

Status: active. Next: implement manifest parsing, execution, capture, and migration; verify integration. [Plan](active/plan-01%20Manifest%20operations.md) · [owners](../OWNERS.md).

## Workers

- /root/manifest: active; implement ordered-operation integration tests.
- /root/review_design: active; implement resumable operation recovery.
