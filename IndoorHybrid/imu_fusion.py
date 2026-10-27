"""Experimental PDR prior from Sensor Logger HTTP Push.

Important constraints:
- Phone must stay approximately aligned with direction of walking.
- A user-alignable yaw offset is required before PDR can affect localization.
- No integration of acceleration twice: only conservative step counting.
- IMU motion is a SOFT prior on the RSSI likelihood, never ground truth.
- When orientation, transport, or timestamps are unhealthy, revert to RSSI-only.
"""
from __future__ import annotations
from collections import deque
import math
import time


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class ImuTracker:
    def __init__(self):
        self.enabled = False
        self.stride_m = 0.62
        self.heading_offset_deg = None
        self.last_yaw_deg = None
        self.last_yaw_received = None
        self.last_received = None
        self.last_acc_ns = -1
        self.last_ori_ns = -1
        self.acc_baseline = None
        self.prev_dynamic = 0.0
        self.last_step_ns = -10**20
        self.steps = deque(maxlen=500)
        self.step_count = 0
        self.last_device_id = None
        self.last_session_id = None
        self.received_batches = 0
        self.rejected_batches = 0
        self.recent_badness = ''
        self.last_message_id = -1

    @property
    def ready(self):
        return self.enabled and self.heading_offset_deg is not None and self.last_yaw_deg is not None

    def fresh(self, now=None):
        now = time.monotonic() if now is None else now
        return self.last_received is not None and now - self.last_received <= 2.5

    def configure(self, enabled=None, stride_m=None):
        if enabled is not None:
            if type(enabled) is not bool:
                raise ValueError('enabled phải là boolean.')
            self.enabled = enabled
        if stride_m is not None:
            stride = float(stride_m)
            if not math.isfinite(stride) or not 0.25 <= stride <= 1.1:
                raise ValueError('Chiều dài bước chỉ hỗ trợ 0.25–1.10 m.')
            self.stride_m = stride
        return self.status()

    def align(self, map_angle_deg):
        angle = float(map_angle_deg)
        if not math.isfinite(angle) or not -360 <= angle <= 360:
            raise ValueError('Hướng trên bản đồ phải là số độ hữu hạn.')
        if not self.fresh() or self.last_yaw_deg is None or self.last_yaw_received is None:
            raise ValueError('Chưa nhận orientation (yaw) mới từ iPhone.')
        if time.monotonic() - self.last_yaw_received > 2.5:
            raise ValueError('Dữ liệu hướng quay đã cũ.')
        self.heading_offset_deg = angle - self.last_yaw_deg
        self.steps.clear()
        self.step_count = 0
        return self.status()

    def heading_deg(self):
        if self.heading_offset_deg is None or self.last_yaw_deg is None:
            return None
        return (self.last_yaw_deg + self.heading_offset_deg) % 360.

    def _orientation(self, item, now):
        stamp = item.get('time')
        if not isinstance(stamp, int) or stamp <= self.last_ori_ns or abs(time.time_ns()-stamp)>10_000_000_000:
            return
        values = item.get('values')
        if not isinstance(values, dict):
            return
        yaw = values.get('yaw')
        if not isinstance(yaw, (int, float)) or not math.isfinite(yaw):
            return
        # Sensor Logger iOS orientation yaw in radians.
        if abs(yaw) > 7:
            self.recent_badness = 'Yaw ngoài phạm vi radian; kiểm tra ứng dụng gửi cảm biến.'
            return
        self.last_yaw_deg = math.degrees(float(yaw))
        self.last_ori_ns = stamp
        self.last_yaw_received = now

    def _accelerometer(self, item):
        stamp = item.get('time')
        if not isinstance(stamp, int) or stamp <= self.last_acc_ns or abs(time.time_ns()-stamp)>10_000_000_000:
            return
        values = item.get('values')
        if not isinstance(values, dict):
            return
        try:
            x,y,z=(float(values[k]) for k in ('x','y','z'))
        except (KeyError,TypeError,ValueError):
            return
        if not all(math.isfinite(v) for v in (x,y,z)):
            return
        magnitude = math.sqrt(x*x+y*y+z*z)
        if not .3 <= magnitude <= 80.:
            return
        self.last_acc_ns = stamp
        # Normalize relative to observed resting gravity magnitude: compatible
        # with sensors reported either as g or m/s^2, no integration drift.
        if self.acc_baseline is None:
            self.acc_baseline = magnitude
            return
        old_base = self.acc_baseline
        dynamic = (magnitude-old_base)/max(.3,old_base)
        self.acc_baseline = .985*old_base+.015*magnitude
        # Detect rising impacts; 0.36–1.2 s inter-step interval. Slow walking
        # or pocket orientation can require adjustment after real phone tests.
        if self.prev_dynamic <= .17 and dynamic > .17 and stamp-self.last_step_ns >= 360_000_000:
            self.last_step_ns = stamp
            if self.ready:
                heading = math.radians(self.heading_deg())
                self.steps.append((stamp, self.stride_m*math.cos(heading),
                                   self.stride_m*math.sin(heading)))
                self.step_count += 1
        self.prev_dynamic = dynamic

    def ingest(self, packet):
        if not isinstance(packet,dict) or not isinstance(packet.get('payload'),list):
            raise ValueError('Sensor Logger cần JSON có payload dạng danh sách.')
        if len(packet['payload'])>5000:
            raise ValueError('Gói IMU quá lớn.')
        device_id=str(packet.get('deviceId',''))[:100]
        sess_id=str(packet.get('sessionId',''))[:100]
        if self.last_device_id is not None and device_id!=self.last_device_id:
            self.heading_offset_deg=None
            self.steps.clear()
            self.step_count=0
            self.last_ori_ns=-1
            self.last_acc_ns=-1
            self.acc_baseline=None
        if self.last_session_id is not None and sess_id!=self.last_session_id:
            # Recalibrate yaw after a new recording/reference frame.
            self.heading_offset_deg=None
            self.steps.clear()
            self.step_count=0
            self.last_ori_ns=-1
            self.last_acc_ns=-1
            self.acc_baseline=None
            self.prev_dynamic=0
        self.last_device_id=device_id
        self.last_session_id=sess_id
        self.received_batches+=1
        now=time.monotonic()
        for p in sorted(packet['payload'], key=lambda k: k.get('time',0) if isinstance(k,dict) else 0):
            if not isinstance(p,dict):continue
            name=p.get('name')
            if name=='orientation':self._orientation(p,now)
            elif name=='accelerometer':self._accelerometer(p)
        self.last_received=now
        return self.status()

    def displacement(self, first_step_seq):
        """Return integrated steps since last wifi snapshot when recent and aligned.

        first_step_seq is a monotonic COUNT of recognized steps; assume all
        entries in the bounded queue represent newer indices.
        """
        if not (self.ready and self.fresh() and
                self.last_yaw_received is not None and time.monotonic()-self.last_yaw_received<=2.5):
            return {'used':False, 'dx':0.,'dy':0.,'steps':0,'step_seq':self.step_count}
        new_steps=max(0,self.step_count-int(first_step_seq))
        if new_steps>len(self.steps):
            # Too many steps to reconstruct after an outage.
            return {'used':False,'dx':0.,'dy':0.,'steps':0,'step_seq':self.step_count}
        chosen=list(self.steps)[-new_steps:] if new_steps else []
        dx=sum(p[1] for p in chosen)
        dy=sum(p[2] for p in chosen)
        if math.hypot(dx,dy)>8:
            return {'used':False,'dx':0.,'dy':0.,'steps':0,'step_seq':self.step_count}
        return {'used':True,'dx':dx,'dy':dy,'steps':new_steps,'step_seq':self.step_count}

    def status(self):
        age=round(time.monotonic()-self.last_received,2) if self.last_received else None
        heading=self.heading_deg()
        return {'enabled':self.enabled,'ready':self.ready,'fresh':self.fresh(),
                'age_s':age,'steps':self.step_count,'stride_m':self.stride_m,
                'heading_deg':round(heading,1) if heading is not None else None,
                'yaw_deg':round(self.last_yaw_deg,1) if self.last_yaw_deg is not None else None,
                'heading_aligned':self.heading_offset_deg is not None,
                'batches':self.received_batches,'device_id':self.last_device_id,
                'session_id':self.last_session_id,'diagnostic':self.recent_badness}
