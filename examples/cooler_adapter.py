"""Exploratory NH-L12S adapter reconstruction; do not manufacture this model.

Use the viewer parameters to inspect either bracket and the three slot variants.
The source of truth remains homelab-cooler-adapters' slot-height-variants-label-08.
The 2 mm slot-entry fillets and 1 mm full-length underside chamfer use the kernel.
The 0.5 mm ledge fillet, outer rounds and labels remain unmodeled; this model
does not establish fit or safe mounting pressure.
"""

from typing import Annotated

import solidrecipe as sr

# The design is a reusable module as well as a viewer-selectable output.
# Function defaults and annotations drive the viewer controls.
with sr.module("mounts"):

    @sr.exportf
    def adapter(
        side: Annotated[
            str, sr.Param(description="Bracket half", options=["left", "right"])
        ] = "left",
        slot_height: Annotated[
            float,
            sr.Param(
                description="Cooler lip slot height",
                unit="mm",
                minimum=4.5,
                maximum=4.7,
                step=0.1,
                options=[4.5, 4.6, 4.7],
            ),
        ] = 4.6,
        entry_fillets: Annotated[
            bool, sr.Param(description="2 mm slot-entry fillets")
        ] = True,
        underside_chamfer: Annotated[
            bool, sr.Param(description="1 mm underside chamfer")
        ] = True,
    ):
        """Build one approximate bracket in mm, with its underside on the XY plane."""
        if side not in ("left", "right"):
            raise ValueError("side must be 'left' or 'right'")
        if not 4.5 <= slot_height <= 4.7:
            raise ValueError("slot height must be between 4.5 and 4.7 mm")

        # The original SCAD defines both parts from the inside edge and then mirrors
        # the right half. Mirroring box coordinates keeps the open slot on that edge.
        def block(x, y, z, width, length, height):
            if side == "right":
                x = 12.5 - x - width
            return sr.Box(width, length, height, origin=(x, y, z))

        raised_start = 10.85 if side == "left" else 10.8
        raised_length = 49.8 if side == "left" else 49.9
        shape = block(0, 0, 0, 12.5, 71, 8.5)
        shape += block(0, raised_start, 8.5, 12.5, raised_length, 4.5)
        # Approximate the thin strip before the raised spine; the round end is omitted.
        shape += block(0, 0, 8.5, 3, raised_start, 3.5)

        # Keep the groove roof fixed at z=7.4 while adjusting its floor, as in SCAD.
        shape -= block(-1, 8, 7.4 - slot_height, 10, 46, slot_height)
        if entry_fillets:
            # Round the vertical entrance edges before cutting the lower setback;
            # afterward their adjacent face is too narrow for the kernel's 2 mm round.
            inner_x = 0 if side == "left" else 12.5
            middle_z = 7.4 - slot_height / 2
            shape = shape.fillet(
                edge_points=[[inner_x, 8, middle_z], [inner_x, 54, middle_z]], radius=2
            )
        # The lower edge is set back by 1 mm for the full 71 mm length.
        shape -= block(-0.1, -0.1, -0.1, 1.1, 71.2, 7.5 - slot_height)

        # The two source brackets use different recovered X positions. Screw axes
        # are 60 mm apart along Y; holes are nominally 3.5 mm in diameter.
        hole_x = 9.225527 if side == "left" else 12.5 - (28.524473 - 19.75)
        for y in (5.5, 65.5):
            shape -= sr.Cylinder(1.75, 9, origin=(hole_x, y, -0.1))
        if underside_chamfer:
            # The inner bottom edge spans the complete 71 mm length after setback.
            inner_edge_x = 1 if side == "left" else 11.5
            shape = shape.chamfer(edge_points=[[inner_edge_x, 35.5, 0]], distance=1)
        return shape.with_metadata(
            name="NH-L12S adapter prototype",
            side=side,
            slot_height_mm=slot_height,
            source="homelab-cooler-adapters/manufacturing/slot-height-variants-label-08",
            manufacturing_ready=False,
        )
