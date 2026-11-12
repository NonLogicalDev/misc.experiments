"""Find one class of construction-based explanation for a selected edge set.

This experiment only proposes common-face/neighbor-face patterns; it is not a
complete synthesis algorithm. It refuses a face without exactly one reported
origin rather than inventing a source. Results describe one rebuilt snapshot.
"""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
helpers = runpy.run_path(str(ROOT / "docs/plans/_owner/artifacts/test-construction-queries.py"))


def face_origin(face):
    ids = face.get("identities", [])
    if len(ids) != 1 or face.get("origin_status") == "generated or untracked" or face.get("merged"):
        return None
    return ids[0]


def mine(report, selected):
    edges = {e["index"]: e for e in report["edges"]}
    faces = {f["index"]: f for f in report["faces"]}
    if not selected or not selected <= edges.keys():
        raise ValueError("selection must contain existing edge indices")
    common = set.intersection(*(set(edges[i]["adjacent_faces"]) for i in selected))
    candidates = []
    for common_face in common:
        neighbor_faces = {f for i in selected for f in edges[i]["adjacent_faces"] if f != common_face}
        center = face_origin(faces[common_face])
        neighbors = [face_origin(faces[f]) for f in sorted(neighbor_faces)]
        if center is None or not neighbors or any(i is None for i in neighbors):
            continue
        # Resolve the source IDs across the entire body. A source that occurs
        # on several faces is a set, not permission to pick the first.
        def matches(f, source):
            return source in f.get("identities", [])
        center_set = {i for i, f in faces.items() if matches(f, center)}
        neighbor_set = {i for i, f in faces.items() if any(matches(f, src) for src in neighbors)}
        result = helpers["between"](report, center_set, neighbor_set)
        if result == selected:
            candidates.append({"center_source": center, "neighbor_sources": neighbors,
                               "matches_snapshot_edges": sorted(result)})
    return candidates


def main():
    ns = helpers["instrument"]()
    ns["adapter"](side="left", slot_height=4.6)
    shape = next(shape for stage, shape in ns["snapshots"] if stage == "final")
    report = helpers["inspect"](shape)
    for selected in ({6, 9, 16}, {35, 36, 43}):
        candidates = mine(report, selected)
        print(json.dumps({"selection": sorted(selected), "candidates": candidates,
                          "caveat": "one snapshot; untracked provenance and other explanations remain"}))
        if selected == {6, 9, 16}:
            assert candidates, "expected at least one common-face candidate"
        else:
            assert not candidates, "three corner edges need a different pattern class"


if __name__ == "__main__":
    main()
