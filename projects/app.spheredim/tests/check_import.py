"""Import the actual output, record evaluated Blender camera matrices, and save a blend."""
import json
import runpy
import sys
from pathlib import Path
import bpy
args = sys.argv[sys.argv.index('--')+1:]
importer, poses, out = args
sys.argv = ['blender', '--', poses]
runpy.run_path(importer, run_name='__main__')
data = json.loads(Path(poses).read_text())
scene = bpy.context.scene
results = {}
for item in data['frames']:
    if item['world_from_camera'] is None:
        continue
    frame = 1 + item['time_seconds'] * scene.render.fps / scene.render.fps_base
    scene.frame_set(int(frame), subframe=frame-int(frame))
    bpy.context.view_layer.update()
    results[str(item['frame'])] = [list(row) for row in scene.camera.matrix_world]
Path(out + '.json').write_text(json.dumps(results))
bpy.ops.wm.save_as_mainfile(filepath=out + '.blend')
