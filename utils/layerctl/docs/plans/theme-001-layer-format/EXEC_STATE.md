# Layer format

Goal: represent each layer with `layer.toml`, commit message, and ordered patch/overlay operations while preserving legacy layers and providing migration.

Status: implementation and walkthrough verified and checkpointed; Deluge integration is in progress. [Active plan](active/plan-02%20Repository%20composition.md). Previous manifest work is completed. [Plan](completed/plan-01%20Manifest%20operations.md) · [owners](../OWNERS.md).

## Workers

- /root/manifest: completed; manifest definition and ordered-operation tests reviewed.
- /root/review_design: completed; recovery implementation and tests reviewed.

- /root/model: completed, git-clone manifest parsing.
- /root/workflow: completed, clone materialization and history-depth behavior.

- /root/projection: completed, isolated composition projections and merge parents.

- /root/model: completed independent review of multiline message encoding.

- /root/projection: completed graph and Deluge dependency review.

- /root/model and /root/projection: completed dependency analysis across the Deluge stack.

- /root/model: completed clone preparation manifest, refresh and recovery metadata. /root/projection: completed clone preparation Git plumbing.

Active: [pre-checkout script and optional clone directory](active/plan-03%20Pre-checkout%20script.md); /root/model, /root/projection, and /root/integration_review are assigned in the plan.
