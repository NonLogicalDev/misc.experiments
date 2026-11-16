import json,os,tempfile,unittest
from pathlib import Path
import numpy as np
import prepare_sharp_overlay as s

I=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
class OverlayTests(unittest.TestCase):
 def test_pose_composition_and_invalid_rotation(self):
  a={'rotation':I,'translation':[1.,2.,3.]};b={'rotation':I,'translation':[4.,5.,6.]};r,t=s.compose(a,b);np.testing.assert_allclose(r,np.eye(3));np.testing.assert_allclose(t,[5,7,9])
  with self.assertRaisesRegex(ValueError,'rotation'):s.compose({'rotation':[[2,0,0],[0,1,0],[0,0,1]],'translation':[0,0,0]},b)
 def test_noncommuting_rig_composition(self):
  rc=[[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]];rr=[[1.,0.,0.],[0.,0.,-1.],[0.,1.,0.]];tc=np.array([1.,2.,3.]);tr=np.array([4.,5.,6.]);point=np.array([2.,3.,7.]);r,t=s.compose({'rotation':rc,'translation':tc.tolist()},{'rotation':rr,'translation':tr.tolist()});np.testing.assert_allclose(r@point+t,np.array(rc)@(np.array(rr)@point+tr)+tc)
 def test_pair_pts(self):
  s.check_pts({'timestamp_microseconds':1000000,'source_packet_pts':[{'stream':0,'pts':30,'time_base':'1/30'},{'stream':1,'pts':30,'time_base':'1/30'}]})
  with self.assertRaisesRegex(ValueError,'PTS mismatch'):s.check_pts({'timestamp_microseconds':1000000,'source_packet_pts':[{'stream':0,'pts':30,'time_base':'1/30'},{'stream':1,'pts':31,'time_base':'1/30'}]})
 def test_training_overlay_preserves_unmodified_data(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();source=root/'prepared';model=root/'model';dataset=root/'dataset';run=root/'run';src=root/'blob';src.write_bytes(b'pixels');(source/'sparse/0').mkdir(parents=True);(source/'images').mkdir();(source/'masks').mkdir();model.mkdir();dataset.mkdir();run.mkdir();(run/'config.json').write_text(json.dumps({'refine_stop_iter':0,'refine_stop_num_iter':2000}));(source/'seed.ply').write_bytes(b'original seed');(source/'sparse/0/cameras.txt').write_text('1 EQUIRECTANGULAR 1024 512 1024 512\n2 EQUIRECTANGULAR 1024 512 1024 512\n');(source/'sparse/0/points3D.txt').write_text('# empty seed\n');(dataset/'manifest.json').write_text('{}');binary=root/'trainer';binary.write_bytes(b'trainer')
   for name in ('cameras.bin','images.bin','points3D.bin','rigs.txt'):(model/name).write_text(name)
   records=[];lines=[];i=0
   for lens in ('cam0','cam1'):
    for j in range(412):
     n=j*5;split='eval' if j%24==0 else 'train';name=f'{split}_{n:06d}_{lens}.png';cam=1+int(lens[-1]);t=cam-1;records.append({'name':name,'source_name':f'{lens}/frame_{n:06d}.png','source_frame':n,'lens':lens,'split':split,'timestamp_microseconds':n*1000,'source_packet_pts':[{'stream':k,'pts':n,'time_base':'1/1000'} for k in (0,1)],'colmap_image_id':i,'colmap_camera_id':cam});lines.append(f'{i} 1 0 0 0 {t} 0 0 {cam} {name}\n\n');i+=1
     for folder in ('images','masks'):os.link(src,source/folder/name)
   (source/'sparse/0/images.txt').write_text(''.join(lines));cmd=[str(binary),'train','360-camera','--data',str(source),'--output-dir-prefix',str(root),'--output-dir-name','run','--num-iterations','6000','--steps-per-save','1000','--save-full-checkpoint','1'];base={'dataset':str(dataset),'source_manifest_sha256':s.sha(dataset/'manifest.json'),'binary_sha256':s.sha(binary),'model':str(model),'model_hashes':{n:s.sha(model/n) for n in ('cameras.bin','images.bin','points3D.bin','rigs.txt')},'seed_sha256':s.sha(source/'seed.ply'),'frames':records,'heldout_evaluation_order':sorted(x['name'] for x in records if x['split']=='eval'),'command':cmd};(source/'manifest.json').write_text(json.dumps(base))
   anchors=list(range(1340,1401,5));frames=[];fits=[]
   for anchor in anchors:
    n=anchor if anchor==1350 else anchor-1;lenses={}
    for lens in ('cam0','cam1'):
     lenses[lens]={}
     for folder in ('images','masks'):lenses[lens][folder]={'path':str(src),'sha256':s.sha(src)}
    frames.append({'anchor':anchor,'source_frame':n,'timestamp_microseconds':n*1000,'source_packet_pts':[{'stream':k,'pts':n,'time_base':'1/1000'} for k in (0,1)],'lenses':lenses});fits.append({'source_frame':n,'timestamp_microseconds':n*1000,'anchor_source_frame':anchor,'accepted':True,'rig_from_world':{'rotation':I,'translation':[0.,1.,0.]}})
   repl=root/'repl.json';repl.write_text(json.dumps({'frames':frames}));inputs={str(repl):s.sha(repl),str(source/'seed.ply'):s.sha(source/'seed.ply'),**{str(model/n):s.sha(model/n) for n in ('images.bin','points3D.bin','rigs.txt')}};registration=root/'fit.json';registration.write_text(json.dumps({'input_sha256':inputs,'source_feature_sha256':{},'cam_from_rig':[{'rotation':I,'translation':[0,0,0]},{'rotation':I,'translation':[1,0,0]}],'frames':fits}));out=root/'overlay';m=s.prepare(source/'manifest.json',repl,registration,out,'overlay-run')
   command,run_path,train,heldout,steps=s.verify(source/'manifest.json',repl,registration,out);self.assertEqual((train,heldout,steps),(788,36,6000))
   self.assertEqual(len(m['frames']),824);self.assertEqual(m['overlay']['replacement_count'],12);self.assertEqual(m['heldout_evaluation_order'],base['heldout_evaluation_order']);self.assertEqual(s.sha(out/'seed.ply'),base['seed_sha256']);self.assertEqual((out/'images/train_001350_cam0.png').stat().st_ino,(source/'images/train_001350_cam0.png').stat().st_ino)
   before=(source/'sparse/0/images.txt').read_text().splitlines();after=(out/'sparse/0/images.txt').read_text().splitlines();unchanged=[i for i in range(0,len(before),2) if 'train_001340_cam0.png' not in before[i] and 'train_001340_cam1.png' not in before[i] and not any(f'train_{n:06d}_cam' in before[i] for n in anchors if n!=1350)];self.assertTrue(all(before[i]==after[i] and after[i+1]=='' for i in unchanged));self.assertIn('train_001339_cam0.png',(out/'sparse/0/images.txt').read_text())
   with (out/'sparse/0/images.txt').open('a') as f:f.write('tampered')
   with self.assertRaisesRegex(ValueError,'poses differ'):s.verify(source/'manifest.json',repl,registration,out)
if __name__=='__main__':unittest.main()
