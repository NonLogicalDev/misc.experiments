# Layer format

Goal: represent each layer with `layer.toml`, commit message, and ordered patch/overlay operations while preserving legacy layers and providing migration.

Status: active. Next: implement manifest parsing, execution, capture, and migration; verify integration. [Plan](active/plan-01%20Manifest%20operations.md) · [owners](../OWNERS.md).

## Workers

- /root/manifest: active; implement manifest parser and definition tests.
- /root/review_design: active; review execution and migration design.
