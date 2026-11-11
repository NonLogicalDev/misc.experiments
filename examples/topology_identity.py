"""Inspect a named box and reuse an edge identity after changing its dimensions.

Run with `solidrecipe serve examples/topology_identity.py`; inspect the JSONL output
in the terminal. Boolean operations and blends do not yet carry these identities.
"""

import solidrecipe as sr

# An explicit ID gives this feature the same identity when its dimensions change.
stock = sr.Box(12, 30, 10).with_metadata(id="stock")
edge = stock.edge("x_min", "y_min")
resized = sr.Box(12, 30, 14).with_metadata(id="stock")

# Resolve the old reference against the rebuilt feature rather than relying on
# an edge index or its previous position. This emits the current B-rep as JSONL.
current_edge = resized.resolve(edge["identity"])
sr.inspect(resized)

# Use the measured edge length in a separate feature. This example intentionally
# does not imply that references survive a Boolean operation or a blend yet.
indicator = sr.Box(2, 2, current_edge["length"]).translate(15, 0, 0)
sr.export("stock", resized)
sr.export("measured_edge_indicator", indicator)
