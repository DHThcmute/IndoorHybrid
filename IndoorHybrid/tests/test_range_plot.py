"""Regression tests for RSSI-distance plot: synthetic packets, NOT real accuracy."""
import math, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import RangeCalibration,DEFAULT_LAYOUT,IDS
from range_plot_math import rssi_to_distance,take_samples

BSSID='a1:22:33:44:55:66'

class PlotMathTests(unittest.TestCase):
    def setUp(self):
        self.layout=DEFAULT_LAYOUT
        self.fit={'A':-44.,'n':2.,'points':3,'provisional':False}
        self.refs={a:3.0 for a in IDS}
    def status(self,seq=5,age=0.1,bssid=BSSID,with_cal=True):
        return {'session':'plotcheck','mode':'IDLE','layout':self.layout,
            'anchors':{a:{'rssi':-44-20*math.log10(3.),'bssid':bssid,'seq':seq,
                           'fresh':age<2.7,'age_s':age} for a in IDS},
            'calibration':{a:(self.fit if with_cal else None) for a in IDS},
            'calibrated_bssid':BSSID if with_cal else None}

    def test_conversion_and_ground_truth_not_used_for_estimation(self):
        distance=rssi_to_distance(-44-20*math.log10(3),self.fit,self.layout,'L1')
        self.assertAlmostEqual(distance,3,places=6)
        seq={}
        s=self.status()
        records=take_samples(s,seq,self.refs,elapsed_s=1.2)
        self.assertEqual(len(records),4)
        self.assertAlmostEqual(records[0]['estimated_m'],3,places=6)
        refs_new={a:8.0 for a in IDS}
        seq={}
        next_records=take_samples(s,seq,refs_new,elapsed_s=1.2)
        self.assertAlmostEqual(next_records[0]['estimated_m'],3,places=6)
        self.assertAlmostEqual(next_records[0]['error_m'],-5,places=6)

    def test_no_duplicate_status_samples(self):
        s=self.status()
        seen={}
        self.assertEqual(len(take_samples(s,seen,self.refs)),4)
        self.assertEqual(len(take_samples(s,seen,self.refs)),0)
        self.assertEqual(len(take_samples(self.status(seq=6),seen,self.refs)),4)

    def test_do_not_accept_stale_bssid_or_uncalibrated(self):
        self.assertEqual(take_samples(self.status(age=3),{},self.refs),[])
        self.assertEqual(take_samples(self.status(bssid='b1:22:33:44:55:66'),{},self.refs),[])
        self.assertEqual(take_samples(self.status(with_cal=False),{},self.refs),[])

    def test_2d_projection_matches_calibration(self):
        cal=RangeCalibration()
        for a in IDS:
            cal.add(a,1.0,[-44]*8,BSSID)
            cal.add(a,3.0,[-44-20*math.log10(3)]*8,BSSID)
        vals=cal.ranges([-44-20*math.log10(3)]*4,self.layout)
        for j,a in enumerate(IDS):
            self.assertAlmostEqual(rssi_to_distance(-44-20*math.log10(3),cal.fit(a),self.layout,a,'3d'),vals[j,0],places=6)
            self.assertAlmostEqual(rssi_to_distance(-44-20*math.log10(3),cal.fit(a),self.layout,a,'2d'),vals[j,1],places=6)

    def test_invalid_fit_is_not_fake_distance(self):
        self.assertIsNone(rssi_to_distance(-60,None,self.layout,'L3'))
        self.assertIsNone(rssi_to_distance(float('nan'),self.fit,self.layout,'L3'))
        self.assertIsNone(rssi_to_distance(-60,{'A':-50,'n':0},self.layout,'L3'))

if __name__=='__main__':unittest.main()
