"""Regression coverage for verified review findings; software-only."""
import csv, math, tempfile, sys, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import DEFAULT_LAYOUT, MotionKalman, in_polygon, project_into_polygon, RangeCalibration, IDS
import collector

class ReviewedRegressionTests(unittest.TestCase):
    def test_kalman_never_displays_outside_room_at_wall(self):
        k=MotionKalman()
        seq=[(8,3),(9,3),(10,3),(10,3),(10,3),(10,3)]
        for i,point in enumerate(seq,1):
            xy,_,_=k.update(point,i,polygon=DEFAULT_LAYOUT['polygon'])
            self.assertTrue(in_polygon(xy,DEFAULT_LAYOUT['polygon']))
            self.assertTrue(in_polygon(k.x[:2],DEFAULT_LAYOUT['polygon']))
        self.assertLessEqual(xy[0],10.)

    def test_projection_on_skew_quad(self):
        poly=[[0,0],[6,0],[5,4],[1,4]]
        for point in [(8,4),(-2,2),(3,5),(3,-1)]:
            result=project_into_polygon(point,poly)
            self.assertTrue(in_polygon(result,poly))
        k=MotionKalman()
        for t,x in enumerate([(2,2),(3,2),(4,2),(5,2),(5,2)],1):
            measured,_,_=k.update(x,t,polygon=poly)
            self.assertTrue(in_polygon(measured,poly))

    def test_evaluation_records_which_anchors_used(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            with patch.object(collector,'ROOT',root),patch.object(collector,'STATE',root/'config'/'state.json'):
                s=collector.Collector('review');s.display_mode='geometry'
                try:
                    s.control({'action':'set_reliability','excluded_anchor':'L3','adaptive_weights':True})
                    b='aa:bb:cc:dd:ee:ff'
                    for aid in ('L1','L2','L4'):
                        for d in (1.,3.,6.):
                            s.cal.add(aid,d,[-44-22*math.log10(d)]*8,b)
                    p=(3.,2.)
                    for sequence in (1,2):
                        for aid in ('L1','L2','L4'):
                            d=math.dist([*p,.8],DEFAULT_LAYOUT['anchors'][aid])
                            s.accept({'protocol_version':2,'type':'measurement','session':'review',
                                      'anchor_id':aid,'sequence':sequence,'rssi_dbm':-44-22*math.log10(d),
                                      'measurement_mode':'real','bssid':b,'hostname':'test'})
                        if sequence==1:s.control({'action':'start_live'})
                    s.control({'action':'evaluate','x':p[0],'y':p[1]})
                    with open(s.evalpath,newline='',encoding='utf-8') as f:
                        rows=list(csv.DictReader(f))
                    self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]['excluded_anchor'],'L3')
                    self.assertEqual(rows[0]['active_anchors'],'L1,L2,L4')
                    self.assertEqual(rows[0]['adaptive_weights'],'True')
                    self.assertEqual(rows[0]['weight_L3'],'0.0')
                    self.assertEqual(rows[0]['calibrated_bssid'],b)
                finally:s.close()

    def test_two_point_calibration_not_enough_for_plateau(self):
        c=RangeCalibration();b='aa:bb:cc:dd:ee:ff'
        for d,r in ((1,-45),(6,-59)):
            c.add('L3',d,[r]*10,b)
        self.assertGreater(c.quality('L3',-60)['score'],.4)
        # It cannot see the deceptive 2--6m plateau until those refs are given.
        for d,r in ((2,-59),(4,-61)):
            c.add('L3',d,[r]*10,b)
        self.assertLess(c.quality('L3',-60)['score'],.25)

if __name__=='__main__':unittest.main()
