# Layer format

Goal: represent each layer with `layer.toml`, commit message, and ordered patch/overlay operations while preserving legacy layers and providing migration.

Status: active; repository composition re-architecture. [Active plan](active/plan-02%20Repository%20composition.md). Previous manifest work is completed. [Plan](completed/plan-01%20Manifest%20operations.md) · [owners](../OWNERS.md).

## Workers

- /root/manifest: completed; manifest definition and ordered-operation tests reviewed.
- /root/review_design: completed; recovery implementation and tests reviewed.

- /root/model: active, repository model analysis.
- /root/workflow: active, capture and recovery analysis.
