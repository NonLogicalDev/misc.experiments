"""Run: blender -b --python apply_blender.py -- input.blend gravity.json output.blend"""
import json,math,sys
from pathlib import Path
import bpy
from mathutils import Vector,Matrix
args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
if len(args)!=3: raise ValueError('expected input.blend gravity.json output.blend')
source,gravity,dest=map(lambda x:Path(x).resolve(),args)
if not source.is_file() or dest.exists() or source==dest: raise ValueError('input must exist and output must be new')
with gravity.open() as f: data=json.load(f)
if data.get('schema')!='spheredim-gravity-v1': raise ValueError('invalid gravity schema')
up=Vector(data['world_up'])
if len(up)!=3 or not all(math.isfinite(v) for v in up) or abs(up.length-1)>0.001: raise ValueError('world_up must be finite and unit length')
bpy.ops.wm.open_mainfile(filepath=str(source))
scene=bpy.context.scene;objects=list(scene.objects); objset=set(objects)
if not objects: raise ValueError('empty scene')
if any(obj.library is not None for obj in objects): raise ValueError('linked objects are not supported')
if any(obj.constraints for obj in objects): raise ValueError('object constraints require explicit validation')
if any(obj.parent and obj.parent not in objset for obj in objects): raise ValueError('parent outside active scene')
root=bpy.data.objects.new('SphereDim Gravity Alignment',None);scene.collection.objects.link(root)
for obj in objects:
 if obj.parent is None:
  obj.parent=root;obj.matrix_parent_inverse=Matrix.Identity(4)
root.rotation_mode='QUATERNION';root.rotation_quaternion=up.rotation_difference(Vector((0,0,1)))
bpy.ops.wm.save_as_mainfile(filepath=str(dest))
print(f'Rotated {len(objects)} objects under {root.name}; saved {dest}',flush=True)
