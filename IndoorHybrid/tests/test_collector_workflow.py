"""Collector end-to-end *software* tests using manufactured RSSI, NOT field trials."""
import math,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import collector
from core import IDS,DEFAULT_LAYOUT
BSSID='aa:bb:cc:dd:ee:ff'

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.p1=patch.object(collector,'ROOT',self.root);self.p2=patch.object(collector,'STATE',self.root/'config'/'state.json')
        self.p1.start();self.p2.start();self.s=collector.Collector('test_session');self.s.display_mode='geometry'
        self.nseq={i:0 for i in IDS}
    def tearDown(self):
        self.s.close();self.p2.stop();self.p1.stop();self.tmp.cleanup()
    def packet(self,a,rssi,mode='real',bssid=BSSID):
        self.nseq[a]+=1
        return {'protocol_version':2,'type':'measurement','session':'test_session',
                'anchor_id':a,'sequence':self.nseq[a], 'rssi_dbm':rssi,
                'measurement_mode':mode,'bssid':bssid,'hostname':'TEST SYNTHETIC'}
    def send_at(self,x,y):
        for a in IDS:
            d=math.dist([x,y,.8],DEFAULT_LAYOUT['anchors'][a]);r=-42.-22*math.log10(d)
            # pass via real-structure packets for TEST ONLY, never under user-facing simulation
            self.s.accept(self.packet(a,r))
            if self.s.cal_task:self.s.cal_task['last'][a]=time.monotonic()-1
    def test_a_reject_simulation(self):
        with self.assertRaisesRegex(ValueError,'Simulation'):
            self.s.accept(self.packet('L1',-60,mode='simulation'))
    def test_b_session(self):
        p=self.packet('L1',-60);p['session']='other'
        with self.assertRaises(ValueError):self.s.accept(p)
    def test_c_full_calibration_live_and_eval(self):
        self.send_at(3,2)
        for x,y in ((3.,2.),(7.,4.)):
            r=self.s.control({'action':'cal_all','x':x,'y':y,'z':.8,'samples':4})
            self.assertEqual(set(r['targets']),set(IDS))
            for _ in range(5):
                # allow valid calibration samples without any real wait
                self.s.cal_task['start']=time.monotonic()-1
                for a in IDS:self.s.cal_task['last'][a]=time.monotonic()-1
                self.send_at(x,y)
                if self.s.mode=='IDLE':break
            self.assertEqual(self.s.mode,'IDLE')
        self.assertTrue(all(self.s.cal.fit(i)['points']==2 for i in IDS))
        self.s.control({'action':'start_live'})
        self.send_at(5.,3.)
        self.assertTrue(self.s.last)
        self.assertLess(math.dist(self.s.last['raw'],[5.,3.]),.05)
        self.assertLess(math.dist(self.s.last['filtered'],[5.,3.]),.05)
        e=self.s.control({'action':'evaluate','x':5.,'y':3.})
        self.assertLess(e['error_filtered_m'],.05)
        # ensure changing anchor invalidates old calibration
        self.s.control({'action':'stop_live'})
        layout=dict(DEFAULT_LAYOUT);layout['anchors']=dict(DEFAULT_LAYOUT['anchors'])
        layout['anchors']['L2']=[9.,0.,.8]
        self.s.control({'action':'set_layout','layout':layout})
        self.assertTrue(all(not self.s.cal.refs[i] for i in IDS))
    def test_e_calibrate_one_anchor_offline_others(self):
        self.s.accept(self.packet('L3',-59))
        r=self.s.control({'action':'cal_one','anchor':'L3','distance':3.,'samples':4})
        self.assertEqual(list(r['targets']),['L3'])
        for _ in range(4):
            self.s.cal_task['start']=time.monotonic()-1
            self.s.cal_task['last']['L3']=time.monotonic()-1
            self.s.accept(self.packet('L3',-59))
        self.assertEqual(self.s.mode,'IDLE')
        self.assertEqual(self.s.cal.fit('L3')['points'],1)
        self.assertFalse(self.s.cal.refs['L1'])
    def test_d_different_bssid(self):
        self.send_at(3,2)
        self.s.accept(self.packet('L1',-53,bssid='00:11:22:33:44:55'))
        self.assertIn('BSSID',self.s.age_check(time.monotonic()))

if __name__=='__main__':unittest.main()
