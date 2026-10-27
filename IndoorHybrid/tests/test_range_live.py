"""Software-only tests; synthetic RSSI is never presented as measured performance."""
import math,sys,unittest,random,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import (IDS,DEFAULT_LAYOUT,RangeCalibration,OnlineRangePipeline,MotionKalman,
                  solve_ranges,validate_layout,in_polygon)

class RangeTests(unittest.TestCase):
    def setUp(self):self.layout=validate_layout(DEFAULT_LAYOUT)
    def test_01_room_rectangle(self):
        l=dict(self.layout)
        l['polygon']=[[0,0],[5,0],[5,5],[0,5]]
        l['anchors']={i:[*l['polygon'][j],.8] for j,i in enumerate(IDS)}
        self.assertEqual(validate_layout(l)['polygon'][2],[5.,5.])
    def test_02_room_quad(self):
        l=dict(self.layout);l['polygon']=[[0,0],[6,0],[5,4],[1,4]]
        l['anchors']={i:[*l['polygon'][j],.8] for j,i in enumerate(IDS)}
        validate_layout(l)
    def test_03_bad_quad(self):
        l=dict(self.layout);l['polygon']=[[0,0],[6,4],[6,0],[0,4]]
        with self.assertRaises(ValueError):validate_layout(l)
    def test_04_bad_anchors(self):
        l=dict(self.layout);l['anchors']={i:[1,1,.8] for i in IDS}
        with self.assertRaises(ValueError):validate_layout(l)
    def test_05_point_in_polygon(self):
        self.assertTrue(in_polygon((4,2),self.layout['polygon']))
        self.assertFalse(in_polygon((11,2),self.layout['polygon']))
    def test_06_cal_one_provisional(self):
        cal=RangeCalibration();cal.add('L1',2.,[-57]*8,'aa:bb:cc:dd:ee:ff')
        m=cal.fit('L1');self.assertTrue(m['provisional']);self.assertEqual(m['n'],2)
    def test_07_cal_two_fit(self):
        cal=RangeCalibration()
        for d in (1.5,5.,9.):
            value=-42.-10*2.3*math.log10(d)
            cal.add('L1',d,[value]*9,'aa:bb:cc:dd:ee:ff')
        f=cal.fit('L1');self.assertAlmostEqual(f['n'],2.3,places=2)
        self.assertAlmostEqual(f['A'],-42.,places=2)
    def test_08_cal_bssid(self):
        cal=RangeCalibration();cal.add('L1',2.,[-57]*8,'aa:bb:cc:dd:ee:ff')
        with self.assertRaises(ValueError):cal.add('L2',2.,[-57]*8,'11:bb:cc:dd:ee:ff')
    def test_09_cal_save_round_trip(self):
        cal=RangeCalibration();cal.add('L1',2.,[-57]*8,'aa:bb:cc:dd:ee:ff')
        restored=RangeCalibration.from_json(cal.to_json())
        self.assertEqual(restored.fit('L1'),cal.fit('L1'))
    def test_10_trilateration_exact(self):
        x=np.array([3.,4.]);rr=[np.linalg.norm(x-np.array(self.layout['anchors'][a][:2])) for a in IDS]
        result,residual=solve_ranges(self.layout,rr)
        self.assertLess(np.linalg.norm(result-x),1e-4)
        self.assertLess(residual,1e-4)
    def test_11_trilateration_height(self):
        layout=validate_layout({**self.layout,'phone_z':1.3})
        x=np.array([7.,1.]);rr=[math.dist([*x,1.3],layout['anchors'][a]) for a in IDS]
        result,_=solve_ranges(layout,rr);self.assertLess(np.linalg.norm(result-x),1e-4)
    def test_12_trilateration_noisy(self):
        p=np.array([3.,4.]);rng=np.random.default_rng(51)
        base=[math.dist([*p,.8],self.layout['anchors'][a]) for a in IDS]
        estimates=[]
        for _ in range(25):
            noisy=np.maximum(.3,np.array(base)+rng.normal(0,.35,4))
            pos,_=solve_ranges(self.layout,noisy);estimates.append(np.linalg.norm(pos-p))
        self.assertLess(float(np.median(estimates)),.6)
    def test_13_pipeline_rssi_direct(self):
        cal=RangeCalibration();p=np.array([3.,2.]);A=-43.;n=2.2
        for aid in IDS:
            for d in (1.4,6.,11.):
                val=A-10*n*math.log10(d)
                cal.add(aid,d,[val]*8,'aa:bb:cc:dd:ee:ff')
        model=OnlineRangePipeline(self.layout,cal)
        rssi=[A-10*n*math.log10(math.dist([*p,.8],self.layout['anchors'][aid])) for aid in IDS]
        out=model.update(rssi,when=1.)
        self.assertLess(math.dist(out['raw'],p),.01)
        self.assertLess(math.dist(out['filtered'],p),.01)
    def test_14_kalman_speed_limit(self):
        f=MotionKalman(vmax=3.);f.update([0,0],1.)
        for t in (1.2,1.4,1.6,1.8,2.):
            old=f.display.copy();new,_,_=f.update([10,0],t)
            self.assertLessEqual(float(np.linalg.norm(new-old)),.601)
    def test_15_reacquisition(self):
        f=MotionKalman();f.update([0,0],1.)
        statuses=[f.update([8,5],1.+i)[1] for i in range(1,6)]
        self.assertIn('REACQUIRE',statuses)
    def test_16_accept_normal_motion(self):
        f=MotionKalman();f.update([0,0],1.)
        out=[f.update([.6*i,0],1+i)[1] for i in range(1,6)]
        self.assertTrue(all(i in ('ACCEPT','REACQUIRE') for i in out))
    def test_17_latency_algorithm(self):
        p=np.array([5.,3.]);rr=[math.dist([*p,.8],self.layout['anchors'][a]) for a in IDS]
        start=time.perf_counter()
        for i in range(20):solve_ranges(self.layout,rr)
        elapsed=(time.perf_counter()-start)/20
        self.assertLess(elapsed,.2)

if __name__=='__main__':unittest.main()
