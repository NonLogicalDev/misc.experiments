# Adapter B-rep inspection evidence

These observations are from `examples/cooler_adapter.py`, an exploratory comparison model rather than a verified manufacturing design. They are inspection results from the existing `target/debug/solidrecipe` executable, not executions of the proposed query language. All reported indices belong only to the named snapshot and cannot establish identity across edits.

## Reproduction

From the project root, run `.venv/bin/python docs/plans/_owner/artifacts/inspect-adapter-snapshots.py`. The script instruments the model source in memory at two unique points, builds the original graphs with slot entry fillets enabled, and invokes `inspect-graph` using the existing debug binary. It emits complete inspection results as JSON to stdout. It performs no Rust build and creates no persistent output files. The results depend on the model source and binary version; verify that the binary corresponds to the intended checkout before using them as evidence for a different revision.

The eight inspected cases are left and right sides at slot heights 4.5 mm and 4.7 mm, each before the slot-entry fillets and before the underside chamfer. The latter stage is after the entry fillets, setback cut and both screw-hole cuts. Both stages use the model's ordinary operations and coordinates.

## Checked subsets

The following values were extracted by checking the returned edge curve kind, endpoints, lengths, radii, and adjacent-face indices, using 0.000001 mm numeric comparisons. The extraction is a one-off inspection of current data; its predicates are not an implementation of the proposed algebra.

| Side | Stage | Result | Snapshot edge indices |
| --- | --- | --- | --- |
| Left | Before entry fillets | Two vertical slot entrance edges at x=0, y=8 and y=54, length equal to slot height | 18, 16 |
| Right | Before entry fillets | Two vertical slot entrance edges at x=12.5, y=8 and y=54, length equal to slot height | 25, 23 |
| Left | Before underside chamfer | One 71 mm straight setback edge at x=1, z=0 | 46 |
| Right | Before underside chamfer | One 71 mm straight setback edge at x=11.5, z=0 | 47 |
| Left | Before underside chamfer | All four radius 1.75 mm circular screw-hole rims | 30, 45, 49, 50 |
| Right | Before underside chamfer | All four radius 1.75 mm circular screw-hole rims | 21, 25, 50, 51 |

Each slot entry edge runs from z=7.4 to z=7.4 minus the selected slot height, with orientation depending on the snapshot. Before the entry fillets every case has 17 faces and 42 edges; before the chamfer every case has 24 faces and 64 edges. The two hole rims at z=8.5 and two at z=0 each have length approximately 10.9956 mm; their y coordinates are 5.5 and 65.5. The hole x coordinate is 9.225527 for left and 3.725527 for right.

## A parameter-change counterexample

Suppose an author tries to select the two entry edges using only “straight, vertical, on the inside x-plane, and length equal to the slot height.” At slot height 4.7 this matches the intended two edges in both sides. At 4.5 it also matches a 4.5 mm vertical edge at the raised spine: left edge 13 at y=60.65, z=8.5–13, and right edge 21 at y=60.7, z=8.5–13. Thus a predicate that happens to work at 4.7 is not sufficient across the tested parameters. The observed entry edge coordinates or a valid relationship to the slot feature are possible additional conditions; the current inspection does not certify slot-feature lineage.
