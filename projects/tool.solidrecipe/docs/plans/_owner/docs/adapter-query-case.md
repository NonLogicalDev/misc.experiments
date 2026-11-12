# Adapter query case: three selected edges

This case tests the proposed [topology query algebra](topology-query-algebra.md) against the exploratory [cooler adapter](../../../../examples/cooler_adapter.py). The adapter is a comparison prototype, not a verified manufacturing design. The query examples below are design pseudocode; SolidRecipe does not implement this query API.

## Selected snapshot

The selected preview had session `solidrecipe-preview-S1bnMv`, revision 1, output `mounts.adapter`, side `left`, slot height 4.6 mm, entry fillets enabled and underside chamfer enabled. The session's read-only inspection data was still available during the investigation. SHA-256 values recomputed from its inspection records using the viewer's JavaScript canonical JSON serialization exactly matched all three values supplied with the selection:

| Snapshot edge | Inspection record SHA-256 | Endpoints, mm | Length, mm | Adjacent snapshot faces |
| --- | --- | --- | --- | --- |
| 36 | `76d31e1598f232d7dd37715279d513489e6732133168bd247cbafe3d80835e62` | (3, 10.85, 8.5) to (12.5, 10.85, 8.5) | 9.5 | 10, 13 |
| 43 | `4ab50fd831b1d3c51cd071ff8adb1453ae4f79c474d64ae56bb173602b46dc64` | (3, 0, 8.5) to (3, 10.85, 8.5) | 10.85 | 12, 13 |
| 35 | `50dca72e80a1f17cdb27e401b47dbd4e1b5efeff1914ba0927a5febed0822f88` | (3, 10.85, 8.5) to (3, 10.85, 12) | 3.5 | 10, 12 |

The three selected straight edges geometrically meet at the corner `(3, 10.85, 8.5)`. Faces 10, 12 and 13 lie respectively on the planes `y = 10.85`, `x = 3` and `z = 8.5`. Indices and inspection hashes identify records in this preview; neither is a persistent identity. Hash equality here verifies the reported records match the supplied selection, not that they retain identity after a rebuild.

## A composable description

For the model as currently authored, the corner can be described using three datums derived from the strip's inner x coordinate, the raised spine's start along y and the base top z. The following is mathematical pseudocode, not executable SolidRecipe Python:

```text
corner = intersection(
    plane(x = strip_inner_x(side)),
    plane(y = raised_start(side)),
    plane(z = base_top),
)

selected = edges(adapter).where(
    exists vertex v in vertices(adapter):
        incident(edge, v) and coincides(v, corner)
)
```

The present example defines the strip width and base top with numeric literals rather than exposing these names as parameters. For this model, the values used are x=3 and y=10.85 on the left, x=9.5 and y=10.8 on the right, and z=8.5 on both sides. Deriving datums from shared authored dimensions would keep the meaning clearer if those dimensions became parameters. The query needs explicit coordinate frame, tolerance, body and revision; its treatment of missing or multiple coincident vertices must be specified. It describes the current set at the authored corner, not a promise that a particular edge survives every edit.

## Checked evidence and limits

The inspection report supplies edge endpoints but this experiment did not establish whether coincident endpoints share an actual B-rep vertex. A separate one-off comparison tested whether either endpoint lies within `0.000001 mm` of the calculated corner. It scanned **every** edge in each independently evaluated snapshot, with both blend options enabled:

| Side | Slot height, mm | Corner, mm | Edges scanned | Matching snapshot indices |
| --- | --- | --- | --- | --- |
| Left | 4.5 | (3, 10.85, 8.5) | 67 | 35, 36, 43 |
| Left | 4.7 | (3, 10.85, 8.5) | 67 | 35, 36, 43 |
| Right | 4.5 | (9.5, 10.8, 8.5) | 67 | 22, 23, 30 |
| Right | 4.7 | (9.5, 10.8, 8.5) | 67 | 22, 23, 30 |

The original selected 4.6 mm snapshot was also scanned: its only matching endpoints belonged to edges 35, 36 and 43. These comparisons show no extra geometric endpoint matches in the five examined snapshots. They do not execute the proposed predicate or prove topological incidence, behavior under other edits, or geometric coverage between endpoints. An edge that passes through the point without ending there would not match this criterion. The desired topological query needs an actual vertex-to-edge relationship; coordinate coincidence alone must not silently substitute for it.

A later [B-rep vertex probe](../artifacts/verify-adapter-vertices.py) inspected independently rebuilt records, rather than only their endpoint coordinates. Each of the five configurations has exactly one vertex at the inspected corner and three edges incident to that vertex. For the left 4.6 mm rebuild the incident indices were `35`, `36`, and `43`. The original user selection was from a different preview snapshot, so this is a reproduced topological result, not a retroactive inspection of that exact B-rep record. The probe uses existing Rust libraries and does not itself verify their source freshness. See the [construction query study](construction-query-study.md) for the construction-first formulation and additional counterexamples.

A second one-off check on the original selected snapshot used face relationships instead: select edges adjacent to faces on two different planes from `x=3`, `y=10.85`, and `z=8.5`. The face sets were `[12]`, `[10]` and `[7, 13]`; scanning the inspected edges produced exactly `[35, 36, 43]`. This uses composable face predicates and incidence rather than edge indices, but it can select distant edges where the same planes meet or extra edges after a split. It was checked only on the original snapshot and is not a general proof that the descriptions remain equivalent.
