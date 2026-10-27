"""Four live RSSI-to-distance charts in a single Tkinter GUI tab."""
from __future__ import annotations
import csv, math, time, tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from range_plot_math import take_samples

IDS=('L1','L2','L3','L4')
BLUE='#126FBC';RED='#D63B3B';GRID='#E6EAF0';TXT='#273244'


class RangePlotTab(ttk.Frame):
    """Diagnostic measurement plot; never modifies estimation/model state."""
    def __init__(self, master):
        super().__init__(master, padding=(8,7))
        self.refs={a:tk.StringVar(value='') for a in IDS}
        self.mode=tk.StringVar(value='3d')
        self.window_sec=tk.StringVar(value='120')
        self.message=tk.StringVar(value='Nhập 4 khoảng cách thực, sau đó nhấn BẮT ĐẦU GHI. Cần CALIB khoảng cách từng máy.')
        self.running=False;self.started=0.;self.samples={a:[] for a in IDS}
        self.last_sequences={};self.last_status=None;self.canvases={}
        self._build()

    def _build(self):
        hdr=ttk.Frame(self);hdr.pack(fill='x')
        ttk.Label(hdr,text='SO SÁNH KHOẢNG CÁCH THỰC VÀ KHOẢNG CÁCH ƯỚC LƯỢNG TỪ RSSI',
                  font=('DejaVu Sans',11,'bold')).pack(anchor='w')
        ttk.Label(hdr,text='Đường đỏ nét đứt: khoảng cách thực  |  Đường xanh: ước lượng từ RSSI đo mới. '
                  'Dữ liệu TEST chỉ dùng để tính sai số, không tham gia định vị.',
                  foreground='#666666',wraplength=820).pack(anchor='w',pady=(3,5))
        row=ttk.Frame(self);row.pack(fill='x',pady=(0,4))
        for aid in IDS:
            ttk.Label(row,text=f'{aid} (m)').pack(side='left',padx=(0,3))
            ttk.Entry(row,textvariable=self.refs[aid],width=7).pack(side='left',padx=(0,10))
        ttk.Label(row,text='Kiểu đo').pack(side='left',padx=(5,2))
        ttk.Combobox(row,textvariable=self.mode,values=('3d','2d'),state='readonly',width=4).pack(side='left')
        ttk.Label(row,text='3d: đo thẳng đến anten  |  2d: đo trên sàn',
                  foreground='#666666').pack(side='left',padx=(8,0))
        second=ttk.Frame(self);second.pack(fill='x',pady=(0,5))
        ttk.Button(second,text='BẮT ĐẦU GHI',command=self.start_capture).pack(side='left')
        ttk.Button(second,text='DỪNG GHI',command=self.stop_capture).pack(side='left',padx=5)
        ttk.Button(second,text='XÓA BIỂU ĐỒ',command=self.clear).pack(side='left',padx=5)
        ttk.Button(second,text='LƯU CSV',command=self.export_csv).pack(side='left',padx=5)
        ttk.Label(second,text='Cửa sổ xem (giây)').pack(side='left',padx=(14,4))
        ttk.Combobox(second,textvariable=self.window_sec,values=('30','60','120','300','600'),
                     state='readonly',width=5).pack(side='left')
        ttk.Label(self,textvariable=self.message,foreground='#535C66',wraplength=1000).pack(anchor='w',pady=(0,4))
        grid=ttk.Frame(self);grid.pack(fill='both',expand=True)
        grid.columnconfigure(0,weight=1);grid.columnconfigure(1,weight=1)
        grid.rowconfigure(0,weight=1);grid.rowconfigure(1,weight=1)
        for j,aid in enumerate(IDS):
            box=ttk.LabelFrame(grid,text=f'{aid}  |  Khoảng cách ước lượng theo thời gian',padding=3)
            box.grid(row=j//2,column=j%2,sticky='nsew',padx=3,pady=3)
            canvas=tk.Canvas(box,bg='#FFFFFF',highlightthickness=0,bd=0,width=375,height=215)
            canvas.pack(fill='both',expand=True)
            self.canvases[aid]=canvas
            canvas.bind('<Configure>',lambda _event, aid=aid:self.draw_one(aid))
        self.window_sec.trace_add('write',lambda *args:self.redraw())

    def _parse_reference(self):
        refs={}
        for aid in IDS:
            raw=self.refs[aid].get().strip().replace(',','.')
            try: d=float(raw)
            except ValueError:raise ValueError(f'Khoảng cách thực {aid} không hợp lệ.') from None
            if not math.isfinite(d) or not 0.1<=d<=150:
                raise ValueError(f'{aid}: khoảng cách phải từ 0.1 đến 150 m.')
            refs[aid]=d
        return refs

    def start_capture(self):
        try:refs=self._parse_reference()
        except ValueError as exc:
            messagebox.showerror('Khoảng cách thực',str(exc),parent=self.winfo_toplevel());return
        if self.running:
            messagebox.showinfo('Plot','Đang ghi. Nhấn DỪNG GHI để đổi mốc.',parent=self.winfo_toplevel());return
        # Previous test site must never contaminate statistics of a new point.
        self.samples={a:[] for a in IDS};self.last_sequences={}
        self.references=refs;self.measurement_mode=self.mode.get()
        self.initial_model=self._calibration_signature(self.last_status)
        self.running=True;self.started=time.monotonic()
        self._set_fields_enabled(False)
        self.message.set('ĐANG GHI • Mỗi mẫu RSSI mới tạo 1 điểm dữ liệu. Không cần START LIVE. '
                         'Nếu đường xanh bị lệch khỏi đường đỏ, đó là sai số cần đo, không được tự sửa.')
        self.redraw()

    def _set_fields_enabled(self,enabled):
        # Keep the graph-window selector usable while recording.
        for child in self.winfo_children():
            if isinstance(child,ttk.Frame):
                for inp in child.winfo_children():
                    if isinstance(inp,ttk.Entry):
                        inp.configure(state='normal' if enabled else 'disabled')
                    if isinstance(inp,ttk.Combobox) and inp.cget('textvariable')==str(self.mode):
                        inp.configure(state='readonly' if enabled else 'disabled')

    def stop_capture(self):
        if not self.running:return
        self.running=False;self._set_fields_enabled(True)
        n=sum(len(v) for v in self.samples.values())
        self.message.set(f'ĐÃ DỪNG • {n} mẫu hợp lệ. Bấm LƯU CSV để lưu dữ liệu; có thể đổi mốc và ghi lại.')
        self.redraw()

    def clear(self):
        if self.running:
            self.stop_capture()
        self.samples={a:[] for a in IDS};self.last_sequences={}
        self.message.set('Đã xóa dữ liệu plot. Nhập lại khoảng cách thực và bắt đầu ghi.')
        self.redraw()

    @staticmethod
    def _calibration_signature(status):
        if not status:return None
        fits=status.get('calibration',{})
        layout=status.get('layout',{})
        # Stable parameter tuple: any CALIB/layout change must start a new plot.
        return (status.get('calibrated_bssid'),
                repr(layout.get('anchors')),repr(layout.get('phone_z')),
                tuple((a,None,None,None) if not fits.get(a) else
                      (a,fits[a].get('A'),fits[a].get('n'),fits[a].get('points'))
                      for a in IDS))

    def update_status(self,status):
        self.last_status=status
        if not self.running:return
        signature=self._calibration_signature(status)
        if self.initial_model is None:
            self.initial_model=signature
        elif signature!=self.initial_model:
            self.stop_capture()
            self.message.set('ĐÃ DỪNG: CALIB / tọa độ anchor / BSSID hiệu chuẩn đã thay đổi. '
                             'Hãy lưu CSV cũ, rồi bắt đầu phép đo mới.')
            return
        calibrated_bssid=status.get('calibrated_bssid')
        if any(v.get('fresh') and v.get('bssid') and calibrated_bssid and
               v['bssid']!=calibrated_bssid for v in status.get('anchors',{}).values()):
            self.stop_capture()
            self.message.set('ĐÃ DỪNG: BSSID Wi-Fi hiện tại khác BSSID lúc CALIB. '
                             'Không trộn đường đo giữa hai hotspot.')
            return
        now=time.monotonic()
        try:records=take_samples(status,self.last_sequences,self.references,
                                 self.measurement_mode,now-self.started)
        except (KeyError,ValueError,TypeError,OverflowError):return
        for record in records:self.samples[record['anchor']].append(record)
        if records:
            total=sum(len(v) for v in self.samples.values())
            missing=[a for a in IDS if not status.get('calibration',{}).get(a)]
            self.message.set(f'ĐANG GHI • {total} mẫu • '+
                ('Chưa CALIB: '+', '.join(missing)+'. ' if missing else '')+
                'Chỉ dùng RSSI mới, đúng BSSID; không tái sử dụng kết quả LIVE.')
            self.redraw()
        elif sum(len(v) for v in self.samples.values())==0:
            anchors=status.get('anchors',{})
            missing=[a for a in IDS if not status.get('calibration',{}).get(a)]
            bssid=status.get('calibrated_bssid')
            mismatch=[a for a in IDS if anchors.get(a,{}).get('bssid') and bssid and anchors[a]['bssid']!=bssid]
            if missing:self.message.set('CHƯA CÓ ĐƯỜNG ƯỚC LƯỢNG: cần CALIB RSSI–khoảng cách: '+', '.join(missing))
            elif mismatch:self.message.set('BSSID KHÔNG KHỚP CALIB: '+', '.join(mismatch)+'. Cần đo CALIB lại.')
            else:self.message.set('Đợi RSSI mới từ bốn anchor. Chỉ hiển thị dữ liệu đang cập nhật.')

    def _time_range(self,records):
        try:window=float(self.window_sec.get())
        except ValueError:window=120.
        last=(records[-1]['elapsed_s'] if records else max(0.,time.monotonic()-self.started) if self.running else 0.)
        return max(0.,last-window),max(window,last)

    def draw_one(self,aid):
        canvas=self.canvases.get(aid)
        if canvas is None:return
        canvas.delete('all')
        W=max(280,canvas.winfo_width());H=max(170,canvas.winfo_height())
        ml,mr,mt,mb=48,14,24,38
        x0,x1=ml,W-mr;y0,y1=mt,H-mb
        records=self.samples[aid]
        if self.running and hasattr(self,'references'):
            ref=self.references[aid]
        elif records:ref=records[-1]['reference_m']
        else:
            try:ref=float(self.refs[aid].get().replace(',','.'))
            except ValueError:ref=None
        # Common time axis for all four panels, so graph shapes are comparable.
        try:window=float(self.window_sec.get())
        except ValueError:window=120.
        recent=max((v[-1]['elapsed_s'] for v in self.samples.values() if v),default=0.)
        if self.running: recent=max(recent,time.monotonic()-self.started)
        t0=max(0.,recent-window);t1=max(15.,recent)
        visible=[r for r in records if r['elapsed_s']>=t0]
        vals=[r['estimated_m'] for r in visible]
        if ref is not None:vals.append(ref)
        if not vals:vals=[0,4]
        lo=max(0.,min(vals)-max(0.35,(max(vals)-min(vals))*.13))
        hi=max(vals)+max(.35,(max(vals)-min(vals))*.13)
        if hi-lo<1.0:mid=(hi+lo)/2;lo=max(0.,mid-.5);hi=lo+1.0
        if hi<=lo:hi=lo+1
        def X(t):return x0+(t-t0)/max(t1-t0,1.e-9)*(x1-x0)
        def Y(v):return y1-(v-lo)/(hi-lo)*(y1-y0)
        # Plot grid and labels.
        for j in range(5):
            y=y0+(y1-y0)*j/4
            v=hi-(hi-lo)*j/4
            canvas.create_line(x0,y,x1,y,fill=GRID)
            canvas.create_text(x0-5,y,text=f'{v:.1f}',anchor='e',font=('DejaVu Sans',8),fill='#657080')
        for j in range(5):
            x=x0+(x1-x0)*j/4
            t=t0+(t1-t0)*j/4
            canvas.create_line(x,y0,x,y1,fill=GRID)
            canvas.create_text(x,y1+10,text=f'{t:.0f}',font=('DejaVu Sans',8),fill='#657080')
        canvas.create_line(x0,y0,x0,y1,x1,y1,fill='#718096')
        canvas.create_text((x0+x1)/2,H-12,text='Thời gian kể từ lúc ghi (s)',
                           font=('DejaVu Sans',8),fill='#586372')
        canvas.create_text(4,y0,text='m',anchor='w',font=('DejaVu Sans',8),fill='#657080')
        if ref is not None:
            y=Y(ref);canvas.create_line(x0,y,x1,y,fill=RED,width=2,dash=(7,4))
        if len(visible)>=2:
            coords=[]
            for r in visible:coords.extend((X(r['elapsed_s']),Y(r['estimated_m'])))
            canvas.create_line(*coords,fill=BLUE,width=1.9,smooth=False)
        for r in visible[-180:]:
            x,y=X(r['elapsed_s']),Y(r['estimated_m'])
            canvas.create_oval(x-1.35,y-1.35,x+1.35,y+1.35,fill=BLUE,outline='')
        n=len(records)
        if n:
            mae=sum(r['absolute_error_m'] for r in records)/n
            bias=sum(r['error_m'] for r in records)/n
            last=records[-1]
            label=f'MẪU {n}  |  RSSI {last["rssi_dbm"]:.0f} dBm  |  MAE {mae:.2f} m  |  Bias {bias:+.2f} m'
            status=f'Dự đoán {last["estimated_m"]:.2f} m  |  Thực {last["reference_m"]:.2f} m'
        else:
            label='Chưa có mẫu RSSI mới / chưa có mô hình CALIB'
            status='Đường xanh: RSSI → khoảng cách (sau CALIB)'
        canvas.create_text(x0,10,text=label,anchor='w',fill=TXT,font=('DejaVu Sans',8,'bold'))
        canvas.create_text(x1,y0+5,text=status,anchor='ne',fill='#556070',font=('DejaVu Sans',8))

    def redraw(self):
        for aid in IDS:self.draw_one(aid)

    def export_csv(self):
        records=[rec for aid in IDS for rec in self.samples[aid]]
        if not records:
            messagebox.showinfo('Lưu CSV','Chưa ghi được mẫu RSSI hợp lệ.',parent=self.winfo_toplevel());return
        name=time.strftime('rssi_distance_plot_%Y%m%d_%H%M%S.csv')
        path=filedialog.asksaveasfilename(parent=self.winfo_toplevel(),defaultextension='.csv',
              initialfile=name,filetypes=[('CSV','*.csv')])
        if not path:return
        cols=['timestamp','elapsed_s','anchor','seq','rssi_dbm','reference_m','estimated_m',
              'error_m','absolute_error_m','cal_A','cal_n','cal_points','provisional','mode','bssid','session']
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
                writer.writerows(sorted(records,key=lambda v:(v['elapsed_s'],v['anchor'])))
        except OSError as exc:
            messagebox.showerror('Lưu CSV',str(exc),parent=self.winfo_toplevel());return
        self.message.set(f'Đã lưu {len(records)} mẫu: {Path(path).name}')
