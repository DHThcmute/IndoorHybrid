"""Diagnostic RSSI-distance plots. Independent of Hybrid inference.

Mathematically matches RangeCalibration.ranges in core.py. No reference
(distance ground truth) is passed into the estimation function: it is used
only to display the red line and compute measurement error.
"""
from __future__ import annotations
import math
from datetime import datetime


def rssi_to_distance(rssi, fit, layout, anchor_id, mode='3d'):
    """Convert a single new RSSI reading into a calibrated 3-D or 2-D distance.

    Returns None when calibration/measurement is invalid. Clipping agrees with
    the geometry engine, including its model inversion safety limits.
    """
    if fit is None or anchor_id not in layout['anchors']:
        return None
    try:
        r=float(rssi); a=float(fit['A']); n=float(fit['n'])
        if not all(math.isfinite(v) for v in (r,a,n)) or not 1.0<=n<=5.0:
            return None
        poly=layout['polygon']
        xs=[float(x) for x,y in poly];ys=[float(y) for x,y in poly]
        limit=max(1.0,3.0*math.hypot(max(xs)-min(xs),max(ys)-min(ys)))
        log_d=max(-1.0,min(math.log10(limit),(a-r)/(10*n)))
        d3=10**log_d
        if mode=='3d':return d3
        if mode!='2d':raise ValueError('Distance mode must be 3d or 2d')
        dz=float(layout['phone_z'])-float(layout['anchors'][anchor_id][2])
        return math.sqrt(max(0.01,d3*d3-dz*dz))
    except (TypeError,ValueError,OverflowError,KeyError,IndexError):
        return None


def take_samples(status, last_sequence, references, mode='3d', elapsed_s=0.0):
    """Extract only NEW, FRESH RSSI per anchor. Does not require START LIVE.

    Mutates last_sequence; returns timestamped plot records without influence
    on the Collector, estimation state, or ground-truth training.
    """
    anchors=status.get('anchors',{})
    fits=status.get('calibration',{})
    calibrated_bssid=status.get('calibrated_bssid')
    layout=status.get('layout',{})
    session=status.get('session','')
    now=datetime.now().astimezone().isoformat(timespec='milliseconds')
    out=[]
    for aid in ('L1','L2','L3','L4'):
        anchor=anchors.get(aid,{})
        if not anchor.get('fresh') or anchor.get('rssi') is None:
            continue
        seq=anchor.get('seq')
        bssid=anchor.get('bssid')
        if not isinstance(seq,int) or seq<1:
            continue
        unique=(session,bssid,seq)
        if last_sequence.get(aid)==unique:
            continue
        last_sequence[aid]=unique
        # BSSID check prevents a hotspot restart from silently reusing old CALIB.
        if not fits.get(aid) or not calibrated_bssid or bssid!=calibrated_bssid:
            continue
        estimated=rssi_to_distance(anchor['rssi'],fits[aid],layout,aid,mode)
        if estimated is None:
            continue
        ref=float(references[aid]); err=estimated-ref
        out.append({'timestamp':now,'elapsed_s':float(elapsed_s),
            'anchor':aid,'seq':seq,'rssi_dbm':float(anchor['rssi']),
            'reference_m':ref,'estimated_m':estimated,
            'error_m':err,'absolute_error_m':abs(err),
            'cal_A':float(fits[aid]['A']),'cal_n':float(fits[aid]['n']),
            'cal_points':int(fits[aid]['points']),
            'provisional':bool(fits[aid].get('provisional',False)),
            'mode':mode,'bssid':bssid,'session':session})
    return out
