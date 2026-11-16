import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from diagnose_sfm_horizon import angle,diagnose

class HorizonTests(unittest.TestCase):
    def test_known_rotation_and_timestamp_guard(self):
        theta=np.pi/2;rot=np.array([[np.cos(theta),-np.sin(theta),0],[np.sin(theta),np.cos(theta),0],[0,0,1]])
        self.assertAlmostEqual(angle(rot),90)
        def pose(r):return np.column_stack((r,np.zeros(3))).tolist()
        sfm=[{'source_frame':i,'time_seconds':float(i),'world_from_camera':pose(r)} for i,r in enumerate([np.eye(3),rot,np.eye(3)])]
        dvo=[{'time_seconds':float(i),'world_from_camera':pose(np.eye(3))} for i in range(3)]
        fused={i:{'pts':float(i),'heading':0} for i in range(3)}
        result=diagnose(sfm,dvo,fused,[1]);self.assertEqual(len(result),2);self.assertAlmostEqual(result[0]['sfm_up_change_degrees'],90);self.assertAlmostEqual(result[0]['dvo_up_change_degrees'],0)
        fused[1]['pts']=1.1
        with self.assertRaises(ValueError):diagnose(sfm,dvo,fused,[1])
if __name__=='__main__':unittest.main()
