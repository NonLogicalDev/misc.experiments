"""Use a named factory from a neighboring SolidRecipe module file."""

import solidrecipe as sr

hardware = sr.load("hardware.py")
sr.export(hardware.mounts.bracket(slot_height=4.5))
