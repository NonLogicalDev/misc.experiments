"""Import SphereDim JSON into Blender: blender --python blender_import.py -- poses.json."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


def main():
    if "--" not in sys.argv or len(sys.argv[sys.argv.index("--") + 1:]) != 1:
        raise ValueError("Usage: blender --python blender_import.py -- poses.json")
    path = Path(sys.argv[sys.argv.index("--") + 1])
    data = json.loads(path.read_text())
    if data.get("schema") != "spheredim-poses-v1":
        raise ValueError("Unsupported SphereDim pose format")
    scene = bpy.context.scene
    camera_data = bpy.data.cameras.new("SphereDim Camera")
    camera = bpy.data.objects.new("SphereDim Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "PANO"
    camera_data.panorama_type = "EQUIRECTANGULAR"
    camera.rotation_mode = "QUATERNION"
    # COLMAP uses x right, y down, z forward; Blender uses x right, y up, -z forward.
    camera_axes = Matrix.Diagonal((1, -1, -1, 1))
    scene_fps = scene.render.fps / scene.render.fps_base
    previous = None
    for pose in data["frames"]:
        if pose["world_from_camera"] is None:
            continue
        matrix = Matrix(pose["world_from_camera"]).to_4x4() @ camera_axes
        camera.location = matrix.to_translation()
        rotation = matrix.to_quaternion()
        if previous is not None and rotation.dot(previous) < 0:
            rotation.negate()
        previous = rotation.copy()
        camera.rotation_quaternion = rotation
        frame = 1 + pose["time_seconds"] * scene_fps
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    scene.frame_end = max(1, math.ceil(1 + data["frames"][-1]["time_seconds"] * scene_fps))
    print(f"Imported {data['registered']} camera poses. Gaps are interpolated by Blender.")


main()
