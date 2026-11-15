"""Render a deterministic equirectangular video and ground-truth Blender poses."""
import json
import math
import random
import sys
from pathlib import Path
import bpy
from mathutils import Vector

arguments = sys.argv[sys.argv.index('--') + 1:]
output = Path(arguments[0])
scenario = arguments[1] if len(arguments) > 1 else 'baseline'
if scenario not in ('baseline', 'loop', 'dynamic', 'plain', 'repetitive', 'low_light'):
    raise ValueError('Unknown scenario')
output.mkdir(parents=True, exist_ok=True)
random.seed({'dynamic': 1337, 'plain': 81, 'repetitive': 99, 'low_light': 2026}.get(scenario, 42))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'  # Cycles supports the native equirectangular camera.
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.render.resolution_x = 1024
scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.fps = 4 if scenario == 'baseline' else 8
scene.world.color = (0.4, 0.4, 0.4)
mat = bpy.data.materials.new('procedural texture')
mat.diffuse_color = (0.6, 0.6, 0.6, 1)
mat.use_nodes = True
nodes = mat.node_tree.nodes
links = mat.node_tree.links
shader = nodes.get('Principled BSDF')
noise = nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 9
noise.inputs['Detail'].default_value = 3
ramp = nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color = (0.025, 0.06, 0.11, 1)
ramp.color_ramp.elements[1].color = (0.9, 0.72, 0.35, 1)
links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
links.new(ramp.outputs['Color'], shader.inputs['Base Color'])
shader.inputs['Roughness'].default_value = 0.8
if scenario == 'plain':
    # Broad untextured surfaces leave only edges and illumination changes.
    for link in list(shader.inputs['Base Color'].links):
        links.remove(link)
    shader.inputs['Base Color'].default_value = (0.65, 0.65, 0.65, 1)
elif scenario == 'repetitive':
    # Identical repeated patterns stress correspondence ambiguity.
    for link in list(shader.inputs['Base Color'].links):
        links.remove(link)
    checker = nodes.new('ShaderNodeTexChecker')
    checker.inputs['Scale'].default_value = 5
    checker.inputs['Color1'].default_value = (0.15, 0.15, 0.15, 1)
    checker.inputs['Color2'].default_value = (0.8, 0.8, 0.8, 1)
    links.new(checker.outputs['Color'], shader.inputs['Base Color'])
# A textured room, plus objects at varied depths for parallax.
bpy.ops.mesh.primitive_cube_add(size=18)
room = bpy.context.object
room.data.materials.append(mat)
for i in range(10 if scenario == 'plain' else 65):
    x = random.uniform(-7, 7)
    y = random.uniform(-7, 7)
    z = random.uniform(-5, 5)
    if scenario == 'repetitive':
        x = -6 + 3 * (i % 5)
        y = -6 + 3 * ((i // 5) % 5)
        z = -3 + 3 * (i // 25)
    if x*x+y*y < 7:
        x += 3.5
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z), rotation=(random.random(), random.random(), random.random()))
    obj = bpy.context.object
    obj.scale = (0.45, 0.45, 0.45) if scenario == 'repetitive' else (random.uniform(.15,.8),random.uniform(.15,.8),random.uniform(.15,.8))
    obj.data.materials.append(mat)
bpy.ops.object.light_add(type='POINT', location=(0, 0, 4))
bpy.context.object.data.energy = 2200
bpy.ops.object.light_add(type='POINT', location=(3, -4, 0))
bpy.context.object.data.energy = 1800
if scenario == 'plain':
    scene.view_settings.exposure = -1.0
if scenario == 'low_light':
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = -3.0
    scene.cycles.samples = 4
bpy.ops.object.camera_add()
cam = bpy.context.object
scene.camera = cam
cam.data.type = 'PANO'
cam.data.panorama_type = 'EQUIRECTANGULAR'
truth = []
moving = None
if scenario == 'dynamic':
    bpy.ops.mesh.primitive_cube_add(size=1.5, location=(0, 3, 0))
    moving = bpy.context.object
    moving.data.materials.append(mat)
count = 20 if scenario == 'baseline' else (48 if scenario == 'loop' else (32 if scenario == 'dynamic' else 24))
for i in range(count):
    t = i / (count - 1)
    if scenario == 'baseline':
        cam.location = (2.0*t, 0.55*math.sin(t*math.pi*1.5), 0.3*math.sin(t*math.pi*2))
        cam.rotation_euler = (0.13*math.sin(t*math.pi*2), 0.16*math.sin(t*math.pi), 0.45*math.sin(t*math.pi*1.2))
    elif scenario == 'loop':
        cam.location = (1.6*math.sin(2*math.pi*t), 1.2*(1-math.cos(2*math.pi*t)), 0.45*math.sin(4*math.pi*t))
        cam.rotation_euler = (0.24*math.sin(2*math.pi*t), 0.3*math.sin(4*math.pi*t), 2*math.pi*t)
    elif scenario == 'dynamic':
        cam.location = (-1.2 + 2.4*t, 0.7*math.sin(3*math.pi*t), 0.4*math.sin(2*math.pi*t))
        cam.rotation_euler = (0.3*math.sin(3*math.pi*t), 0.3*math.sin(2*math.pi*t), 1.7*math.pi*t)
        moving.location = (2.3*math.cos(2*math.pi*t), 1.8*math.sin(2*math.pi*t), 0.7*math.sin(3*math.pi*t))
    else:
        cam.location = (-1.0 + 2.0*t, 0.55*math.sin(2*math.pi*t), 0.25*math.sin(3*math.pi*t))
        cam.rotation_euler = (0.16*math.sin(2*math.pi*t), 0.18*math.sin(3*math.pi*t), 1.4*math.pi*t)

    bpy.context.view_layer.update()
    # Cast rays into the actual scene, recording visible points over the entire sphere.
    samples = []
    for v in range(16, 512, 32):
        latitude = math.pi * (0.5 - v / 512)
        for u in range(16, 1024, 32):
            longitude = 2 * math.pi * (u / 1024 - 0.5)
            ray = Vector((math.sin(longitude)*math.cos(latitude), math.sin(latitude), -math.cos(longitude)*math.cos(latitude)))
            direction = cam.matrix_world.to_3x3() @ ray
            hit, point, _, _, _, _ = scene.ray_cast(bpy.context.evaluated_depsgraph_get(), cam.location, direction)
            if hit:
                samples.append([u, v, *point])
    truth.append({'frame': i, 'time_seconds': i/scene.render.fps, 'world_from_blender_camera': [list(row) for row in cam.matrix_world], 'visible_world_points': samples})
    scene.render.filepath = str(output / f'{i:06}.png')
    bpy.ops.render.render(write_still=True)
(output / 'truth.json').write_text(json.dumps(truth, indent=2))
