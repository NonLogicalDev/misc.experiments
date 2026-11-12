"""Use an edge reference after a cut to measure and round the same edge.

Run `solidrecipe serve examples/topology_identity.py` and choose an output in
the viewer. Change `height` and rebuild to see the edge measurement update.
Topology tracking is experimental; kernel provenance is not yet proven complete
for every operation. Do not treat this example as a manufacturing model.
"""

import solidrecipe as sr

height = 14

# Name the box so its faces and edges can be referenced across operations.
# Each face has four edges; the lowest-X and lowest-Y faces share one edge.
blank = sr.Box(12, 30, height).with_metadata(id="blank")
edge = blank.edge_between_faces("x_min", "y_min")

# Cut a hole, then find the same edge on the resulting shape. Resolution fails
# if the edge is missing, split into multiple descendants, merged, or otherwise
# ambiguous; it never picks a nearby edge as a substitute.
with_hole = blank - sr.Box(2, 2, height + 2, origin=(5, 14, -1))
edge_length = with_hole.resolve(edge)["length"]

# The reference also selects the edge to round. The separate bar makes the
# current edge length visible: changing height changes the bar's height too.
bracket = with_hole.fillet(edge_refs=[edge], radius=0.5)
length_bar = sr.Box(2, 2, edge_length).translate(15, 0, 0)

sr.export("bracket", bracket)
sr.export("edge_length_bar", length_bar)
