# SolidCraft layers

The manifests under `layers/` are the source of truth for the pinned upstream and SolidRecipe's changes. The ordered patches live beside their layer manifest. `0003-edge-split-draft` is disabled and untested; it is not part of the build.

From the SolidRecipe root, run `make prepare-solidcore`. Layerctl fetches the pinned upstream commit and composes `.work/solidcraft/source`; the first composition requires network access. The generated definition repository links to these checked-in layers; it does not contain another copy of the patches. The current layer graph can be inspected with:

```sh
(cd .work/solidcraft/definitions && layerctl graph)
```

If the layer definitions change or the workspace contains edits, preparation stops. Preserve any edits before removing `.work/solidcraft` and composing again. Rebuilding requires sufficient disk space for the source projection.
