"""Reusable modules, plus a default shape that can be previewed on its own."""

from typing import Annotated

import solidrecipe as sr

with sr.module("mounts"):

    @sr.exportf
    def bracket(
        slot_height: Annotated[
            float,
            sr.Param(
                description="Slot height", unit="mm", minimum=4.5, maximum=4.7, step=0.1
            ),
        ] = 4.6,
    ):
        """Return a simple demonstration bracket; not a manufacturing model."""
        return sr.Box(12.5, 71, 13) - sr.Box(10, 46, slot_height, origin=(-1, 8, 2.8))


with sr.module("spacers"):

    @sr.exportf("round")
    def round_spacer(height=2):
        return sr.Cylinder(radius=4, height=height)


sr.export(bracket())
