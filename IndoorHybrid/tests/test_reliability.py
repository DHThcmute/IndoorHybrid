"""Synthetic software tests, NOT a measured field-accuracy claim."""
import math,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import IDS,DEFAULT_LAYOUT,RangeCalibration,OnlineRangePipeline,solve_ranges
import collector
BSSID='aa:bb:cc:dd:ee:ff'

class ReliabilityTests(unittest.TestCase):
    def build_cal(self):
        c=RangeCalibration()
        for a in IDS:
            if a=='L3':
                for d,r in [(1,-45),(2,-59),(4,-61),(6,-59)]:
                    c.add(a,d,[r]*8,BSSID)
            else:
                for d in (1.,2.,4.,6.,10.):
                    r=-43-22*math.log10(d)
                    c.add(a,d,[r]*8,BSSID)
        return c
    def test_plateau_quality(self):
        c=self.build_cal()
        self.assertLess(c.quality('L3',-60)['score'],.25)
        self.assertGreater(c.quality('L1',-60)['score'],.75)
        self.assertIn('RSSI phẳng',c.quality('L3')['reason'])
    def test_good_anchor_more_weight(self):
        c=self.build_cal();p=(4.,3.)
        readings={a:(-60 if a=='L3' else -43-22*math.log10(math.dist([*p,.8],DEFAULT_LAYOUT['anchors'][a]))) for a in IDS}
        result=OnlineRangePipeline(DEFAULT_LAYOUT,c).update(readings,when=10.)
        self.assertLess(result['weights']['L3'],result['weights']['L1'])
        self.assertEqual(len(result['active_anchors']),4)
    def test_explicit_three_anchor_no_l3_data(self):
        c=self.build_cal();p=(4.,3.)
        readings={a:-43-22*math.log10(math.dist([*p,.8],DEFAULT_LAYOUT['anchors'][a])) for a in ('L1','L2','L4')}
        result=OnlineRangePipeline(DEFAULT_LAYOUT,c,excluded_anchor='L3').update(readings,when=10.)
        self.assertEqual(result['weights']['L3'],0)
        self.assertIsNone(result['ranges_m'][2])
        self.assertLess(math.dist(result['raw'],p),.01)
    def test_equal_weights_mode(self):
        c=self.build_cal();p=(4.,3.)
        readings={a:-43-22*math.log10(math.dist([*p,.8],DEFAULT_LAYOUT['anchors'][a])) for a in IDS}
        r=OnlineRangePipeline(DEFAULT_LAYOUT,c,adaptive_weights=False).update(readings,when=10.)
        self.assertTrue(all(r['weights'][a]==1 for a in IDS))
    def test_three_collinear_rejected(self):
        layout={'polygon':[[0,0],[10,0],[10,6],[0,6]],'anchors':{
            'L1':[1,1,.8],'L2':[2,1,.8],'L3':[1,4,.8],'L4':[3,1,.8]},'phone_z':.8}
        with self.assertRaisesRegex(ValueError,'thẳng hàng'):
            solve_ranges(layout,[2.,3.,float('nan'),4.],weights=[1.,1.,0.,1.])
    def test_collector_3_anchor_without_l3(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(collector,'ROOT',root),patch.object(collector,'STATE',root/'config'/'state.json'):
                s=collector.Collector('test');s.display_mode='geometry'
                try:
                    s.control({'action':'set_reliability','excluded_anchor':'L3','adaptive_weights':True})
                    for a in ('L1','L2','L4'):
                        for d in (1.,4.,8.):
                            s.cal.add(a,d,[-43-22*math.log10(d)]*8,BSSID)
                    p=(3.,2.)
                    for a in ('L1','L2','L4'):
                        d=math.dist([*p,.8],DEFAULT_LAYOUT['anchors'][a])
                        s.accept({'protocol_version':2,'type':'measurement','session':'test',
                                  'anchor_id':a,'sequence':1,'rssi_dbm':-43-22*math.log10(d),
                                  'measurement_mode':'real','bssid':BSSID,'hostname':'TEST'})
                    self.assertIsNone(s.age_check(time.monotonic()))
                    s.control({'action':'start_live'})
                    for a in ('L1','L2','L4'):
                        d=math.dist([*p,.8],DEFAULT_LAYOUT['anchors'][a])
                        s.accept({'protocol_version':2,'type':'measurement','session':'test',
                                  'anchor_id':a,'sequence':2,'rssi_dbm':-43-22*math.log10(d),
                                  'measurement_mode':'real','bssid':BSSID,'hostname':'TEST'})
                    self.assertTrue(s.last)
                    self.assertEqual(s.last['weights']['L3'],0)
                    s.control({'action':'stop_live'})
                    s.close()
                    s=collector.Collector('test');s.display_mode='geometry'
                    self.assertEqual(s.excluded_anchor,'L3')
                    self.assertTrue(s.adaptive_weights)
                finally:
                    s.close()
    def test_no_changes_during_live(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(collector,'ROOT',root),patch.object(collector,'STATE',root/'config'/'state.json'):
                s=collector.Collector('test');s.display_mode='geometry'
                try:
                    s.mode='LIVE'
                    with self.assertRaisesRegex(ValueError,'STOP LIVE'):
                        s.control({'action':'set_reliability','excluded_anchor':'L3','adaptive_weights':True})
                finally:s.close()

if __name__=='__main__':unittest.main()
