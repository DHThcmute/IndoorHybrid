"""Wi-Fi RSSI collector, online range calibration, four-range localization.
Compatible with IndoorSystem v2 anchor clients (port 8765); master local IPC 8766.
Neither historic room measurements nor fake positions are used for LIVE.
"""
from __future__ import annotations
import argparse,asyncio,csv,datetime,json,math,re,time,statistics
from collections import deque
from pathlib import Path
from core import IDS,DEFAULT_LAYOUT,RangeCalibration,OnlineRangePipeline,validate_layout
from hybrid_engine import HybridReferenceStore,HybridBayesianModel,HybridOnlinePipeline
from imu_fusion import ImuTracker
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'config'/'state.json'

def clock():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')
def newlog(prefix,headers):
    path=ROOT/'data'/f'{prefix}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('w',encoding='utf-8',newline='',buffering=1)
    w=csv.DictWriter(f,headers);w.writeheader()
    return f,w,str(path)

class Collector:
    def __init__(self,session):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',session):raise ValueError('Invalid session')
        self.session=session;self.mode='IDLE';self.live={};self.seq={};self.warnings=deque(maxlen=8)
        self.layout=DEFAULT_LAYOUT.copy();self.cal=RangeCalibration()
        self.hybrid_store=HybridReferenceStore();self.hybrid_model=None;self.hybrid_pipe=None
        self.hybrid_trained=False;self.display_mode="hybrid";self.hybrid_issue="Chưa xây dựng mô hình."
        self.excluded_anchor=None;self.adaptive_weights=True;self.imu=ImuTracker();self.load_state()
        self.pipe=self.new_pipe()
        if self.hybrid_trained:self.rebuild_hybrid()
        self.last={};self.last_time=0.;self.last_seq={};self.cal_task=None;self.stop=asyncio.Event()
        self.rssi_hist={a:deque(maxlen=3) for a in IDS}
        self.max_age=2.7;self.max_skew=1.8
        self.rfile,self.rwriter,self.rawpath=newlog('rssi_raw',
            ['utc','anchor_id','rssi_dbm','bssid','sequence','session','hostname'])
        self.pfile,self.pwriter,self.predpath=newlog('positions_live',
            ['utc','session','x_raw','y_raw','x_filtered','y_filtered','rssi_L1','rssi_L2','rssi_L3','rssi_L4',
             'd_L1','d_L2','d_L3','d_L4','range_rmse_m','nis','gate','max_anchor_age_s',
             'weight_L1','weight_L2','weight_L3','weight_L4','quality_L1','quality_L2','quality_L3','quality_L4',
             'excluded_anchor','adaptive_weights',
             'display_mode','geometry_x_raw','geometry_y_raw','geometry_x_filtered','geometry_y_filtered',
             'hybrid_x_raw','hybrid_y_raw','hybrid_x_filtered','hybrid_y_filtered',
             'hybrid_uncertainty_m','hybrid_gate','hybrid_model_cost','hybrid_status',
             'imu_enabled','imu_fresh','imu_fused','imu_step_count','imu_steps_since_wifi',
             'imu_heading_deg','imu_prior_x','imu_prior_y'])
        self.efile,self.ewriter,self.evalpath=newlog('evaluation',
            ['utc','snapshot_utc','x_true','y_true','x_raw','y_raw','x_filtered','y_filtered',
             'error_raw_m','error_filtered_m','excluded_anchor','adaptive_weights','active_anchors',
             'max_anchor_age_s','range_rmse_m','gate','nis','calibrated_bssid',
             'weight_L1','weight_L2','weight_L3','weight_L4',
             'quality_L1','quality_L2','quality_L3','quality_L4',
             'display_mode','geometry_error_m','hybrid_error_m','hybrid_uncertainty_m',
             'imu_fused','imu_step_count','imu_heading_deg'])
    def active_ids(self):
        return tuple(a for a in IDS if a!=self.excluded_anchor)
    def new_pipe(self):
        return OnlineRangePipeline(self.layout,self.cal,self.excluded_anchor,self.adaptive_weights)
    def rebuild_hybrid(self):
        """Fit only from user-confirmed physical reference sites, never test coordinates."""
        self.hybrid_model=None;self.hybrid_pipe=None
        summary=self.hybrid_store.summary(self.layout)
        if not summary['ready']:
            self.hybrid_issue=summary['warning'];self.hybrid_trained=False
            return False
        self.hybrid_store.validate_all(self.layout,self.cal.bssid)
        self.hybrid_model=HybridBayesianModel(self.layout,lengthscale=3.5,alpha=1.5,grid_step=.2)
        self.hybrid_model.fit(self.hybrid_store.refs)
        self.hybrid_pipe=HybridOnlinePipeline(self.hybrid_model,self.layout,self.excluded_anchor,self.adaptive_weights)
        self.hybrid_trained=True;self.hybrid_issue='Mô hình đã sẵn sàng.'
        return True

    def add_hybrid_reference(self,ref):
        if self.hybrid_store.refs and ref['bssid']!=self.hybrid_store.refs[0]['bssid']:
            raise ValueError('BSSID khác mốc Hybrid cũ. Phải xoá mốc Hybrid để đo lại.')
        count=self.hybrid_store.append(ref,self.layout,self.cal.bssid)
        # Previously fitted model remains only as a snapshot; explicit retrain
        # prevents silently changing likelihood parameters during a live test.
        self.hybrid_trained=False;self.hybrid_model=None;self.hybrid_pipe=None
        self.hybrid_issue='Có mốc mới: bấm XÂY MÔ HÌNH để cập nhật.'
        self.save()
        return count

    def import_hybrid_csv(self,path,geometry_confirmed=False):
        """Explicit import, only on localhost; no auto-activation of historical CSV."""
        p=Path(path).expanduser().resolve()
        if not geometry_confirmed:raise ValueError('Bạn phải xác nhận hình học và BSSID nguồn trước khi nhập.')
        if not p.is_file() or p.suffix.lower()!='.csv' or p.stat().st_size>15_000_000:
            raise ValueError('Chọn file CSV hợp lệ (<15 MB).')
        import csv as _csv
        groups={};bssids=set()
        with p.open(encoding='utf-8-sig',newline='') as f:
            for row in _csv.DictReader(f):
                if len(groups)>1000:raise ValueError('Dữ liệu quá nhiều điểm; hãy chỉ nhập mốc hiệu chuẩn.')
                aid=row.get('anchor_id')
                if aid not in IDS:continue
                pid=row.get('point_id') or row.get('site_id')
                if not pid:raise ValueError('CSV phải có point_id hoặc site_id.')
                b=(row.get('bssid') or '').strip().lower()
                if not b:raise ValueError('CSV cần BSSID để ngăn trộn phiên phát.')
                bssids.add(b)
                if len(bssids)>1:raise ValueError('CSV chứa nhiều BSSID; phải làm sạch trước.')
                x=float(row.get('x_true_m',row.get('x','nan')))
                y=float(row.get('y_true_m',row.get('y','nan')))
                z=float(row.get('z_true_m',row.get('z',self.layout['phone_z'])))
                r=float(row.get('rssi_dbm',row.get('rssi_med','nan')))
                if not math.isfinite(r) or not -110<=r<=0:raise ValueError('RSSI CSV ngoài phạm vi.')
                if row.get('orientation_deg') and abs(float(row['orientation_deg']))>1e-4:
                    raise ValueError('CSV chứa nhiều hướng iPhone: chỉ nhập 0 độ trong giai đoạn này.')
                group=groups.setdefault(pid,{'coords':set(),'values':{a:[] for a in IDS}})
                group['coords'].add((x,y,z));group['values'][aid].append(r)
        bssid=next(iter(bssids)) if bssids else None
        if self.cal.bssid and bssid!=self.cal.bssid:raise ValueError('BSSID CSV KHÁC BSSID CALIB hiện tại.')
        if self.hybrid_store.refs and bssid!=self.hybrid_store.refs[0]['bssid']:
            raise ValueError('BSSID CSV khác các mốc Hybrid hiện có.')
        if len(groups)<8:raise ValueError('CSV có dưới 8 mốc hợp lệ.')
        refs=[]
        for pid,g in groups.items():
            if len(g['coords'])!=1:raise ValueError('Một point_id chứa nhiều tọa độ.')
            if any(len(g['values'][aid])<1 for aid in IDS):
                raise ValueError(f'Thiếu RSSI bốn anchor ở {pid}.')
            x,y,z=next(iter(g['coords']))
            ref={'xyz':[x,y,z],'rssi':{a:statistics.median(g['values'][a]) for a in IDS},
                 'bssid':bssid,'n':min(len(g['values'][a]) for a in IDS),'source':'CSV_MANUAL'}
            refs.append(ref)
        # Validate entire new dataset *before* mutating the existing stored model.
        from hybrid_engine import validate_reference
        clean=[validate_reference(r,self.layout,self.cal.bssid) for r in refs]
        self.hybrid_store=HybridReferenceStore(clean)
        self.hybrid_trained=False;self.hybrid_model=None;self.hybrid_pipe=None
        self.hybrid_issue='CSV đã nạp. Nhấn XÂY MÔ HÌNH.'
        self.save()
        return len(clean)

    def warn(self,message):
        if not self.warnings or self.warnings[-1]!=message:self.warnings.append(message);print('[WARN]',message,flush=True)
    def load_state(self):
        try:
            obj=json.loads(STATE.read_text(encoding='utf-8'))
            self.layout=validate_layout(obj['layout']);self.cal=RangeCalibration.from_json(obj['calibration'])
            settings=obj.get('reliability',{})
            self.excluded_anchor=settings.get('excluded_anchor')
            if self.excluded_anchor not in (None,*IDS):self.excluded_anchor=None
            self.adaptive_weights=bool(settings.get('adaptive_weights',True))
            self.hybrid_store=HybridReferenceStore(obj.get('hybrid_refs',[]))
            self.hybrid_store.validate_all(self.layout,self.cal.bssid)
            self.hybrid_trained=bool(obj.get('hybrid_trained',False))
            self.display_mode=str(obj.get('display_mode','hybrid'))
            imu_settings=obj.get('imu',{})
            self.imu.configure(enabled=bool(imu_settings.get('enabled',False)),
                               stride_m=float(imu_settings.get('stride_m',.62)))
            if self.display_mode not in ('geometry','hybrid'):self.display_mode='geometry'
        except (OSError,ValueError,TypeError,KeyError):
            self.layout=validate_layout(DEFAULT_LAYOUT);self.cal=RangeCalibration()
            self.excluded_anchor=None;self.adaptive_weights=True
            self.hybrid_store=HybridReferenceStore();self.hybrid_trained=False
            self.display_mode='hybrid'
    def save(self):
        STATE.parent.mkdir(exist_ok=True,parents=True)
        tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps({'layout':self.layout,'calibration':self.cal.to_json(),
                         'reliability':{'excluded_anchor':self.excluded_anchor,
                                        'adaptive_weights':self.adaptive_weights},
                         'hybrid_refs':self.hybrid_store.refs,
                         'hybrid_trained':self.hybrid_trained,'display_mode':self.display_mode,
                         'imu':{'enabled':self.imu.enabled,'stride_m':self.imu.stride_m}},
                         ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATE)
    def close(self):
        self.save()
        for f in (self.rfile,self.pfile,self.efile):f.close()
    def age_check(self,now,required=None):
        active=tuple(required or self.active_ids())
        if any(i not in self.live for i in active):return 'Chưa đủ RSSI từ các anchor đang sử dụng.'
        if any(now-self.live[i]['at']>self.max_age for i in active):return 'RSSI quá cũ: mất hoặc trễ một anchor đang sử dụng.'
        if max(self.live[i]['at'] for i in active)-min(self.live[i]['at'] for i in active)>self.max_skew:
            return 'Các RSSI đang dùng không đủ đồng thời.'
        bssids={self.live[i]['bssid'] for i in active}
        if len(bssids)!=1:return 'BSSID của bốn laptop không giống nhau.'
        if self.display_mode=='geometry' and self.cal.bssid and next(iter(bssids))!=self.cal.bssid:
            return 'Hotspot BSSID thay đổi so với hiệu chuẩn. Cần hiệu chuẩn lại.'
        if self.display_mode=='hybrid' and self.hybrid_store.refs and next(iter(bssids))!=self.hybrid_store.refs[0]['bssid']:
            return 'BSSID khác mô hình Hybrid. Phải huấn luyện lại cho hotspot hiện tại.'
        return None
    def accept(self,msg):
        if not isinstance(msg,dict) or msg.get('protocol_version')!=2 or msg.get('type')!='measurement':
            raise ValueError('Invalid measurement v2')
        aid=msg.get('anchor_id')
        if aid not in IDS or msg.get('session')!=self.session:raise ValueError('Bad anchor or session')
        if msg.get('measurement_mode')!='real':raise ValueError('Simulation packets forbidden')
        seq=msg.get('sequence')
        if type(seq)!=int or seq<1:raise ValueError('Invalid sequence')
        rssi=float(msg.get('rssi_dbm'))
        if not math.isfinite(rssi) or not -110<=rssi<=0:raise ValueError('Invalid RSSI')
        bssid=str(msg.get('bssid') or '').lower()
        if not re.fullmatch('[0-9a-f]{2}(:[0-9a-f]{2}){5}',bssid):raise ValueError('No valid BSSID')
        now=time.monotonic();old=self.live.get(aid)
        if seq<=self.seq.get(aid,0):
            if not old or now-old['at']<3 or seq>3:raise ValueError('Out of order')
        self.seq[aid]=seq
        if old is None or old['bssid']!=bssid:
            self.rssi_hist[aid].clear()
        self.rssi_hist[aid].append(rssi)
        self.live[aid]={'rssi':rssi,'bssid':bssid,'seq':seq,'at':now,'hostname':str(msg.get('hostname',''))[:100]}
        self.rwriter.writerow({'utc':clock(),'anchor_id':aid,'rssi_dbm':rssi,'bssid':bssid,
                               'sequence':seq,'session':self.session,'hostname':msg.get('hostname','')})
        if self.mode=='CAL':self.calibration_sample(aid,rssi,now)
        if self.mode=='LIVE':self.snapshot(now)
    def calibration_sample(self,aid,rssi,now):
        task=self.cal_task
        if task is None or aid not in task['targets'] or now<task['start']+.2:return
        if len(task['targets'])==4:
            if self.age_check(now,required=IDS):return
        elif self.cal.bssid and self.live[aid]['bssid']!=self.cal.bssid:
            return
        if now-task['last'][aid]<.55:return
        if len(task['samples'][aid])>=task['n']:return
        task['samples'][aid].append(float(rssi));task['last'][aid]=now
        if all(len(v)>=task['n'] for v in task['samples'].values()):
            bssid=self.live[next(iter(task['targets']))]['bssid']
            try:
                for name,dist in task['targets'].items():self.cal.add(name,dist,task['samples'][name],bssid)
                if task.get('xyz') is not None:
                    self.add_hybrid_reference({'xyz':task['xyz'],
                         'rssi':{a:statistics.median(task['samples'][a]) for a in IDS},
                         'bssid':bssid,'n':task['n'],'source':'CALIB'})
                self.save();self.warn('Hiệu chuẩn xong. ' + ', '.join(f'{i}:{self.cal.fit(i)["points"]} mốc' for i in task['targets']))
            except ValueError as e:self.warn('CAL ERROR: '+str(e))
            self.cal_task=None;self.mode='IDLE';self.pipe.reset()
    def snapshot(self,now):
        # Every LIVE prediction depends on fresh, independently measured RSSI.
        # Hybrid never requires RSSI->distance calibration or the legacy geometry solver.
        if self.age_check(now):return
        active=self.active_ids()
        if any(self.live[a]['seq']<=self.last_seq.get(a,0) for a in active):return
        if now-self.last_time<.4:return
        rssi={a:float(statistics.median(self.rssi_hist[a])) for a in active}
        self.last_seq={a:self.live[a]['seq'] for a in active}
        g=None;h=None
        geometry_ready=all(bool(self.cal.refs[a]) for a in active)
        if geometry_ready:
            try:g=self.pipe.update({a:self.live[a]['rssi'] for a in active},now)
            except (ValueError,RuntimeError,ArithmeticError) as exc:
                self.warn('Geometry: '+str(exc))
        if self.hybrid_pipe is not None:
            try:
                rel=({a:self.cal.quality(a,rssi[a])['score'] for a in active}
                     if geometry_ready else None)
                h=self.hybrid_pipe.update(rssi,now,reliability=rel,imu=self.imu if self.imu.enabled else None)
                self.hybrid_issue='Mô hình Hybrid đang chạy.'
            except (ValueError,RuntimeError,ArithmeticError) as exc:
                self.hybrid_issue=str(exc);self.warn('Hybrid: '+str(exc))
        selected=h if self.display_mode=='hybrid' else g
        if selected is None:
            # Never silently use geometry when HYBRID was explicitly selected.
            self.last={}
            return
        self.last_time=now
        status={a:self.cal.quality(a,rssi.get(a)) for a in IDS}
        weight={a:(g['weights'][a] if g else None) for a in IDS}
        ranges={a:(g['ranges_m'][i] if g else None) for i,a in enumerate(IDS)}
        record={'utc':clock(),'geometry':g,'hybrid':h,'display_mode':self.display_mode,
            'raw':selected['raw'],'filtered':selected['filtered'],
            'gate':selected['gate'],'nis':selected['nis'],
            'quality':status,'weights':weight,'ranges_m':[ranges[a] for a in IDS],
            'range_rmse_m':g['range_rmse_m'] if g else None,
            'active_anchors':list(active),'rssi_median':[rssi.get(a) for a in IDS],
            'hybrid_issue':self.hybrid_issue,
            'imu':self.imu.status(),
            'max_anchor_age_s':round(max(now-self.live[a]['at'] for a in active),2)}
        self.last=record
        self.pwriter.writerow({'utc':record['utc'],'session':self.session,
            'x_raw':record['raw'][0],'y_raw':record['raw'][1],
            'x_filtered':record['filtered'][0],'y_filtered':record['filtered'][1],
            **{f'rssi_{a}':rssi.get(a) for a in IDS},
            **{f'd_{a}':ranges[a] for a in IDS},
            'range_rmse_m':record['range_rmse_m'],'nis':record['nis'],'gate':record['gate'],
            'max_anchor_age_s':record['max_anchor_age_s'],
            **{f'weight_{a}':weight[a] for a in IDS},
            **{f'quality_{a}':status[a]['score'] for a in IDS},
            'excluded_anchor':self.excluded_anchor or '',
            'adaptive_weights':self.adaptive_weights,
            'display_mode':self.display_mode,
            'geometry_x_raw':g['raw'][0] if g else None,
            'geometry_y_raw':g['raw'][1] if g else None,
            'geometry_x_filtered':g['filtered'][0] if g else None,
            'geometry_y_filtered':g['filtered'][1] if g else None,
            'hybrid_x_raw':h['raw'][0] if h else None,
            'hybrid_y_raw':h['raw'][1] if h else None,
            'hybrid_x_filtered':h['filtered'][0] if h else None,
            'hybrid_y_filtered':h['filtered'][1] if h else None,
            'hybrid_uncertainty_m':h['uncertainty_m'] if h else None,
            'hybrid_gate':h['gate'] if h else None,
            'hybrid_model_cost':h['model_cost'] if h else None,
            'hybrid_status':self.hybrid_issue,
            'imu_enabled':self.imu.enabled,
            'imu_fresh':self.imu.fresh(),
            'imu_fused':h.get('imu_fused',False) if h else False,
            'imu_step_count':self.imu.step_count,
            'imu_steps_since_wifi':h.get('imu_steps_since_wifi',0) if h else 0,
            'imu_heading_deg':self.imu.heading_deg(),
            'imu_prior_x':h['imu_prior_xy'][0] if h and h.get('imu_prior_xy') else None,
            'imu_prior_y':h['imu_prior_xy'][1] if h and h.get('imu_prior_xy') else None})

    def status(self):
        now=time.monotonic()
        issue=self.age_check(now)
        if issue and self.mode=='LIVE':self.warn(issue)
        anchors={a:{**{k:self.live[a][k] for k in ('rssi','bssid','hostname','seq')},
                    'age_s':round(now-self.live[a]['at'],2),'fresh':now-self.live[a]['at']<=self.max_age}
                 if a in self.live else {'rssi':None,'age_s':None,'fresh':False} for a in IDS}
        last=self.last if self.mode=='LIVE' and not issue and self.last and now-self.last_time<=3 else None
        task=None
        if self.cal_task:
            task={'n':self.cal_task['n'],'counts':{a:len(v) for a,v in self.cal_task['samples'].items()},
                  'targets':self.cal_task['targets']}
        return {'session':self.session,'mode':self.mode,'layout':self.layout,
                'anchors':anchors,'calibration':{i:self.cal.fit(i) for i in IDS},
                'quality':{i:self.cal.quality(i,self.live[i]['rssi'] if i in self.live else None) for i in IDS},
                'reliability':{'excluded_anchor':self.excluded_anchor,'adaptive_weights':self.adaptive_weights,
                               'active_anchors':list(self.active_ids())},
                'calibrated_bssid':self.cal.bssid,
                'last':last,'cal_task':task,'issue':issue,'warnings':list(self.warnings),
                'paths':{'live':self.predpath,'raw':self.rawpath,'evaluation':self.evalpath},
                'hybrid':{**self.hybrid_store.summary(self.layout),
                          'trained':bool(self.hybrid_pipe),'message':self.hybrid_issue},
                'display_mode':self.display_mode,
                'imu':self.imu.status()}
    def control(self,cmd):
        action=cmd.get('action')
        if action=='status':return {'ok':True,**self.status()}
        if action=='set_imu':
            if self.mode!='IDLE':raise ValueError('STOP LIVE trước khi đổi chế độ IMU.')
            status=self.imu.configure(enabled=cmd.get('enabled'),stride_m=cmd.get('stride_m'))
            if self.hybrid_pipe:self.hybrid_pipe.reset()
            self.last={};self.last_seq={}
            self.save()
            return {'ok':True,'imu':status}
        if action=='align_imu':
            if self.mode!='IDLE':raise ValueError('STOP LIVE trước khi căn hướng IMU.')
            status=self.imu.align(cmd.get('map_angle_deg',0.))
            if self.hybrid_pipe:self.hybrid_pipe.reset()
            self.last={};self.last_seq={}
            return {'ok':True,'imu':status}
        if action=='set_layout':
            if self.mode!='IDLE':raise ValueError('DỪNG LIVE/CAL trước khi đổi sơ đồ.')
            new=validate_layout(cmd['layout'])
            if new['anchors']!=self.layout['anchors'] or new['phone_z']!=self.layout['phone_z']:
                self.cal.clear();self.hybrid_store.clear();self.hybrid_pipe=None
                self.hybrid_model=None;self.hybrid_trained=False;self.display_mode='hybrid'
                self.warn('Đã xóa CALIB và HYBRID do thay đổi hình học/chiều cao.')
            if new['polygon']!=self.layout['polygon']:
                self.hybrid_store.clear();self.hybrid_pipe=None;self.hybrid_model=None
                self.hybrid_trained=False;self.display_mode='hybrid'
            self.layout=new;self.pipe=self.new_pipe();self.save()
            return {'ok':True,'calibration_cleared':all(not self.cal.refs[k] for k in IDS)}
        if action=='set_reliability':
            if self.mode!='IDLE':raise ValueError('STOP LIVE/CAL trước khi đổi độ tin cậy.')
            exclude=cmd.get('excluded_anchor')
            if exclude in ('','NONE','Không'):exclude=None
            if exclude is not None and exclude not in IDS:raise ValueError('Anchor loại trừ không hợp lệ.')
            adaptive=cmd.get('adaptive_weights',True)
            if not isinstance(adaptive,bool):raise ValueError('adaptive_weights phải là boolean.')
            self.excluded_anchor=exclude;self.adaptive_weights=adaptive
            self.pipe=self.new_pipe();self.last={};self.last_seq={}
            if self.hybrid_trained:self.rebuild_hybrid()
            self.save()
            return {'ok':True,'reliability':self.status()['reliability']}
        if action=='set_display_mode':
            mode=str(cmd.get('display_mode','geometry'))
            if mode not in ('geometry','hybrid'):raise ValueError('Chế độ không hợp lệ.')
            if mode=='hybrid' and not self.hybrid_pipe:
                raise ValueError(self.hybrid_issue+' Cần ít nhất 8 mốc X,Y để xây mô hình.')
            self.display_mode=mode;self.last={};self.last_seq={}
            self.save()
            # Existing snapshot remains unchanged until next genuine packet,
            # so a mode switch cannot fabricate fresh observation.
            return {'ok':True,'display_mode':mode}
        if action=='build_hybrid':
            if self.mode!='IDLE':raise ValueError('STOP LIVE/CAL trước khi xây mô hình.')
            count=self.hybrid_store.summary(self.layout)
            if not count['ready']:raise ValueError(count['warning'])
            self.rebuild_hybrid();self.save()
            return {'ok':True,'hybrid':self.status()['hybrid']}
        if action=='clear_hybrid':
            if self.mode!='IDLE':raise ValueError('STOP LIVE trước khi xóa Hybrid.')
            self.hybrid_store.clear();self.hybrid_pipe=None;self.hybrid_model=None
            self.hybrid_trained=False;self.display_mode='hybrid'
            self.hybrid_issue='Đã xóa mốc Hybrid.';self.save()
            return {'ok':True}
        if action=='import_hybrid_csv':
            if self.mode!='IDLE':raise ValueError('STOP LIVE/CAL trước khi nhập CSV.')
            n=self.import_hybrid_csv(cmd['path'],cmd.get('geometry_confirmed',False))
            return {'ok':True,'points_imported':n}
        if action=='clear_calibration':
            if self.mode!='IDLE':raise ValueError('DỪNG LIVE/CAL trước khi xóa.')
            self.cal.clear();self.pipe.reset();self.hybrid_store.clear()
            self.hybrid_model=None;self.hybrid_pipe=None;self.hybrid_trained=False
            self.display_mode='hybrid';self.save();return {'ok':True}
        if action in ('cal_all','cal_one'):
            if self.mode!='IDLE':raise ValueError('DỪNG LIVE trước khi CALIB.')
            if action=='cal_all':
                issue=self.age_check(time.monotonic(),required=IDS)
                if issue:raise ValueError(issue)
            else:
                selected=str(cmd.get('anchor'))
                entry=self.live.get(selected)
                if selected not in IDS or not entry or time.monotonic()-entry['at']>self.max_age:
                    raise ValueError('Anchor cần CALIB chưa gửi RSSI mới.')
            n=int(cmd.get('samples',8))
            if not 4<=n<=60:raise ValueError('Số mẫu hiệu chuẩn phải trong khoảng 4–60.')
            if action=='cal_all':
                x,y,z=float(cmd['x']),float(cmd['y']),float(cmd['z'])
                from core import in_polygon
                if not in_polygon((x,y),self.layout['polygon']):
                    raise ValueError('Mốc hiệu chuẩn ở ngoài tứ giác.')
                targets={a:math.dist([x,y,z],self.layout['anchors'][a]) for a in IDS}
            else:
                aid=str(cmd['anchor'])
                if aid not in IDS:raise ValueError('Anchor ID sai')
                targets={aid:float(cmd['distance'])}
            if any(not .3<=v<=150 for v in targets.values()):
                raise ValueError('Khoảng cách CALIB cần từ 0.3 đến 150 m.')
            observed={self.live[a]['bssid'] for a in targets}
            if self.cal.bssid and (len(observed)!=1 or next(iter(observed))!=self.cal.bssid):
                raise ValueError('BSSID thay đổi: XÓA CALIB rồi hiệu chuẩn lại.')
            if self.hybrid_store.refs and (len(observed)!=1 or next(iter(observed))!=self.hybrid_store.refs[0]['bssid']):
                raise ValueError('BSSID mới khác mốc Hybrid. Xóa mốc và huấn luyện lại.')
            self.cal_task={'targets':targets,'xyz':[x,y,z] if action=='cal_all' else None,
                           'n':n,'samples':{a:[] for a in targets},
                           'last':{a:0 for a in targets},'start':time.monotonic()}
            self.mode='CAL';return {'ok':True,'targets':targets,'samples':n}
        if action=='cancel_cal':
            if self.mode=='CAL':self.mode='IDLE';self.cal_task=None
            return {'ok':True}
        if action=='start_live':
            if self.mode!='IDLE':raise ValueError('DỪNG CAL trước khi START LIVE.')
            if self.display_mode=='geometry':
                if any(not self.cal.refs[i] for i in self.active_ids()):
                    raise ValueError('Chưa đủ CALIB khoảng cách cho chế độ Geometry.')
            elif self.hybrid_pipe is None:
                raise ValueError('Chưa có mô hình Hybrid: CALIB >=8 mốc và bấm XÂY MÔ HÌNH.')
            issue=self.age_check(time.monotonic())
            if issue:raise ValueError(issue)
            self.pipe=self.new_pipe();self.last={};self.last_seq={i:self.live[i]['seq'] for i in self.active_ids()}
            if self.hybrid_pipe:self.hybrid_pipe.reset()
            self.mode='LIVE';return {'ok':True}
        if action=='stop_live':
            if self.mode=='LIVE':self.mode='IDLE';self.last={};self.pipe.reset()
            if self.hybrid_pipe:self.hybrid_pipe.reset()
            return {'ok':True}
        if action=='evaluate':
            if self.mode!='LIVE' or not self.last or time.monotonic()-self.last_time>3:
                raise ValueError('Chưa có tọa độ LIVE mới.')
            from core import in_polygon
            x,y=float(cmd['x']),float(cmd['y'])
            if not in_polygon([x,y],self.layout['polygon']):raise ValueError('Tọa độ tham chiếu ngoài bản đồ.')
            r=self.last;raw=math.dist([x,y],r['raw']);filt=math.dist([x,y],r['filtered'])
            gerror=math.dist([x,y],r['geometry']['filtered']) if r['geometry'] else None
            herror=math.dist([x,y],r['hybrid']['filtered']) if r['hybrid'] else None
            self.ewriter.writerow({'utc':clock(),'snapshot_utc':r.get('utc',''),
                 'x_true':x,'y_true':y,
                 'x_raw':r['raw'][0],'y_raw':r['raw'][1],
                 'x_filtered':r['filtered'][0],'y_filtered':r['filtered'][1],
                 'error_raw_m':raw,'error_filtered_m':filt,
                 'excluded_anchor':self.excluded_anchor or '',
                 'adaptive_weights':self.adaptive_weights,
                 'active_anchors':','.join(r['active_anchors']),
                 'max_anchor_age_s':r.get('max_anchor_age_s'),
                 'range_rmse_m':r['range_rmse_m'],
                 'gate':r['gate'],'nis':r['nis'],
                 'calibrated_bssid':self.cal.bssid or '',
                 **{f'weight_{a}':r['weights'][a] for a in IDS},
                 **{f'quality_{a}':r['quality'][a]['score'] for a in IDS},
                 'display_mode':self.display_mode,'geometry_error_m':gerror,
                 'hybrid_error_m':herror,
                 'hybrid_uncertainty_m':r['hybrid']['uncertainty_m'] if r['hybrid'] else None,
                 'imu_fused':r['hybrid'].get('imu_fused',False) if r['hybrid'] else False,
                 'imu_step_count':self.imu.step_count,
                 'imu_heading_deg':self.imu.heading_deg()})
            return {'ok':True,'error_raw_m':round(raw,3),'error_filtered_m':round(filt,3),
                    'geometry_error_m':round(gerror,3) if gerror is not None else None,
                    'hybrid_error_m':round(herror,3) if herror is not None else None}
        if action=='shutdown':self.stop.set();return {'ok':True}
        raise ValueError('Invalid action')

async def one_packet(reader,writer,state,control=False):
    try:
        line=await asyncio.wait_for(reader.readline(),timeout=5)
        if len(line)>20000 or not line:raise ValueError('Bad frame')
        packet=json.loads(line)
        if control:
            if packet.get('protocol_version')!=2 or packet.get('type')!='control':raise ValueError('Bad control protocol')
            res=state.control(packet);response=json.dumps(res,ensure_ascii=False)+'\n'
        else:state.accept(packet);response='OK\n'
    except Exception as e:
        response=json.dumps({'ok':False,'error':str(e)})+'\n' if control else 'ERROR\n'
        print('[REJECT]',str(e),flush=True)
    try:writer.write(response.encode());await writer.drain()
    finally:writer.close();await writer.wait_closed()

async def imu_http(reader,writer,state):
    """Tiny local HTTP receiver for Sensor Logger, without extra dependencies."""
    status='400 Bad Request'
    response=b'{"ok":false}'
    try:
        header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),timeout=4.)
        if len(header)>8192:raise ValueError('HTTP header too large')
        lines=header.decode('iso-8859-1').split('\r\n')
        method,path,*_=lines[0].split()
        headers={}
        for line in lines[1:]:
            if ':' in line:
                key,value=line.split(':',1)
                headers[key.strip().lower()]=value.strip()
        if method!='POST' or path not in ('/imu','/data'):
            status='404 Not Found';raise ValueError('Wrong IMU endpoint')
        size=int(headers.get('content-length','-1'))
        if not 2<=size<=256_000:raise ValueError('Invalid Content-Length')
        if 'json' not in headers.get('content-type','application/json').lower():
            raise ValueError('Content type must be JSON')
        body=await asyncio.wait_for(reader.readexactly(size),timeout=5.)
        packet=json.loads(body)
        state.imu.ingest(packet)
        status='200 OK';response=b'{"ok":true}'
    except (ValueError,TypeError,KeyError,asyncio.TimeoutError,asyncio.IncompleteReadError,asyncio.LimitOverrunError,UnicodeDecodeError) as e:
        print('[IMU REJECT]',str(e),flush=True)
    finally:
        writer.write((f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\n'
                      f'Content-Length: {len(response)}\r\nConnection: close\r\n\r\n').encode()+response)
        try:await writer.drain()
        except (ConnectionResetError,BrokenPipeError):pass
        writer.close()
        try:await writer.wait_closed()
        except (ConnectionResetError,BrokenPipeError):pass

async def main(session,bind):
    state=Collector(session)
    try:
        a=await asyncio.start_server(lambda r,w:one_packet(r,w,state),bind,8765)
        b=await asyncio.start_server(lambda r,w:one_packet(r,w,state,True),'127.0.0.1',8766)
        c=await asyncio.start_server(lambda r,w:imu_http(r,w,state),bind,8767)
        print('READY: 8765 RSSI + 8766 LOCAL CONTROL',flush=True)
        async with a,b,c:await state.stop.wait()
    finally:state.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--session',default='room_live');p.add_argument('--bind',default='0.0.0.0')
    args=p.parse_args()
    try:asyncio.run(main(args.session,args.bind))
    except KeyboardInterrupt:pass
