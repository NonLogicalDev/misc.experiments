"""Exploratory NH-L12S adapter reconstruction; do not manufacture this model.

Change SIDE and SLOT_HEIGHT to inspect either bracket and the three slot variants.
The source of truth remains homelab-cooler-adapters' slot-height-variants-label-08.
This first SolidRecipe model omits the original chamfer, fillets, rounded outside
corners and engraved labels; it does not establish fit or safe mounting pressure.
"""

import solidrecipe as sr

# The submitted designs differ in slot height and in the handed screw positions.
SIDE = "left"  # "left" or "right"
SLOT_HEIGHT = 4.6  # mm; submitted variants: 4.5, 4.6, 4.7


def adapter(side, slot_height):
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
    # The lower edge is set back by 1 mm for the full 71 mm length.
    shape -= block(-0.1, -0.1, -0.1, 1.1, 71.2, 7.5 - slot_height)

    # The two source brackets use different recovered X positions. Screw axes
    # are 60 mm apart along Y; holes are nominally 3.5 mm in diameter.
    hole_x = 9.225527 if side == "left" else 12.5 - (28.524473 - 19.75)
    for y in (5.5, 65.5):
        shape -= sr.Cylinder(1.75, 9, origin=(hole_x, y, -0.1))
    return shape


model = adapter(SIDE, SLOT_HEIGHT)
