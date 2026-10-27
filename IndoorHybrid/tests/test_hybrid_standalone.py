"""Software-only tests. Packets contain synthetic RSSI, NOT real-world measurements."""
import csv,math,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import IDS,DEFAULT_LAYOUT
from hybrid_engine import HybridBayesianModel,HybridReferenceStore
import collector
BSSID='ab:12:34:56:78:9a'

class HybridSoftwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.p1=patch.object(collector,'ROOT',self.root)
        self.p2=patch.object(collector,'STATE',self.root/'config'/'state.json')
        self.p1.start();self.p2.start()
        self.c=collector.Collector('hybridtest');self.seq={a:0 for a in IDS}
        self.csv=self.root/'measurements.csv'
        self.xy=[(x,y) for x in (1.,4.5,8.5) for y in (1.,3.,5.)]
        with self.csv.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['point_id','anchor_id','x_true_m','y_true_m','z_true_m','rssi_dbm','bssid','orientation_deg']);w.writeheader()
            for i,(x,y) in enumerate(self.xy):
                for a in IDS:
                    r=self.rssi(x,y,a)
                    for _ in range(6):
                        w.writerow({'point_id':f'P{i}','anchor_id':a,'x_true_m':x,'y_true_m':y,
                            'z_true_m':.8,'rssi_dbm':r,'bssid':BSSID,'orientation_deg':0})
    def tearDown(self):
        self.c.close();self.p2.stop();self.p1.stop();self.tmp.cleanup()
    def rssi(self,x,y,a):
        d=math.dist([x,y,.8],DEFAULT_LAYOUT['anchors'][a]);return -43.-21.0*math.log10(max(d,.5))
    def packet(self,a,x,y,bssid=BSSID):
        self.seq[a]+=1
        return {'protocol_version':2,'type':'measurement','session':'hybridtest',
            'anchor_id':a,'sequence':self.seq[a],'rssi_dbm':self.rssi(x,y,a),
            'measurement_mode':'real','bssid':bssid,'hostname':'SYNTHETIC SOFTWARE TEST'}
    def do_import(self):
        response=self.c.control({'action':'import_hybrid_csv','path':str(self.csv),'geometry_confirmed':True})
        self.assertEqual(response['points_imported'],9)
        self.assertFalse(self.c.cal.refs['L1'])
        self.assertTrue(self.c.control({'action':'build_hybrid'})['hybrid']['trained'])
        self.assertEqual(self.c.display_mode,'hybrid')
    def test_import_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError,'xác nhận'):
            self.c.control({'action':'import_hybrid_csv','path':str(self.csv)})
    def test_live_hybrid_without_range_calibration(self):
        self.do_import()
        for a in IDS:self.c.accept(self.packet(a,2.,2.))
        self.c.control({'action':'start_live'})
        for a in IDS:self.c.accept(self.packet(a,2.,2.))
        self.assertTrue(self.c.last)
        self.assertIsNone(self.c.last['geometry'])
        self.assertIsNotNone(self.c.last['hybrid'])
        self.assertEqual(self.c.last['display_mode'],'hybrid')
        self.assertLess(math.dist(self.c.last['filtered'],(2.,2.)),2.)
        response=self.c.control({'action':'evaluate','x':2.,'y':2.})
        self.assertIsNone(response['geometry_error_m'])
        self.assertGreaterEqual(response['hybrid_error_m'],0.)
        self.assertEqual(len(self.c.hybrid_store.refs),9,'Testing must not train itself')
        self.assertTrue(Path(self.c.predpath).exists())
    def test_bssid_change_rejected(self):
        self.do_import()
        for a in IDS:self.c.accept(self.packet(a,3.,3.,bssid='00:11:22:33:44:55'))
        with self.assertRaisesRegex(ValueError,'BSSID'):
            self.c.control({'action':'start_live'})
    def test_import_validation_does_not_replace_training(self):
        self.do_import()
        failed=self.root/'wrong.csv'
        data=self.csv.read_text().replace(BSSID,'11:22:33:44:55:66')
        failed.write_text(data)
        with self.assertRaisesRegex(ValueError,'BSSID'):
            self.c.control({'action':'import_hybrid_csv','path':str(failed),'geometry_confirmed':True})
        self.assertEqual(len(self.c.hybrid_store.refs),9)
    def test_three_anchor_mode_hybrid(self):
        self.do_import()
        self.c.control({'action':'set_reliability','excluded_anchor':'L3','adaptive_weights':True})
        for a in ('L1','L2','L4'):self.c.accept(self.packet(a,3.,2.))
        self.c.control({'action':'start_live'})
        for a in ('L1','L2','L4'):self.c.accept(self.packet(a,3.,2.))
        self.assertIsNotNone(self.c.last.get('hybrid'))
        self.assertEqual(self.c.last['active_anchors'],['L1','L2','L4'])
    def test_geometry_mode_is_not_silent_fallback(self):
        self.do_import()
        self.c.control({'action':'set_display_mode','display_mode':'geometry'})
        for a in IDS:self.c.accept(self.packet(a,3.,2.))
        with self.assertRaisesRegex(ValueError,'CALIB khoảng cách'):
            self.c.control({'action':'start_live'})
        self.c.control({'action':'set_display_mode','display_mode':'hybrid'})
    def test_hybrid_reference_store_geo(self):
        store=HybridReferenceStore()
        ref={'xyz':[1,1,.8],'rssi':{a:-55 for a in IDS},'bssid':BSSID}
        store.append(ref,DEFAULT_LAYOUT)
        self.assertEqual(store.summary(DEFAULT_LAYOUT)['points'],1)
        with self.assertRaisesRegex(ValueError,'BSSID'):
            store.append({**ref,'xyz':[2,2,.8],'bssid':'00:00:00:00:00:00'},DEFAULT_LAYOUT,bssid=BSSID)

if __name__=='__main__':unittest.main()
