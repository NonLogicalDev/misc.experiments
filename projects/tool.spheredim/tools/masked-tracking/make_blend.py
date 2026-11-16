"""Build a Blender scene from SphereDim poses and its sparse ASCII PLY."""
import json, runpy, subprocess, sys
from fractions import Fraction
from pathlib import Path
import bpy
args=sys.argv[sys.argv.index('--')+1:]
importer,poses,ply,dest,*optional=args
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene; scene.render.fps=30; scene.render.fps_base=1
if optional:
    rate=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','default=noprint_wrappers=1:nokey=1',optional[0]],text=True).strip()
    fps=float(Fraction(rate))
    if fps <= 0: raise ValueError('Video frame rate must be positive')
    scene.render.fps=max(1,round(fps)); scene.render.fps_base=scene.render.fps/fps
sys.argv=['blender','--',poses];runpy.run_path(importer,run_name='__main__')
with open(ply) as f:
    count=None
    for line in f:
        if line.startswith('element vertex '):count=int(line.split()[-1])
        if line.strip()=='end_header':break
    if count is None: raise ValueError('PLY has no vertex count')
    points=[];colors=[]
    for _ in range(count):
        p=f.readline().split();points.append(tuple(map(float,p[:3])));colors.append(tuple(int(x)/255 for x in p[3:6])+(1.0,))
mesh=bpy.data.meshes.new('Sparse reconstructed points');mesh.from_pydata(points,[],[]);mesh.update()
cloud=bpy.data.objects.new('Sparse reconstructed points',mesh);bpy.context.scene.collection.objects.link(cloud)
attr=mesh.color_attributes.new(name='Color',type='BYTE_COLOR',domain='POINT')
for datum,color in zip(attr.data,colors):datum.color_srgb=color
# Expose vertices as actual visible points without inventing surface geometry.
modifier=cloud.modifiers.new('Display points','NODES');group=bpy.data.node_groups.new('Sparse point display','GeometryNodeTree')
group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry');group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
in_node=group.nodes.new('NodeGroupInput');out_node=group.nodes.new('NodeGroupOutput');points_node=group.nodes.new('GeometryNodeMeshToPoints');points_node.inputs['Radius'].default_value=0.015
group.links.new(in_node.outputs['Geometry'],points_node.inputs['Mesh'])
material=bpy.data.materials.new('Reconstructed point colors');material.use_nodes=True
nodes=material.node_tree.nodes;nodes.clear()
material_out=nodes.new('ShaderNodeOutputMaterial');emission=nodes.new('ShaderNodeEmission');attribute=nodes.new('ShaderNodeAttribute');attribute.attribute_name='Color'
material.node_tree.links.new(attribute.outputs['Color'],emission.inputs['Color']);material.node_tree.links.new(emission.outputs['Emission'],material_out.inputs['Surface'])
set_material=group.nodes.new('GeometryNodeSetMaterial');set_material.inputs['Material'].default_value=material
group.links.new(points_node.outputs['Points'],set_material.inputs['Geometry']);group.links.new(set_material.outputs['Geometry'],out_node.inputs['Geometry']);modifier.node_group=group
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D': area.spaces.active.shading.type='MATERIAL'
scene=bpy.context.scene
if optional:
    clip=bpy.data.movieclips.load(optional[0],check_existing=True)
    scene.camera.data.show_background_images=True
    background=scene.camera.data.background_images.new(); background.source='MOVIE_CLIP'; background.clip=clip
# The trajectory line is an aid to inspection; each vertex is one recovered camera position.
data=json.loads(Path(poses).read_text());positions=[p['world_from_camera'] for p in data['frames'] if p['world_from_camera'] is not None]
curve=bpy.data.curves.new('Camera trajectory','CURVE');curve.dimensions='3D';curve.bevel_depth=0.006
spline=curve.splines.new('POLY');spline.points.add(len(positions)-1)
for point,m in zip(spline.points,positions):point.co=(m[0][3],m[1][3],m[2][3],1)
scene.collection.objects.link(bpy.data.objects.new('Camera trajectory',curve))
scene.frame_end=max(1,int(round(1+data['frames'][-1]['time_seconds']*scene.render.fps/scene.render.fps_base)))
scene.render.engine='CYCLES'
bpy.ops.wm.save_as_mainfile(filepath=dest)
print(f'Created Blender scene with {len(positions)} poses and {len(points)} sparse points: {dest}')
