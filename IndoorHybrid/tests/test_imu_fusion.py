"""IMU integration: synthetic-only tests, no claims of phone hardware validation."""
import asyncio
import json
import math
import time
import numpy as np
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from imu_fusion import ImuTracker
from hybrid_engine import HybridOnlinePipeline
from core import DEFAULT_LAYOUT
from collector import imu_http, Collector


def pack(samples, session='sessionA', device='iphoneA'):
    return {'messageId':12,'deviceId':device,'sessionId':session,
            'payload':samples}


def orientation(ns, yaw=0.):
    return {'name':'orientation','time':ns,'values':{'yaw':yaw,'qx':0,'qy':0,'qz':0,'qw':1}}


def accel(ns, a=9.81):
    return {'name':'accelerometer','time':ns,'values':{'x':0,'y':0,'z':a}}


class IMUTests(unittest.TestCase):
    def setUp(self):
        self.t=ImuTracker()
        self.ns=int(time.time()*1e9)
        self.t.ingest(pack([orientation(self.ns),accel(self.ns)]))

    def test_no_prior_without_optin_and_alignment(self):
        self.assertFalse(self.t.ready)
        self.assertFalse(self.t.displacement(0)['used'])
        self.t.configure(enabled=True)
        self.assertFalse(self.t.ready)
        self.t.align(0.)
        self.assertTrue(self.t.ready)

    def test_calibration_plus_x(self):
        self.t.configure(enabled=True)
        self.t.align(0.)
        self.assertAlmostEqual(self.t.heading_deg(),0.)
        self.t.ingest(pack([orientation(self.ns+100_000_000,math.pi/2)]))
        self.assertAlmostEqual(self.t.heading_deg(),90.,places=4)

    def test_step_with_magnitude_mss(self):
        self.t.configure(enabled=True,stride_m=.7)
        self.t.align(0.)
        batch=[]
        for i,magnitude in enumerate((9.81,12.7,9.81,9.81,12.9,9.81)):
            batch.append(accel(self.ns+(i+1)*400_000_000,magnitude))
        self.t.ingest(pack(batch))
        d=self.t.displacement(0)
        self.assertTrue(d['used'])
        self.assertEqual(d['steps'],2)
        self.assertAlmostEqual(d['dx'],1.4,places=4)
        self.assertAlmostEqual(d['dy'],0.,places=4)

    def test_step_with_unit_g(self):
        t=ImuTracker()
        t.ingest(pack([orientation(self.ns),accel(self.ns,1.)]))
        t.configure(enabled=True)
        t.align(90.)
        t.ingest(pack([accel(self.ns+400_000_000,1.30)]))
        d=t.displacement(0)
        self.assertEqual(d['steps'],1)
        self.assertAlmostEqual(d['dy'],.62,places=3)

    def test_duplicate_sensor_timestamps_ignored(self):
        self.t.configure(enabled=True)
        self.t.align(0.)
        self.t.ingest(pack([accel(self.ns+400_000_000,12.8)]))
        once=self.t.step_count
        self.t.ingest(pack([accel(self.ns+400_000_000,12.8)]))
        self.assertEqual(self.t.step_count,once)

    def test_new_recording_invalidates_yaw(self):
        self.t.configure(enabled=True)
        self.t.align(0.)
        self.t.ingest(pack([orientation(self.ns+10_000_000)],session='another'))
        self.assertFalse(self.t.ready)

    def test_missing_sensor_or_impossible_input(self):
        with self.assertRaises(ValueError):self.t.ingest({'no':'payload'})
        with self.assertRaises(ValueError):self.t.configure(stride_m=3.)
        self.t.ingest(pack([{'name':'accelerometer','time':self.ns+1,
                            'values':{'x':float('nan'),'y':0,'z':0}}]))
        self.assertEqual(self.t.step_count,0)

    def test_stale_fallback(self):
        self.t.configure(enabled=True);self.t.align(0.)
        self.t.last_received=time.monotonic()-4.
        self.assertFalse(self.t.displacement(0)['used'])

    def test_pipeline_uses_motion_as_soft_prior(self):
        # Stub model measures actual prior passed into the Bayesian estimator.
        class Model:
            def __init__(self):self.log=[]
            def estimate(self, rssi, active, prior_xy=None, prior_sigma=None, reliability=None):
                self.log.append((prior_xy.copy() if prior_xy is not None else None,prior_sigma))
                xy=[2.,2.] if prior_xy is None else list(prior_xy)
                return {'xy':np.asarray(xy,float),'global_xy':np.asarray([2.,2.]),
                        'alternative_xy':np.asarray([8.,5.]),
                        'gap':1.,'uncertainty_m':.3,'cost':1.}
        mod=Model()
        pipe=HybridOnlinePipeline(mod,DEFAULT_LAYOUT)
        now=time.monotonic()
        pipe.update({a:-50. for a in ('L1','L2','L3','L4')},now)
        imu=self.t
        imu.configure(enabled=True,stride_m=.7)
        imu.align(0.)
        imu.ingest(pack([accel(self.ns+400_000_000,12.8)]))
        pipe.update({a:-50. for a in ('L1','L2','L3','L4')},now+1.,imu=imu)
        self.assertIsNotNone(mod.log[-1][0])
        self.assertGreater(mod.log[-1][0][0],2.)
        self.assertGreaterEqual(mod.log[-1][1],1.)


class IMUHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_post_sensor_logger_schema(self):
        class State:
            imu=ImuTracker()
        state=State()
        server=await asyncio.start_server(lambda r,w:imu_http(r,w,state),'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        try:
            r,w=await asyncio.open_connection('127.0.0.1',port)
            packet=pack([orientation(int(time.time()*1e9)),accel(int(time.time()*1e9))])
            body=json.dumps(packet).encode()
            request=(b'POST /imu HTTP/1.1\r\nHost: localhost\r\n'
                     +b'Content-Type: application/json\r\n'
                     +f'Content-Length: {len(body)}\r\n\r\n'.encode()+body)
            w.write(request);await w.drain()
            response=await r.read()
            self.assertIn(b'200 OK',response)
            self.assertEqual(state.imu.received_batches,1)
            w.close();await w.wait_closed()
        finally:
            server.close();await server.wait_closed()

    async def test_http_rejects_wrong_path(self):
        class State:
            imu=ImuTracker()
        server=await asyncio.start_server(lambda r,w:imu_http(r,w,State()),'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        try:
            r,w=await asyncio.open_connection('127.0.0.1',port)
            w.write(b'POST /wrong HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}')
            await w.drain()
            self.assertIn(b'404',await r.read())
            w.close();await w.wait_closed()
        finally:server.close();await server.wait_closed()

if __name__=='__main__':unittest.main()
