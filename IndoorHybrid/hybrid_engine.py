"""Hybrid spatial RSSI likelihood, learned only from explicitly recorded reference locations.

Uses 4 Wi-Fi RSSI channels jointly; it never assumes each RSSI is a unique
range. This is an experimental algorithm: spatial extrapolation is uncertain.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.distance import cdist
from core import IDS, in_polygon, MotionKalman, project_into_polygon

MIN_POINTS=8


def validate_reference(ref, layout, expected_bssid=None):
    """Validate one *physical* reference site and the four RSSI medians."""
    if not isinstance(ref,dict):raise ValueError('Mốc hybrid không hợp lệ.')
    xyz=np.asarray(ref['xyz'],dtype=float)
    if xyz.shape!=(3,) or not np.isfinite(xyz).all() or not in_polygon(xyz[:2],layout['polygon']):
        raise ValueError('Tọa độ mốc hybrid không hợp lệ/ngoài phòng.')
    if abs(xyz[2]-layout['phone_z'])>.30:
        raise ValueError('Chiều cao mốc hybrid khác quá 0.30 m so với bố trí hiện tại.')
    measurements=ref['rssi']
    if set(measurements)!=set(IDS):raise ValueError('Cần đủ bốn RSSI tại cùng một mốc.')
    for value in measurements.values():
        r=float(value)
        if not math.isfinite(r) or not -110<=r<=0:raise ValueError('RSSI hiệu chuẩn không hợp lệ.')
    bssid=ref['bssid']
    if expected_bssid and bssid!=expected_bssid:
        raise ValueError('BSSID của mô hình và hiện tại khác nhau. Không thể dùng lẫn.')
    return {'xyz':xyz.tolist(),'rssi':{a:float(measurements[a]) for a in IDS},
            'bssid':str(bssid),'n':int(ref.get('n',8)),
            'source':str(ref.get('source','CALIB'))[:30]}

class HybridReferenceStore:
    def __init__(self,refs=None):
        self.refs=list(refs or [])
    def clear(self):self.refs=[]
    def append(self,ref,layout,bssid=None):
        r=validate_reference(ref,layout,bssid)
        self.refs=[p for p in self.refs if np.linalg.norm(np.asarray(p['xyz'][:2])-np.asarray(r['xyz'][:2]))>.22]
        self.refs.append(r)
        return len(self.refs)
    def validate_all(self,layout,bssid=None):
        return [validate_reference(r,layout,bssid) for r in self.refs]
    def summary(self,layout):
        if not self.refs:return {'points':0,'ready':False,'warning':'Chưa có mốc tọa độ cho mô hình xác suất.'}
        xy=np.asarray([r['xyz'][:2] for r in self.refs],float)
        span=np.ptp(xy,axis=0)
        ready=len(xy)>=MIN_POINTS and (span>.8).all() and np.linalg.matrix_rank(xy-xy.mean(0))==2
        return {'points':len(self.refs),'ready':bool(ready),'x_span_m':round(float(span[0]),2),
                'y_span_m':round(float(span[1]),2),
                'warning':('Nên có ít nhất 12–25 mốc trải đều toàn phòng.' if ready else
                           'Cần >=8 mốc phân bố theo cả trục X và Y (khuyến nghị 12–25).')}

@dataclass
class BayesianEstimate:
    xy:np.ndarray
    filtered:np.ndarray
    global_xy:np.ndarray
    alternative_xy:np.ndarray
    uncertainty_m:float
    gap:float
    nis:float
    gate:str
    model_cost:float

class HybridBayesianModel:
    """Forward RSSI model + smooth spatial residual, robust Gaussian-like likelihood.

    A physical 3D baseline is regularized with spatial RBF residuals.
    Constant geometry is arbitrary convex quadrilateral, including tilted anchors.
    No ground-truth coordinate enters estimate() at runtime.
    """
    def __init__(self,layout,lengthscale=3.5,alpha=1.5,grid_step=.20):
        self.layout=layout
        self.lengthscale=float(lengthscale);self.alpha=float(alpha)
        self.anchor_xyz=np.asarray([layout['anchors'][a] for a in IDS],float)
        p=np.asarray(layout['polygon'],float)
        xx=np.arange(p[:,0].min(),p[:,0].max()+grid_step*.5,grid_step)
        yy=np.arange(p[:,1].min(),p[:,1].max()+grid_step*.5,grid_step)
        gx,gy=np.meshgrid(xx,yy)
        grid=np.c_[gx.ravel(),gy.ravel()]
        self.grid=np.asarray([q for q in grid if in_polygon(q,p)],float)
        if self.grid.shape[0]<10:raise ValueError('Bản đồ không đủ điểm lưới xác suất.')
        self.fitted=False
    def fit(self,refs):
        if len(refs)<MIN_POINTS:raise ValueError(f'Cần ít nhất {MIN_POINTS} mốc tọa độ cho thuật toán Hybrid.')
        self.pos=np.asarray([r['xyz'][:2] for r in refs],float)
        self.z=np.asarray([r['xyz'][2] for r in refs],float)
        if np.min(np.ptp(self.pos,axis=0))<.8 or np.linalg.matrix_rank(self.pos-self.pos.mean(0))<2:
            raise ValueError('Các điểm HYBRID phải trải đều theo X và Y, không thẳng hàng.')
        self.rssi=np.asarray([[r['rssi'][a] for a in IDS] for r in refs],float)
        d=np.maximum(np.linalg.norm(np.c_[self.pos,self.z][:,None,:]-self.anchor_xyz[None,:,:],axis=2),.5)
        baseline=[];resid=[];sigma=[]
        for i in range(4):
            xs=np.log10(d[:,i]);ys=self.rssi[:,i]
            coeff=least_squares(lambda c:c[0]+c[1]*xs-ys,[-43.,-20.],
                                bounds=([-110.,-50.],[-15.,-5.]),loss='soft_l1',f_scale=2.0)
            c=coeff.x
            r=ys-(c[0]+c[1]*xs)
            baseline.append(c);resid.append(r)
            sigma.append(max(2.,float(np.sqrt(np.mean(r*r)))))
        self.coeff=np.asarray(baseline,float)
        self.resid=np.stack(resid,axis=1)
        self.sigma=np.asarray(sigma,float)
        K=np.exp(-.5*(cdist(self.pos,self.pos)/self.lengthscale)**2)
        self.kweights=np.linalg.solve(K+self.alpha**2*np.eye(len(self.pos)),self.resid)
        dgrid=np.maximum(np.linalg.norm(np.c_[self.grid,np.full(len(self.grid),self.layout['phone_z'])][:,None,:]
                                        -self.anchor_xyz[None,:,:],axis=2),.5)
        baseline=self.coeff[:,0][None,:]+self.coeff[:,1][None,:]*np.log10(dgrid)
        gain=np.exp(-.5*(cdist(self.grid,self.pos)/self.lengthscale)**2)
        self.prediction=baseline+gain@self.kweights
        self.fitted=True
        return self

    @staticmethod
    def _robust_cost(prediction,obs,sigma,active_indices,common_bias_sigma=3.):
        n=len(prediction)
        idx=np.asarray(active_indices,int)
        dif=prediction[:,idx]-obs[None,idx]
        s=sigma[idx]
        # A weak common-mode drift (phone orientation / Tx power) is profiled out
        # but always penalized; no free arbitrary RSSI shift.
        if common_bias_sigma>0:
            inv=1/s**2
            offset=(dif*inv[None,:]).sum(1)/(inv.sum()+1/common_bias_sigma**2)
            dif=dif-offset[:,None]
            offset_penalty=(offset/common_bias_sigma)**2
        else:offset_penalty=np.zeros(n)
        z=np.abs(dif/s[None,:])
        return np.where(z<=2,z*z,4*z-4).sum(1)+offset_penalty

    def estimate(self,rssi,active_ids=IDS,prior_xy=None,prior_sigma=None,reliability=None):
        if not self.fitted:raise ValueError('Chưa xây dựng mô hình Hybrid.')
        active=[IDS.index(a) for a in active_ids]
        if len(active)<3:raise ValueError('Cần >=3 anchor để định vị Hybrid.')
        obs=np.zeros(4,float)
        for aid in active_ids:
            value=float(rssi[aid])
            if not math.isfinite(value):raise ValueError('RSSI Hybrid không hợp lệ.')
            obs[IDS.index(aid)]=value
        sigma=self.sigma.copy()
        if reliability:
            for j,a in enumerate(IDS):
                if a in active_ids:
                    # Do not confuse diagnostics with calibrated probabilities.
                    score=float(reliability.get(a,1.))
                    sigma[j] *= 1./math.sqrt(max(.15,min(1.,score)))
        cost=self._robust_cost(self.prediction,obs,sigma,active)
        global_idx=int(np.argmin(cost))
        if prior_xy is not None and prior_sigma is not None and prior_sigma>0:
            prior=np.asarray(prior_xy,float)
            posterior_cost=cost+np.sum((self.grid-prior)**2,axis=1)/(prior_sigma**2)
        else:posterior_cost=cost
        idx=int(np.argmin(posterior_cost))
        alt=next((int(k) for k in np.argsort(posterior_cost) if np.linalg.norm(self.grid[k]-self.grid[idx])>=1.),idx)
        scaled=posterior_cost-np.min(posterior_cost)
        p=np.exp(-.5*np.clip(scaled,0,700));p=p/np.sum(p)
        radius=np.linalg.norm(self.grid-self.grid[idx],axis=1)
        order=np.argsort(radius)
        uncertainty=float(radius[order[np.searchsorted(np.cumsum(p[order]),.68,side='left')]])
        return {'xy':self.grid[idx].copy(),'global_xy':self.grid[global_idx].copy(),
                'alternative_xy':self.grid[alt].copy(),'gap':float(posterior_cost[alt]-posterior_cost[idx]),
                'uncertainty_m':round(uncertainty,3),'cost':float(posterior_cost[idx])}

class HybridOnlinePipeline:
    def __init__(self,model,layout,excluded_anchor=None,adaptive_weights=True):
        self.model=model
        self.layout=layout
        self.excluded_anchor=excluded_anchor
        self.adaptive_weights=adaptive_weights
        self.kal=MotionKalman(vmax=3.)
        self.last_time=None
        self.last_imu_seq=0
    def reset(self):self.kal.reset();self.last_time=None;self.last_imu_seq=0
    def update(self,rssi,when,reliability=None,imu=None):
        active=tuple(a for a in IDS if a!=self.excluded_anchor)
        if len(active)<3:raise ValueError('Không đủ anchor Hybrid.')
        prior_xy=None;prior_sigma=None
        if self.kal.display is not None and self.last_time is not None:
            dt=float(np.clip(when-self.last_time,0.,10.))
            if dt<=5.:
                # A soft mobility prior; allow reacquisition after outages.
                prior_xy=np.asarray(self.kal.display,float)
                prior_sigma=min(4.5,max(1.6,1.0+2.*dt))
        imu_used=False
        imu_steps=0
        imu_prior=None
        if imu is not None:
            m=imu.displacement(self.last_imu_seq)
            self.last_imu_seq=m['step_seq']
            if m['used'] and m['steps']>0 and prior_xy is not None:
                # The displacement is only valid for recent, aligned IMU and
                # short Wi-Fi intervals. Do not dominate the RSSI likelihood.
                dt=max(.25,float(when-self.last_time))
                displacement=math.hypot(m['dx'],m['dy'])
                if displacement <= min(3.0*dt+.6,5.0) and m['steps'] <= 12:
                    imu_prior=project_into_polygon(
                        prior_xy+np.asarray([m['dx'],m['dy']]),self.layout['polygon'])
                    prior_xy=imu_prior
                    prior_sigma=max(1.0,min(2.5,1.1+.20*m['steps']+.22*dt))
                    imu_used=True
                    imu_steps=m['steps']
        current=self.model.estimate(rssi,active,prior_xy,prior_sigma,
                                     reliability if self.adaptive_weights else None)
        sigma=float(np.clip(.55+.42*current['uncertainty_m'],.65,3.5))
        filtered,gate,nis=self.kal.update(current['xy'],when,sigma,polygon=self.layout['polygon'])
        self.last_time=when
        return {'raw':current['xy'].tolist(), 'filtered':filtered.tolist(),
                'global_xy':current['global_xy'].tolist(),
                'alternative_xy':current['alternative_xy'].tolist(),
                'uncertainty_m':current['uncertainty_m'],
                'gap':round(current['gap'],3), 'model_cost':round(current['cost'],3),
                'gate':gate,'nis':round(nis,2),'active_anchors':list(active),
                'imu_fused':imu_used,'imu_steps_since_wifi':imu_steps,
                'imu_prior_xy':imu_prior.tolist() if imu_prior is not None else None}
