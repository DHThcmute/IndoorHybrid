"""No radio-map, no GPR: per-anchor RSSI->range and robust 2D multilateration.

All lengths are metres. Horizontal map coordinates are (x,y); z specifies the
antenna height above the same floor. RSSI is a noisy *proxy* for range, not TOF.
"""
from __future__ import annotations
import math,statistics,time
from collections import deque
import numpy as np
from scipy.optimize import least_squares, minimize
IDS=('L1','L2','L3','L4')
DEFAULT_LAYOUT={'polygon':[[0.,0.],[10.,0.],[10.,6.],[0.,6.]],
                'anchors':{'L1':[0.,0.,0.8],'L2':[10.,0.,0.8],
                           'L3':[10.,6.,0.8],'L4':[0.,6.,0.8]},
                'phone_z':0.8}

def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def in_polygon(xy, poly, eps=1e-7):
    return all(cross(poly[i],poly[(i+1)%len(poly)],xy)>=-eps for i in range(len(poly)))

def validate_layout(layout):
    p=np.asarray(layout['polygon'],float)
    if p.shape!=(4,2) or not np.all(np.isfinite(p)):
        raise ValueError('Tứ giác phải có đúng 4 đỉnh (x,y) hữu hạn.')
    if min(cross(p[i],p[(i+1)%4],p[(i+2)%4]) for i in range(4))<=0.01:
        raise ValueError('Nhập 4 đỉnh tứ giác LỒI theo thứ tự ngược chiều kim đồng hồ.')
    if np.ptp(p,axis=0).max()>100: raise ValueError('Phòng quá 100 m: kiểm tra đơn vị mét.')
    anchors=layout['anchors']
    if set(anchors)!=set(IDS):raise ValueError('Phải có tọa độ đủ L1–L4.')
    a=np.asarray([anchors[k] for k in IDS],float)
    if a.shape!=(4,3) or not np.isfinite(a).all():raise ValueError('Mỗi anchor phải có X,Y,Z.')
    if not all(in_polygon(x[:2],p) for x in a):raise ValueError('Tất cả anchor phải nằm trong hoặc trên biên tứ giác.')
    if not 0<=float(layout['phone_z'])<=5 or (a[:,2]<0).any() or (a[:,2]>5).any():
        raise ValueError('Chiều cao Z phải trong khoảng 0–5 m.')
    if np.linalg.matrix_rank(a[:,:2]-a[:,:2].mean(axis=0))<2:
        raise ValueError('Bốn laptop không được nằm gần như trên cùng một đường thẳng.')
    return {'polygon':p.tolist(),'anchors':{k:a[i].tolist() for i,k in enumerate(IDS)},
            'phone_z':float(layout['phone_z'])}

class RangeCalibration:
    """One reference fixes A at assumed n=2; >=2 spaced distances fit (A,n)."""
    def __init__(self):self.refs={i:[] for i in IDS};self.bssid=None
    def clear(self):self.__init__()
    def add(self,aid,distance,readings,bssid):
        if aid not in IDS:raise ValueError('Anchor ID sai')
        if distance<.30 or distance>150:raise ValueError('Khoảng cách hiệu chuẩn cần 0.3–150 m.')
        vals=np.asarray(list(readings),float)
        if len(vals)<4 or not np.isfinite(vals).all():raise ValueError('Cần ít nhất 4 RSSI thật.')
        if self.bssid and bssid!=self.bssid:raise ValueError('BSSID đã đổi; xóa hiệu chuẩn cũ trước.')
        self.bssid=bssid
        med=float(np.median(vals));mad=float(1.4826*np.median(abs(vals-med)))
        self.refs[aid].append({'distance':float(distance),'rssi':med,'mad':max(.7,mad),
                               'count':int(len(vals)),'bssid':bssid})
        return self.fit(aid)
    def fit(self,aid):
        pts=self.refs[aid]
        if not pts:return None
        ds=np.asarray([p['distance'] for p in pts]);rs=np.asarray([p['rssi'] for p in pts])
        if len(pts)<2 or np.ptp(np.log10(ds))<.12:
            n=2.;A=float(np.median(rs+10*n*np.log10(ds)))
            return {'A':A,'n':n,'provisional':True,'points':len(pts),
                    'warning':'Chỉ có một mốc hoặc các mốc quá gần nhau: tạm dùng n=2.0.'}
        weights=1/np.maximum(1,np.asarray([p['mad'] for p in pts]))
        def residual(v):return (v[0]-10*v[1]*np.log10(ds)-rs)*weights
        guessA=float(np.median(rs+20*np.log10(ds)))
        fit=least_squares(residual,x0=[float(np.clip(guessA,-94,-16)),2.],bounds=([-105,1.],[0.,5.]),
                          loss='soft_l1',f_scale=1,max_nfev=500)
        A,n=map(float,fit.x)
        warning=''
        if n<1.05 or n>4.95:warning='Dữ liệu không phù hợp suy hao log-distance; cần đo lại ở mốc xa hơn.'
        return {'A':A,'n':n,'provisional':False,'points':len(pts),'warning':warning}
    def quality(self, aid, rssi=None):
        """Calibration *diagnostic* score, NOT a probability of correct position.

        A plateau/reversal in reference medians is a strong warning that the
        log-distance inversion is not informative in that distance interval.
        """
        fit=self.fit(aid)
        if fit is None:
            return {'score':0, 'level':'NO CAL', 'reason':'Chưa CALIB',
                    'rmse_db':None,'plateau_intervals':[]}
        pts=sorted(self.refs[aid],key=lambda q:q['distance'])
        d=np.asarray([p['distance'] for p in pts],float)
        obs=np.asarray([p['rssi'] for p in pts],float)
        pred=fit['A']-10*fit['n']*np.log10(d)
        rmse=float(np.sqrt(np.mean((obs-pred)**2)))
        score={1:.35,2:.68}.get(len(pts),.98)
        if fit['provisional']:score*=.75
        score*=math.exp(-max(0.,rmse-.75)/5.)
        plateaus=[]
        for left,right in zip(pts,pts[1:]):
            ratio=right['distance']/left['distance']
            attenuation=left['rssi']-right['rssi']
            # Only assess well-separated references, not tiny movements.
            if ratio>=1.5 and attenuation<3.0:
                plateaus.append([left['distance'],right['distance']])
        if plateaus:score*=.23
        if fit['warning']:score*=.6
        reason=[]
        if len(pts)<3:reason.append(f'{len(pts)} mốc: chưa kiểm chứng đường cong')
        if fit['provisional']:reason.append('hệ số suy hao đang giả định')
        if plateaus:reason.append('RSSI phẳng/đảo chiều ở mốc xa')
        if rmse>=2:reason.append(f'sai khác mô hình {rmse:.1f} dB')
        if not reason:reason=['Hiệu chuẩn phù hợp mô hình tại các mốc đã đo']
        if rssi is not None and len(pts)>=2:
            # Extrapolation beyond observed RSSI is risky.
            r=float(rssi)
            if r<min(obs)-3 or r>max(obs)+3:
                score*=.65;reason.append('ngoài dải RSSI CALIB')
            if plateaus:
                # If the model maps current RSSI into a plateau, reduce more.
                estimated=10**float(np.clip((fit['A']-r)/(10*fit['n']),-1,2))
                if any(lo*.85<=estimated<=hi*1.15 for lo,hi in plateaus):
                    score*=.75
        score=float(np.clip(score,.05,1.))
        level='TỐT' if score>=.75 else 'CẦN KIỂM TRA' if score>=.4 else 'KÉM'
        return {'score':round(score,3),'level':level,'reason':'; '.join(reason),
                'rmse_db':round(rmse,2),'plateau_intervals':plateaus}

    def ranges(self,rssi,layout,active_ids=IDS):
        """Return 4 rows (3D, horizontal) with NaN for inactive anchors."""
        active=set(active_ids)
        if any(not self.refs[k] for k in active):
            raise ValueError('Cần CALIB đủ các anchor đang sử dụng.')
        ans=[];z=layout['phone_z']
        limit=3*np.linalg.norm(np.ptp(np.asarray(layout['polygon']),axis=0))
        for aid,value in zip(IDS,rssi):
            if aid not in active:
                ans.append((float('nan'),float('nan')));continue
            f=self.fit(aid)
            logd=np.clip((f['A']-float(value))/(10*f['n']),-1.0,math.log10(max(limit,1)))
            d3=float(10**logd)
            dz=z-layout['anchors'][aid][2]
            dxy=math.sqrt(max(.01,d3*d3-dz*dz))
            ans.append((d3,dxy))
        return np.asarray(ans,float)
    def to_json(self):return {'refs':self.refs,'bssid':self.bssid}
    @classmethod
    def from_json(cls,obj):
        c=cls();c.refs={i:list(obj.get('refs',{}).get(i,[])) for i in IDS};c.bssid=obj.get('bssid')
        # check contents before accepting saved calibration
        for aid in IDS:
            for r in c.refs[aid]:
                if not (math.isfinite(float(r['distance'])) and .3<=float(r['distance'])<=150
                        and -110<=float(r['rssi'])<=0):raise ValueError('Invalid calibration file')
        return c

def solve_ranges(layout,ranges,previous=None,weights=None):
    """Constrained robust RSSI multilateration using >=3 active anchors.

    Inactive anchors must have weight 0; their ranges may be NaN.
    """
    poly=np.asarray(layout['polygon'],float)
    allp=np.asarray([layout['anchors'][i][:2] for i in IDS],float)
    allz=np.asarray([layout['anchors'][i][2] for i in IDS],float)
    phone_z=layout['phone_z']
    r=np.asarray(ranges,float)
    w=np.ones(4) if weights is None else np.asarray(weights,float)
    if r.shape!=(4,) or w.shape!=(4,) or not np.isfinite(w).all() or (w<0).any():
        raise ValueError('Invalid range weights/shape')
    active=w>0
    if active.sum()<3 or not np.isfinite(r[active]).all() or (r[active]<=0).any():
        raise ValueError('Cần ít nhất 3 khoảng cách hợp lệ.')
    p=allp[active];z=allz[active];rr=r[active];ww=w[active]
    if np.linalg.matrix_rank(p-p.mean(axis=0))<2:
        raise ValueError('Ba anchor đang dùng không được thẳng hàng.')
    ww=ww/np.mean(ww)
    def predicted(x):return np.sqrt(np.sum((p-x)**2,axis=1)+(z-phone_z)**2)
    def robust_objective(x):
        e=predicted(x)-rr
        delta=1.3
        return float(np.sum(ww*delta**2*(np.sqrt(1+(e/delta)**2)-1)))
    constraints=[{'type':'ineq','fun':lambda x,i=i:cross(poly[i],poly[(i+1)%4],x)} for i in range(4)]
    seeds=[np.mean(poly,axis=0)]
    if previous is not None and in_polygon(previous,poly):seeds.insert(0,np.asarray(previous,float))
    try:
        A=2*(p[1:]-p[:1]);b=np.sum(p[1:]**2,axis=1)-np.sum(p[0]**2)-rr[1:]**2+rr[0]**2
        guess=np.linalg.lstsq(A,b,rcond=None)[0]
        if in_polygon(guess,poly):seeds.insert(0,guess)
    except np.linalg.LinAlgError:pass
    outcomes=[minimize(robust_objective,seed,method='SLSQP',constraints=constraints,
                       options={'ftol':1e-8,'maxiter':100}) for seed in seeds]
    valid=[q for q in outcomes if q.success and in_polygon(q.x,poly,1e-5)]
    if not valid:raise RuntimeError('Không hội tụ được nghiệm nằm trong tứ giác.')
    best=min(valid,key=lambda q:q.fun)
    residual=predicted(best.x)-rr
    return best.x,float(np.sqrt(np.average(residual**2,weights=ww)))

def project_into_polygon(point, polygon):
    """Nearest feasible XY for a counter-clockwise convex polygon.

    Unlike clipping x/y independently, this also works for a skew quadrilateral.
    Euclidean projection onto a convex set is non-expansive, so the visible
    displacement limit is not increased by projection.
    """
    xy=np.asarray(point,float)
    poly=np.asarray(polygon,float)
    if in_polygon(xy,poly):
        return xy.copy()
    nearest=None;best=float('inf')
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
        v=b-a
        t=float(np.clip(np.dot(xy-a,v)/np.dot(v,v),0.,1.))
        pt=a+t*v
        d=float(np.sum((xy-pt)**2))
        if d<best:best=d;nearest=pt
    return nearest.copy()

class MotionKalman:
    """2D constant-velocity filter; innovation gate with safe re-acquisition.

    Hard speed bound is applied to visible XY, not a claim of range accuracy.
    """
    def __init__(self,vmax=3.,process_var=1.7):
        self.vmax=vmax;self.q=process_var;self.reset()
    def reset(self):
        self.x=None;self.P=None;self.t=None;self.display=None;self.rejected=0;self.pending=None
    def update(self,xy,now,measurement_sigma=.85,polygon=None):
        z=np.asarray(xy,float)
        if self.x is None:
            if polygon is not None:z=project_into_polygon(z,polygon)
            self.x=np.r_[z,0.,0.];self.P=np.diag([1.,1.,3.,3.]);self.t=now
            self.display=z.copy();return z.copy(),'INIT',0.
        dt=float(np.clip(now-self.t,.1,3.));self.t=now
        F=np.eye(4);F[0,2]=dt;F[1,3]=dt
        G=np.array([[.5*dt**2,0],[0,.5*dt**2],[dt,0],[0,dt]])
        self.x=F@self.x;self.P=F@self.P@F.T+self.q*(G@G.T)
        H=np.array([[1.,0,0,0],[0,1,0,0]])
        R=np.eye(2)*max(.4,measurement_sigma)**2
        y=z-H@self.x;S=H@self.P@H.T+R
        nis=float(y@np.linalg.solve(S,y))
        gate=9.21  # Chi-square 2 d.o.f. ~99%; heuristic under RSSI non-Gaussian errors
        status='ACCEPT'
        if nis>gate or float(np.linalg.norm(z-self.display))>self.vmax*dt+1.2:
            self.rejected+=1
            if self.pending is None or np.linalg.norm(z-self.pending['pos'])>1.6:
                self.pending={'pos':z.copy(),'hits':1}
            else:
                self.pending['pos']=.65*self.pending['pos']+.35*z
                self.pending['hits']+=1
            if self.pending['hits']>=3:
                # Reacquire stable new cluster, then speed limit DISPLAY to avoid teleport.
                self.x[:2]=z;self.x[2:]=0.;self.P=np.diag([1.4,1.4,2.,2.])
                self.pending=None;status='REACQUIRE'
            else:status='REJECT'
        else:
            self.pending=None
            K=self.P@H.T@np.linalg.inv(S)
            self.x=self.x+K@y
            I=np.eye(4)
            self.P=(I-K@H)@self.P@(I-K@H).T+K@R@K.T
        v=self.x[2:];norm=float(np.linalg.norm(v))
        if norm>self.vmax:self.x[2:]*=self.vmax/norm
        target=self.x[:2].copy()
        step=target-self.display
        limit=self.vmax*dt
        travel=float(np.linalg.norm(step))
        if travel>limit:self.display+=step*(limit/travel)
        else:self.display=target
        if polygon is not None:
            desired=self.x[:2].copy()
            corrected=project_into_polygon(desired,polygon)
            if float(np.linalg.norm(corrected-desired))>1e-9:
                # Cancel only the outward velocity component; preserve movement
                # tangential to a wall where possible.
                outward=desired-corrected
                outward/=np.linalg.norm(outward)
                vn=float(np.dot(self.x[2:],outward))
                if vn>0:self.x[2:]-=vn*outward
                self.x[:2]=corrected
            self.display=project_into_polygon(self.display,polygon)
        return self.display.copy(),status,nis

class OnlineRangePipeline:
    def __init__(self,layout,calibration,excluded_anchor=None,adaptive_weights=True):
        self.layout=validate_layout(layout);self.cal=calibration
        if excluded_anchor is not None and excluded_anchor not in IDS:
            raise ValueError('Anchor loại trừ không hợp lệ.')
        self.excluded_anchor=excluded_anchor
        self.adaptive_weights=bool(adaptive_weights)
        self.active_ids=tuple(i for i in IDS if i!=excluded_anchor)
        self.history={k:deque(maxlen=3) for k in IDS}
        self.kal=MotionKalman();self.previous=None
    def reset(self):
        self.history={k:deque(maxlen=3) for k in IDS};self.kal.reset();self.previous=None
    def update(self,rssi,when=None):
        now=time.monotonic() if when is None else when
        readings=rssi if isinstance(rssi,dict) else dict(zip(IDS,rssi))
        for aid in self.active_ids:
            v=float(readings[aid])
            if not math.isfinite(v):raise ValueError('RSSI anchor đang dùng không hợp lệ.')
            self.history[aid].append(v)
        filtered=np.asarray([statistics.median(self.history[k]) if k in self.active_ids else float('nan')
                             for k in IDS])
        distances=self.cal.ranges(filtered,self.layout,self.active_ids)
        qualities={a:self.cal.quality(a,filtered[j] if a in self.active_ids else None)
                   for j,a in enumerate(IDS)}
        weights=np.zeros(4)
        for j,a in enumerate(IDS):
            if a not in self.active_ids:continue
            f=self.cal.fit(a)
            mad=float(np.median([max(.7,p['mad']) for p in self.cal.refs[a]]))
            model_rmse=qualities[a]['rmse_db'] or 0.
            sigma_rssi=math.sqrt(mad**2+model_rmse**2+1.5**2)
            sigma_d=max(.55,math.log(10)/(10*f['n'])*distances[j,0]*sigma_rssi)
            # Equal mode for an explicit A/B comparison. Otherwise inverse
            # estimated range variance times calibration diagnostic quality.
            weights[j]=(max(.05,qualities[a]['score'])/sigma_d**2
                        if self.adaptive_weights else 1.)
        # Avoid one anchor overwhelming the others due to a tiny estimated sigma.
        if self.adaptive_weights:
            nonzero=weights[weights>0]
            cap=max(float(np.median(nonzero))*8.,.01)
            weights=np.minimum(weights,cap)
        raw,range_rmse=solve_ranges(self.layout,distances[:,0],self.previous,weights)
        self.previous=raw
        sigma=np.clip(.65+.4*range_rmse,.65,3.)
        smoothed,gate,nis=self.kal.update(raw,now,sigma,polygon=self.layout['polygon'])
        # JSON-safe output for disabled anchors (None, not NaN).
        return {'raw':raw.tolist(),'filtered':smoothed.tolist(),
                'rssi_median':[float(v) if math.isfinite(v) else None for v in filtered],
                'ranges_m':[float(v) if math.isfinite(v) else None for v in distances[:,0]],
                'weights':{a:round(float(weights[j]),4) for j,a in enumerate(IDS)},
                'quality':qualities,'active_anchors':list(self.active_ids),
                'range_rmse_m':round(range_rmse,3),'gate':gate,'nis':round(nis,2)}
