"""Reuse a named edge after resizing, cutting, and blending a box.

Run with `solidrecipe serve examples/topology_identity.py`; inspect the JSONL output
in the terminal. Boolean and blend provenance is experimental: the current kernel
conversion does not yet prove correspondence for every possible topology.
"""

import solidrecipe as sr

# An explicit ID gives this feature the same identity when its dimensions change.
stock = sr.Box(12, 30, 10).with_metadata(id="stock")
edge = stock.edge("x_min", "y_min")
resized = sr.Box(12, 30, 14).with_metadata(id="stock")

# The cut leaves the chosen outer edge intact. Resolve the old reference against
# the cut body rather than relying on an edge index or its previous position.
cut = resized - sr.Box(2, 2, 16, origin=(5, 14, -1))
current_edge = cut.resolve(edge["identity"])
rounded = cut.fillet(edge_refs=[edge["identity"]], radius=0.5)
sr.inspect(rounded)

# Use the current measured edge length in a separate feature.
indicator = sr.Box(2, 2, current_edge["length"]).translate(15, 0, 0)
sr.export("stock", rounded)
sr.export("measured_edge_indicator", indicator)
