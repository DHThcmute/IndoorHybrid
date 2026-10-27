"""Real-time 4-anchor RSSI range localization. No training CSV or Radio Map."""
from __future__ import annotations
import math,queue,subprocess,threading,time,tkinter as tk
from collections import deque
from tkinter import ttk,messagebox,filedialog
from pathlib import Path
from gui_common import ROOT,configure_style,send_control,new_process,python_cmd,recent_lan_ips,read_json,write_json
from core import IDS,DEFAULT_LAYOUT,validate_layout
from range_plot_gui import RangePlotTab

class App:
    def __init__(self,root):
        self.root=root;root.title('IndoorSystem — HYBRID LIVE + IMU / Probabilistic RSSI');root.geometry('1510x920');root.minsize(1120,760)
        configure_style(root)
        self.layout=read_json(ROOT/'config'/'layout_draft.json',DEFAULT_LAYOUT)
        try:self.layout=validate_layout(self.layout)
        except (ValueError,KeyError):self.layout=validate_layout(DEFAULT_LAYOUT)
        self.server=None;self.local=None;self.boot_attempt=0;self.q=queue.Queue();self.track=deque(maxlen=90)
        self.last_timestamp=None;self.last_mode='';self.active=False
        self.session=tk.StringVar(value='room_live')
        self.anchorvars={a:[tk.StringVar(value=str(v)) for v in self.layout['anchors'][a]] for a in IDS}
        self.polyvars=[[tk.StringVar(value=str(x)) for x in p] for p in self.layout['polygon']]
        self.phonez=tk.StringVar(value=str(self.layout['phone_z']))
        self.refx=tk.StringVar(value='3.0');self.refy=tk.StringVar(value='2.0')
        self.refz=tk.StringVar(value='0.8');self.n=tk.StringVar(value='8')
        self.one_id=tk.StringVar(value='L1');self.one_distance=tk.StringVar(value='2.0')
        self.testx=tk.StringVar(value='3.0');self.testy=tk.StringVar(value='2.0')
        self.coords=tk.StringVar(value='—, — m');self.info=tk.StringVar(value='Chưa khởi chạy. Không dùng dữ liệu huấn luyện cũ.')
        self.progress=tk.StringVar(value='Chưa hiệu chuẩn.')
        self.net=tk.StringVar(value='MASTER OFFLINE');self.rate=tk.StringVar(value='Bản đồ theo thời gian thực')
        self.exclude_var=tk.StringVar(value='Không');self.auto_weight=tk.BooleanVar(value=True)
        self.reliability_loaded=False
        self.display_var=tk.StringVar(value='hybrid');self.display_loaded=False
        self.hybrid_status=tk.StringVar(value='Chưa có mô hình Hybrid. CALIB nhiều mốc trước khi START LIVE.')
        self.hybrid_notice=tk.StringVar(value='Chỉ nhập dữ liệu cũ khi đúng BSSID, vị trí anchor và chiều cao iPhone.')
        self.imu_enabled=tk.BooleanVar(value=False)
        self.imu_stride=tk.StringVar(value='0.62')
        self.imu_mapangle=tk.StringVar(value='0')
        self.imu_line=tk.StringVar(value='IMU chưa kết nối — Wi-Fi vẫn hoạt động độc lập.')
        self.imu_url=tk.StringVar(value='http://IP_MASTER:8767/imu')
        self.imu_settings_loaded=False
        self.geometry_xy=None;self.hybrid_xy=None;self.hybrid_uncertainty=None;self.hybrid_alt=None
        self.tiles={};self.build();root.after(200,self.drain);root.after(600,self.poll)
        root.protocol('WM_DELETE_WINDOW',self.close)

    def build(self):
        outer=ttk.Frame(self.root,padding=10);outer.pack(fill='both',expand=True)
        top=ttk.Frame(outer);top.pack(fill='x')
        ttk.Label(top,text='INDOOR SYSTEM',style='Header.TLabel').pack(side='left')
        ttk.Label(top,text='   RSSI 4 ANCHOR → LIKELIHOOD 2D + IMU (TÙY CHỌN) → KALMAN',style='Muted.TLabel').pack(side='left')
        ttk.Label(top,textvariable=self.net,font=('DejaVu Sans',11,'bold')).pack(side='right')
        conn=ttk.LabelFrame(outer,text='1  KẾT NỐI BỐN LAPTOP — HYBRID ĐỘC LẬP',padding=8);conn.pack(fill='x',pady=(7,6))
        ttk.Label(conn,text='Session').pack(side='left');ttk.Entry(conn,textvariable=self.session,width=16).pack(side='left',padx=(4,9))
        ttk.Button(conn,text='CHẠY MASTER + L1',style='Accent.TButton',command=self.start_master).pack(side='left')
        ttk.Button(conn,text='DỪNG MASTER',command=self.stop_master).pack(side='left',padx=5)
        ttk.Button(conn,text='PHÒNG / TỨ GIÁC / VỊ TRÍ L1–L4',command=self.edit_layout).pack(side='left',padx=5)
        ip=', '.join(x for x in recent_lan_ips() if ':' not in x)
        ttk.Label(conn,text='IP Master: '+ip[:56],style='Muted.TLabel').pack(side='right')
        anchors=ttk.Frame(outer);anchors.pack(fill='x')
        for aid in IDS:
            f=ttk.Frame(anchors,style='Panel.TFrame',padding=(14,8));f.pack(side='left',fill='x',expand=True,padx=2)
            ttk.Label(f,text=aid+'  '+('MASTER' if aid=='L1' else 'REMOTE'),style='Panel.TLabel').pack(anchor='w')
            r=ttk.Label(f,text='— dBm',style='Panel.TLabel',font=('DejaVu Sans',15,'bold'));r.pack(anchor='w')
            d=ttk.Label(f,text='RSSI: —',style='Panel.TLabel');d.pack(anchor='w')
            p=ttk.Label(f,text='CAL: —',style='Panel.TLabel');p.pack(anchor='w')
            q=ttk.Label(f,text='Tin cậy: —',style='Panel.TLabel');q.pack(anchor='w')
            self.tiles[aid]=(r,d,p,q)
        central=ttk.Frame(outer);central.pack(fill='both',expand=True,pady=(7,0))
        lf=ttk.LabelFrame(central,text='2  VỊ TRÍ LIVE / PLOT KHOẢNG CÁCH 4 ANCHOR',padding=7)
        lf.pack(side='left',fill='both',expand=True,padx=(0,8))
        self.view_tabs=ttk.Notebook(lf)
        self.view_tabs.pack(fill='both',expand=True)
        map_tab=ttk.Frame(self.view_tabs)
        plot_tab=ttk.Frame(self.view_tabs)
        self.view_tabs.add(map_tab,text='  BẢN ĐỒ / LIVE  ')
        self.view_tabs.add(plot_tab,text='  PLOT KHOẢNG CÁCH L1–L4  ')
        self.canvas=tk.Canvas(map_tab,bg='white',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        ttk.Label(map_tab,text='● Vị trí đang chọn    ○ Chưa lọc    ◌ vùng bất định Hybrid (tham khảo)    ── Quỹ đạo',style='Muted.TLabel').pack(anchor='w')
        self.plot_panel=RangePlotTab(plot_tab)
        self.plot_panel.pack(fill='both',expand=True)
        side=ttk.Frame(central);side.pack(side='left',fill='y')
        right_canvas=tk.Canvas(side,width=510,highlightthickness=0,bg='#F5F5F5')
        scroll=ttk.Scrollbar(side,orient='vertical',command=right_canvas.yview)
        scroll.pack(side='right',fill='y')
        right_canvas.pack(side='left',fill='both',expand=True)
        right_canvas.configure(yscrollcommand=scroll.set)
        right=ttk.Frame(right_canvas)
        right_window=right_canvas.create_window((0,0),window=right,anchor='nw')
        right.bind('<Configure>',lambda e:right_canvas.configure(scrollregion=right_canvas.bbox('all')))
        right_canvas.bind('<Configure>',lambda e:right_canvas.itemconfigure(right_window,width=e.width))
        def wheel(e):right_canvas.yview_scroll(-int(e.delta/120) if e.delta else 0,'units')
        right_canvas.bind('<Enter>',lambda e:right_canvas.bind_all('<MouseWheel>',wheel))
        right_canvas.bind('<Leave>',lambda e:right_canvas.unbind_all('<MouseWheel>'))
        pos=ttk.LabelFrame(right,text='3  TỌA ĐỘ LIVE',padding=9);pos.pack(fill='x',pady=(0,7))
        ttk.Label(pos,textvariable=self.coords,font=('DejaVu Sans',25,'bold')).pack(anchor='w')
        ttk.Label(pos,textvariable=self.info,style='Muted.TLabel',wraplength=455).pack(anchor='w',pady=5)
        row=ttk.Frame(pos);row.pack(fill='x',pady=3)
        ttk.Button(row,text='START LIVE',style='Accent.TButton',command=lambda:self.act('start_live')).pack(side='left')
        ttk.Button(row,text='STOP LIVE',command=lambda:self.act('stop_live')).pack(side='left',padx=7)
        ttk.Label(pos,textvariable=self.rate,style='Muted.TLabel').pack(anchor='w',pady=4)
        hy=ttk.LabelFrame(right,text='4  MÔ HÌNH HYBRID XÁC SUẤT — ĐỊNH VỊ TRỰC TIẾP TỪ RSSI',padding=8)
        hy.pack(fill='x',pady=(0,7))
        ttk.Label(hy,textvariable=self.hybrid_status,style='Muted.TLabel',wraplength=455).pack(anchor='w')
        mode=ttk.Frame(hy);mode.pack(fill='x',pady=(7,6))
        ttk.Label(mode,text='Điểm hiển thị:').pack(side='left')
        ttk.Combobox(mode,textvariable=self.display_var,values=('hybrid','geometry'),state='readonly',width=12).pack(side='left',padx=6)
        ttk.Button(mode,text='CHỌN CHẾ ĐỘ',command=self.set_display).pack(side='left')
        ttk.Label(hy,text='hybrid = trường xác suất RSSI (chính); geometry = định vị khoảng cách (đối chứng).',
                  style='Muted.TLabel',wraplength=455).pack(anchor='w')
        ttk.Button(hy,text='XÂY / CẬP NHẬT MÔ HÌNH HYBRID TỪ CÁC MỐC ĐÃ ĐO',
                   style='Accent.TButton',command=self.build_hybrid).pack(fill='x',pady=(9,5))
        extra=ttk.Frame(hy);extra.pack(fill='x')
        ttk.Button(extra,text='NHẬP MỐC TỪ CSV (tùy chọn)',command=self.import_hybrid).pack(side='left')
        ttk.Button(extra,text='XÓA MỐC HYBRID',command=self.clear_hybrid).pack(side='left',padx=6)
        ttk.Label(hy,textvariable=self.hybrid_notice,style='Muted.TLabel',wraplength=455).pack(anchor='w',pady=(5,0))
        trust=ttk.LabelFrame(right,text='ĐỘ TIN CẬY ANCHOR / SO SÁNH 3–4 MÁY',padding=7)
        trust.pack(fill='x',pady=(0,7))
        rr=ttk.Frame(trust);rr.pack(fill='x')
        ttk.Checkbutton(rr,text='Trọng số tự động',variable=self.auto_weight).pack(side='left')
        ttk.Label(rr,text='Loại khỏi phép tính:').pack(side='left',padx=(8,4))
        ttk.Combobox(rr,textvariable=self.exclude_var,values=('Không',*IDS),width=7,
                     state='readonly').pack(side='left')
        ttk.Button(rr,text='ÁP DỤNG',command=self.save_reliability).pack(side='left',padx=7)
        ttk.Label(trust,text='Chỉ đổi khi STOP LIVE. L3 bị loại vẫn có thể gửi RSSI; 3 máy còn lại phải không thẳng hàng. Điểm tin cậy chỉ là chẩn đoán từ CALIB, không phải xác suất đúng.',
                  style='Muted.TLabel',wraplength=455).pack(anchor='w')
        imu=ttk.LabelFrame(right,text='IMU IPHONE — SENSOR LOGGER / PDR (THỬ NGHIỆM)',padding=8)
        imu.pack(fill='x',pady=(0,7))
        ttk.Label(imu,textvariable=self.imu_line,style='Muted.TLabel',wraplength=455).pack(anchor='w')
        ttk.Label(imu,textvariable=self.imu_url,wraplength=455).pack(anchor='w',pady=(2,4))
        ttk.Label(imu,text='Trên iPhone: Sensor Logger → HTTP Push → URL phía trên; bật Accelerometer + Orientation. Giữ máy hướng theo hướng đi.',
                  style='Muted.TLabel',wraplength=455).pack(anchor='w')
        r=ttk.Frame(imu);r.pack(fill='x',pady=(6,3))
        ttk.Checkbutton(r,text='Dùng IMU làm prior mềm',variable=self.imu_enabled).pack(side='left')
        ttk.Label(r,text='Bước (m)').pack(side='left',padx=(10,3))
        ttk.Entry(r,textvariable=self.imu_stride,width=7).pack(side='left')
        ttk.Button(r,text='ÁP DỤNG IMU',command=self.apply_imu).pack(side='left',padx=6)
        r=ttk.Frame(imu);r.pack(fill='x',pady=(3,0))
        ttk.Label(r,text='Đặt ĐẦU iPhone theo hướng bản đồ (độ):').pack(side='left')
        ttk.Entry(r,textvariable=self.imu_mapangle,width=7).pack(side='left',padx=5)
        ttk.Button(r,text='CĂN HƯỚNG',command=self.align_imu).pack(side='left')
        ttk.Label(imu,text='0° = +X (phải); 90° = +Y (lên). Phải STOP LIVE để căn hướng. Không xoay điện thoại trong tay sau khi căn. Nếu IMU cũ/mất: trở về RSSI-only.',
                  style='Muted.TLabel',wraplength=455).pack(anchor='w',pady=(5,0))
        cal=ttk.LabelFrame(right,text='5  THU MỐC TỌA ĐỘ THẬT CHO HYBRID — CALIB CẢ 4 ANCHOR',padding=8);cal.pack(fill='x',pady=(0,7))
        ttk.Label(cal,text='Đặt iPhone cố định, nhập X/Y/Z thật. Mỗi lượt sẽ lưu 4 RSSI làm một mốc HYBRID. Ít nhất 8 mốc; nên đo 12–25 mốc trải rộng phòng.',
                  style='Muted.TLabel',wraplength=455).pack(anchor='w')
        r=ttk.Frame(cal);r.pack(fill='x',pady=5)
        for title,var in [('X',self.refx),('Y',self.refy),('Z',self.refz),('Số mẫu',self.n)]:
            ttk.Label(r,text=title).pack(side='left',padx=(0,2));ttk.Entry(r,textvariable=var,width=6).pack(side='left',padx=(0,7))
        ttk.Button(cal,text='CALIB CẢ 4 MÁY TẠI MỐC NÀY',style='Accent.TButton',
                   command=self.cal_all).pack(fill='x',pady=(1,5))
        ttk.Label(cal,text='Hoặc CALIB từng anchor tại khoảng cách đo bằng thước:',style='Muted.TLabel').pack(anchor='w')
        r=ttk.Frame(cal);r.pack(fill='x',pady=5)
        ttk.Combobox(r,textvariable=self.one_id,values=IDS,state='readonly',width=6).pack(side='left')
        ttk.Label(r,text='Khoảng cách thực (m)').pack(side='left',padx=8)
        ttk.Entry(r,textvariable=self.one_distance,width=9).pack(side='left')
        ttk.Button(r,text='CALIB ANCHOR',command=self.cal_one).pack(side='left',padx=9)
        r=ttk.Frame(cal);r.pack(fill='x',pady=4)
        ttk.Button(r,text='HỦY LƯỢT CALIB',command=lambda:self.act('cancel_cal')).pack(side='left')
        ttk.Button(r,text='XÓA TOÀN BỘ CALIB',command=self.clear_cal).pack(side='left',padx=6)
        ttk.Label(cal,textvariable=self.progress,wraplength=440,style='Muted.TLabel').pack(anchor='w',pady=(5,0))
        eva=ttk.LabelFrame(right,text='6  KIỂM TRA TẠI VỊ TRÍ CHƯA DÙNG HIỆU CHUẨN',padding=8)
        eva.pack(fill='x',pady=(0,7))
        r=ttk.Frame(eva);r.pack(fill='x')
        ttk.Label(r,text='X thật').pack(side='left');ttk.Entry(r,textvariable=self.testx,width=7).pack(side='left',padx=5)
        ttk.Label(r,text='Y thật').pack(side='left');ttk.Entry(r,textvariable=self.testy,width=7).pack(side='left',padx=5)
        ttk.Button(r,text='GHI / TÍNH SAI SỐ',command=self.record_test).pack(side='left',padx=5)
        ttk.Label(right,text='Trễ mục tiêu <6 s; hiển thị tuổi RSSI để biết dữ liệu có bị cũ.',
                  style='Muted.TLabel',wraplength=470).pack(anchor='w',pady=3)
        log=ttk.LabelFrame(right,text='7  NHẬT KÝ / CẢNH BÁO',padding=7);log.pack(fill='both',expand=True)
        self.log=tk.Text(log,height=8,bg='#F7F7F7',fg='#171717',font=('DejaVu Sans Mono',9),wrap='word',relief='flat')
        self.log.pack(fill='both',expand=True)
        self.note('Bản HYBRID độc lập: CALIB 8–25 điểm tọa độ thật, XÂY MÔ HÌNH, START LIVE. Không tự nạp dữ liệu cũ.')
        self.draw()

    def note(self,message):
        self.log.insert('end',time.strftime('%H:%M:%S')+' '+str(message)+'\n')
        if int(self.log.index('end-1c').split('.')[0])>500:self.log.delete('1.0','100.0')
        self.log.see('end')
    def drain(self):
        try:
            while True:
                k,msg=self.q.get_nowait()
                if k=='LOG':self.note(msg.rstrip())
                elif k=='STOP':self.note(msg+' đã dừng')
        except queue.Empty:pass
        self.root.after(150,self.drain)
    def stream(self,proc,title):
        try:
            for line in proc.stdout:self.q.put(('LOG',f'[{title}] {line.rstrip()}'))
        except (OSError,ValueError):pass
        self.q.put(('STOP',title))
    def start_master(self):
        if self.server and self.server.poll() is None:
            messagebox.showinfo('Master','Master đã chạy rồi.');return
        try:
            send_control('status')
        except (OSError,ValueError,ConnectionError):
            pass
        else:
            messagebox.showerror('Cổng Master đang được sử dụng',
                'Một Master khác đang chạy cổng 8766. Hãy dừng RangeLive v2 hoặc Hybrid cũ trước khi mở ứng dụng này.')
            return
        try:
            self.boot_attempt=0
            self.server=new_process(python_cmd('collector.py','--session',self.session.get().strip()))
            threading.Thread(target=self.stream,args=(self.server,'MASTER'),daemon=True).start()
            self.net.set('MASTER đang mở...');self.root.after(1150,self.start_local)
        except OSError as e:messagebox.showerror('Không mở Master',str(e))
    def start_local(self):
        if self.server is None or self.server.poll() is not None:
            self.net.set('MASTER KHÔNG CHẠY')
            self.note('Master không khởi động: có thể cổng 8765/8766 đã được ứng dụng khác dùng.')
            return
        try:
            status=send_control('status')
            self.layout=status['layout'];self.draw()
            self.local=new_process(python_cmd('anchor/anchor_client.py','--id','L1','--session',status['session'],
                               '--server','127.0.0.1:8765','--interval','1.0'))
            threading.Thread(target=self.stream,args=(self.local,'L1'),daemon=True).start()
            self.net.set('MASTER ĐANG CHẠY')
            self.note('Mở Anchor Client cũ trên L2–L4, server=IP Master:8765, session='+status['session'])
        except (OSError,ValueError,ConnectionError) as e:
            self.boot_attempt+=1
            if self.boot_attempt<7 and self.server and self.server.poll() is None:
                self.note('Master đang khởi động, thử lại kết nối...')
                self.root.after(650,self.start_local)
            else:
                self.note('Master khởi động lỗi: '+str(e));self.net.set('KHỞI ĐỘNG LỖI')
    def stop_master(self):
        if self.server is not None and self.server.poll() is None:
            try:send_control('shutdown')
            except (OSError,ValueError,ConnectionError):pass
        for p in (self.local,self.server):
            if p and p.poll() is None:
                try:p.terminate()
                except OSError:pass
        self.local=None;self.server=None;self.net.set('MASTER OFFLINE')
        self.track.clear();self.coords.set('—, — m');self.raw=None;self.current=None
        self.hybrid_uncertainty=None;self.draw()
    def act(self,action,**kwargs):
        try:
            r=send_control(action,**kwargs);self.note(action+' OK')
            if action=='stop_live':self.coords.set('—, — m');self.track.clear();self.draw()
            return r
        except (OSError,ValueError,ConnectionError,KeyError) as e:
            messagebox.showerror(action,str(e));return None
    def save_reliability(self):
        excluded=self.exclude_var.get()
        result=self.act('set_reliability',excluded_anchor=None if excluded=='Không' else excluded,
                        adaptive_weights=bool(self.auto_weight.get()))
        if result:
            self.note('Đã cập nhật trọng số: '+('AUTO' if self.auto_weight.get() else 'BẰNG NHAU')+
                      ', loại '+excluded)
    def set_display(self):
        mode=self.display_var.get()
        r=self.act('set_display_mode',display_mode=mode)
        if r:
            self.track.clear();self.last_timestamp=None
            self.note('Hiển thị '+ ('HYBRID xác suất' if mode=='hybrid' else 'GEOMETRY đối chứng'))

    def apply_imu(self):
        try:
            result=self.act('set_imu',enabled=bool(self.imu_enabled.get()),
                            stride_m=float(self.imu_stride.get()))
            if result:self.note('IMU: '+('BẬT' if self.imu_enabled.get() else 'TẮT')+
                                ' | Cần căn hướng sau khi Sensor Logger gửi orientation.')
        except ValueError:messagebox.showerror('IMU','Chiều dài bước hợp lệ 0.25–1.10 m.')

    def align_imu(self):
        try:
            r=self.act('align_imu',map_angle_deg=float(self.imu_mapangle.get()))
            if r:self.note('Căn hướng IMU thành công. Hãy giữ đầu iPhone theo hướng đi.')
        except ValueError:messagebox.showerror('IMU','Nhập hướng từ -360° đến +360°.')

    def build_hybrid(self):
        result=self.act('build_hybrid')
        if result:
            self.display_var.set('hybrid')
            self.set_display()
            self.hybrid_notice.set('Mô hình sẵn sàng. Có thể START LIVE. Hãy kiểm tra các vị trí chưa dùng để CALIB.')

    def import_hybrid(self):
        filename=filedialog.askopenfilename(parent=self.root,title='Chọn CSV gồm các mốc thật (không trộn BSSID)',
                filetypes=[('CSV','*.csv'),('Tất cả','*.*')])
        if not filename:return
        if not messagebox.askyesno('Xác nhận dữ liệu hiệu chuẩn',
            'Bạn xác nhận CSV dùng CÙNG vị trí L1–L4, hệ tọa độ phòng, chiều cao iPhone và BSSID của hotspot hiện tại?\n\n'
            'Không nhập tập đã dùng để kiểm tra độc lập. Chương trình sẽ từ chối BSSID không khớp.',parent=self.root):return
        r=self.act('import_hybrid_csv',path=filename,geometry_confirmed=True)
        if r:
            self.hybrid_notice.set(f'Đã nạp {r["points_imported"]} mốc từ CSV. Bấm XÂY MÔ HÌNH.')
            self.note(f'Đã nhập thủ công {r["points_imported"]} mốc, chưa dùng làm dự đoán cho tới khi XÂY MÔ HÌNH.')

    def clear_hybrid(self):
        if messagebox.askyesno('Xóa mốc Hybrid','Xóa toàn bộ mốc tọa độ HYBRID? Không ảnh hưởng file CSV gốc.',parent=self.root):
            if self.act('clear_hybrid'):
                self.hybrid_notice.set('Đã xóa mốc Hybrid. CALIB lại rồi XÂY MÔ HÌNH.')
                self.display_var.set('hybrid')

    def cal_all(self):
        try:self.act('cal_all',x=float(self.refx.get()),y=float(self.refy.get()),
                     z=float(self.refz.get()),samples=int(self.n.get()))
        except ValueError:messagebox.showerror('CALIB','Nhập X,Y,Z và số mẫu hợp lệ.')
    def cal_one(self):
        try:self.act('cal_one',anchor=self.one_id.get(),distance=float(self.one_distance.get()),samples=int(self.n.get()))
        except ValueError:messagebox.showerror('CALIB','Nhập khoảng cách và số mẫu hợp lệ.')
    def clear_cal(self):
        if messagebox.askyesno('Xóa hiệu chuẩn','Xóa tất cả mốc RSSI–khoảng cách đã đo?'):
            self.act('clear_calibration')
    def record_test(self):
        try:
            r=self.act('evaluate',x=float(self.testx.get()),y=float(self.testy.get()))
            if r:
                h=r.get('hybrid_error_m');g=r.get('geometry_error_m')
                report=(f'Sai số HYBRID: {h:.2f} m\n' if h is not None else 'HYBRID: chưa có kết quả\n')
                report+=(f'Sai số GEOMETRY: {g:.2f} m\n' if g is not None else 'GEOMETRY: chưa hiệu chuẩn khoảng cách\n')
                report+='Chỉ sử dụng X/Y thật để ghi sai số; không đưa X/Y vào thuật toán LIVE.'
                messagebox.showinfo('KIỂM TRA ĐỘC LẬP',report)
        except ValueError:messagebox.showerror('TEST','Nhập tọa độ X,Y thật hợp lệ.')
    def poll(self):
        if self.server and self.server.poll() is None:
            try:self.apply_status(send_control('status'))
            except (OSError,ValueError,ConnectionError) as e:self.net.set('MẤT KẾT NỐI MASTER')
        self.root.after(500,self.poll)
    def apply_status(self,s):
        self.plot_panel.update_status(s)
        if s['mode']!=self.last_mode:
            self.note('MODE: '+s['mode']);self.last_mode=s['mode']
            if s['mode']!='LIVE':self.track.clear()
        cal=s['calibration'];anch=s['anchors'];rssi_d={}
        hy=s.get('hybrid',{})
        im=s.get('imu',{})
        ips=[x for x in recent_lan_ips() if ':' not in x and not x.startswith('127.')]
        if ips:self.imu_url.set(f'HTTP Push URL: http://{ips[0]}:8767/imu')
        if not self.imu_settings_loaded:
            self.imu_enabled.set(bool(im.get('enabled',False)))
            self.imu_stride.set(str(im.get('stride_m',.62)))
            self.imu_settings_loaded=True
        if im.get('batches',0)==0: imu_message='Chưa nhận gói IMU từ iPhone'
        elif not im.get('fresh'): imu_message='IMU cũ/mất: chỉ dùng RSSI'
        elif not im.get('heading_aligned'): imu_message='IMU đã nhận, cần CĂN HƯỚNG để PDR hoạt động'
        elif not im.get('enabled'): imu_message='IMU đã nhận nhưng chức năng hợp nhất đang TẮT'
        else: imu_message='IMU SẴN SÀNG'+(' (đang hợp nhất)' if ((s.get('last') or {}).get('hybrid') or {}).get('imu_fused') else '')
        self.imu_line.set(f'{imu_message} | gói={im.get("batches",0)} | bước={im.get("steps",0)} | '+
                          f'hướng={im.get("heading_deg")}° | tuổi={im.get("age_s")}s')
        self.hybrid_status.set(f'Mốc tọa độ: {hy.get("points",0)}   |   Mô hình: {"SẴN SÀNG" if hy.get("trained") else "CHƯA XÂY"}   |   {hy.get("warning","")}')
        if not self.display_loaded:
            self.display_var.set(s.get('display_mode','hybrid'));self.display_loaded=True
        setting=s.get('reliability',{})
        if not self.reliability_loaded:
            self.exclude_var.set(setting.get('excluded_anchor') or 'Không')
            self.auto_weight.set(setting.get('adaptive_weights',True))
            self.reliability_loaded=True
        quality=s.get('quality',{})
        active=set(setting.get('active_anchors',IDS))
        for aid in IDS:
            data=anch[aid];r,d,p,q=self.tiles[aid]
            if data['rssi'] is None:
                r.configure(text='— dBm');d.configure(text='Range: — m')
            else:
                r.configure(text=f'{data["rssi"]:.0f} dBm')
                age=data['age_s'];d.configure(text=f'RSSI age: {age:.1f} s'+('  CŨ' if not data['fresh'] else ''))
            c=cal[aid]
            p.configure(text='CAL: '+('—' if c is None else f'{c["points"]} mốc / n={c["n"]:.2f}'+(' ⚠' if c['provisional'] else '')))
            qv=quality.get(aid,{})
            q.configure(text=('KHÔNG DÙNG' if aid not in active else
                              f'Tin cậy: {qv.get("score",0)*100:.0f}/100 — {qv.get("level","—")}'))
        task=s['cal_task']
        if task:self.progress.set('ĐANG CAL: '+', '.join(f'{k} {n}/{task["n"]}' for k,n in task['counts'].items()))
        else:
            complete=sum(bool(cal[a]) for a in IDS)
            self.progress.set(f'Đã CALIB {complete}/4 anchor. Mỗi anchor nên có ≥2 mốc xa nhau.' +
                              ('  [CHƯA ĐỦ MỐC]' if any(cal[a] and cal[a]['provisional'] for a in IDS) else ''))
        latest=s['last'];self.layout=s['layout']
        if latest:
            f=latest['filtered'];raw=latest['raw'];self.coords.set(f'({f[0]:.2f}, {f[1]:.2f}) m')
            self.display_var.set(s.get('display_mode','hybrid'))
            h=latest.get('hybrid');g=latest.get('geometry')
            self.hybrid_xy=tuple(h['filtered']) if h else None
            self.geometry_xy=tuple(g['filtered']) if g else None
            self.hybrid_uncertainty=h['uncertainty_m'] if h else None
            self.hybrid_alt=tuple(h['alternative_xy']) if h else None
            uncertainty=(f'  |  vùng bất định ~{h["uncertainty_m"]:.2f}m (tương đối)' if h else '')
            if h and h.get('imu_fused'):uncertainty+=f'  |  IMU +{h.get("imu_steps_since_wifi",0)} bước'
            self.info.set(f'{s.get("display_mode","hybrid").upper()}  |  RAW ({raw[0]:.2f},{raw[1]:.2f})  |  RSSI age ≤{latest["max_anchor_age_s"]:.2f}s  |  gate={latest["gate"]}'+uncertainty)
            self.rate.set('LIVE — dự đoán chỉ nhận RSSI mới, không sử dụng tọa độ thật của điểm TEST')
            if latest.get('utc')!=self.last_timestamp:
                self.track.append(tuple(f));self.last_timestamp=latest.get('utc')
            for j,aid in enumerate(IDS):
                _,d,_,_=self.tiles[aid]
                dist=latest['ranges_m'][j]
                if dist is not None:
                    d.configure(text=f'{dist:.2f} m | w={latest["weights"][aid]:.3f}')
                elif aid not in latest['active_anchors']:
                    d.configure(text='ĐANG LOẠI TRỪ')
                else:d.configure(text='RSSI trực tiếp → HYBRID')
            self.raw=tuple(raw);self.current=tuple(f)
        else:
            self.coords.set('—, — m');self.info.set('Đợi RSSI mới từ các anchor đang sử dụng. '+str(s['issue'] or ''))
            self.raw=None;self.current=None;self.hybrid_xy=None;self.geometry_xy=None
            self.hybrid_alt=None;self.hybrid_uncertainty=None
            if s['mode']!='LIVE' or s['issue']:self.track.clear()
        self.net.set('MASTER '+s['mode'])
        warning=s['warnings'][-1] if s['warnings'] else None
        if warning and warning!=getattr(self,'last_warning',None):self.note('CẢNH BÁO: '+warning)
        self.last_warning=warning
        self.draw()
    def transform(self):
        poly=self.layout['polygon']
        xs=[p[0] for p in poly];ys=[p[1] for p in poly]
        W=max(200,self.canvas.winfo_width());H=max(200,self.canvas.winfo_height())
        dx=max(xs)-min(xs);dy=max(ys)-min(ys)
        scale=min((W-105)/max(dx,.1),(H-105)/max(dy,.1))
        margin_x=(W-dx*scale)/2; margin_y=(H-dy*scale)/2
        return lambda xy:(margin_x+(xy[0]-min(xs))*scale,
                          H-margin_y-(xy[1]-min(ys))*scale),scale
    def draw(self):
        c=self.canvas;c.delete('all');tf,scale=self.transform();poly=self.layout['polygon']
        coord=[v for p in poly for v in tf(p)]
        c.create_polygon(coord,fill='#FAFAFA',outline='#333333',width=2)
        lo_x=min(p[0] for p in poly);hi_x=max(p[0] for p in poly)
        lo_y=min(p[1] for p in poly);hi_y=max(p[1] for p in poly)
        for x in range(math.floor(lo_x),math.ceil(hi_x)+1):
            pa=tf((x,lo_y));pb=tf((x,hi_y));c.create_line(*pa,*pb,fill='#EDEDED')
        for y in range(math.floor(lo_y),math.ceil(hi_y)+1):
            pa=tf((lo_x,y));pb=tf((hi_x,y));c.create_line(*pa,*pb,fill='#EDEDED')
        c.create_polygon(coord,fill='',outline='#282828',width=2)
        for j,pt in enumerate(poly):
            x,y=tf(pt);c.create_text(x,y-17,text=f'Q{j+1} {pt[0]:g},{pt[1]:g}',font=('DejaVu Sans',9),fill='#777777')
        for aid in IDS:
            a=self.layout['anchors'][aid];x,y=tf(a)
            c.create_rectangle(x-6,y-6,x+6,y+6,fill='#262626',outline='')
            c.create_text(x+8,y+11,text=aid,anchor='nw',fill='#222222',font=('DejaVu Sans',10,'bold'))
        if len(self.track)>1:
            pts=[v for p in self.track for v in tf(p)];c.create_line(*pts,fill='#8A8A8A',width=2,smooth=False)
        if self.display_var.get()=='hybrid' and getattr(self,'current',None) is not None and self.hybrid_uncertainty is not None and math.isfinite(self.hybrid_uncertainty):
            x,y=tf(self.current);r=min(self.hybrid_uncertainty*scale,300)
            c.create_oval(x-r,y-r,x+r,y+r,outline='#AFCBD0',dash=(3,4),width=1)
        if getattr(self,'raw',None) is not None:
            x,y=tf(self.raw);c.create_oval(x-8,y-8,x+8,y+8,outline='#999999',width=2)
        if getattr(self,'current',None) is not None:
            x,y=tf(self.current);c.create_oval(x-8,y-8,x+8,y+8,fill='#171717',outline='white',width=2)
            c.create_text(x+13,y-14,text=f'({self.current[0]:.2f},{self.current[1]:.2f})',anchor='w',fill='#222222')
        c.create_text(18,14,text='1 ô lưới = 1 mét',fill='#666666',anchor='nw')

    def edit_layout(self):
        for j,pt in enumerate(self.layout['polygon']):
            for k in range(2):self.polyvars[j][k].set(str(pt[k]))
        for aid in IDS:
            for k,v in enumerate(self.layout['anchors'][aid]):self.anchorvars[aid][k].set(str(v))
        self.phonez.set(str(self.layout['phone_z']))
        window=tk.Toplevel(self.root);window.title('Thiết lập bản đồ và bốn anchor');window.geometry('680x660')
        window.transient(self.root);window.grab_set()
        body=ttk.Frame(window,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='TỨ GIÁC LỒI — Q1→Q4 NGƯỢC CHIỀU KIM ĐỒNG HỒ',font=('DejaVu Sans',12,'bold')).pack(anchor='w')
        t=ttk.Frame(body);t.pack(fill='x',pady=8)
        for j,vars in enumerate(self.polyvars):
            ttk.Label(t,text=f'Q{j+1}').grid(row=j,column=0,padx=6,pady=4)
            for k in range(2):ttk.Entry(t,textvariable=vars[k],width=12).grid(row=j,column=k+1,padx=9)
        dim=ttk.Frame(body);dim.pack(anchor='w',pady=5)
        ttk.Label(dim,text='Chữ nhật W').pack(side='left');ww=tk.StringVar(value='6')
        ttk.Entry(dim,textvariable=ww,width=7).pack(side='left',padx=4)
        ttk.Label(dim,text='H').pack(side='left');hh=tk.StringVar(value='4')
        ttk.Entry(dim,textvariable=hh,width=7).pack(side='left',padx=4)
        def rectangle():
            try:
                w=float(ww.get());h=float(hh.get())
                if w<1 or h<1:raise ValueError()
                ps=[(0,0),(w,0),(w,h),(0,h)]
                for j,pt in enumerate(ps):
                    for k in range(2):self.polyvars[j][k].set(str(pt[k]))
                for j,aid in enumerate(IDS):
                    for k in range(2):self.anchorvars[aid][k].set(str(ps[j][k]))
            except ValueError:messagebox.showerror('W/H','Chiều dài/rộng phải ≥1 m.',parent=window)
        ttk.Button(dim,text='ĐỔI KÍCH THƯỚC + ĐẶT 4 GÓC',command=rectangle).pack(side='left',padx=8)
        ttk.Label(body,text='VỊ TRÍ ANTEN TỪNG LAPTOP (mét)',font=('DejaVu Sans',12,'bold')).pack(anchor='w',pady=(12,5))
        grid=ttk.Frame(body);grid.pack(anchor='w')
        for j,label in enumerate(('Anchor','X','Y','Z (cao)')):ttk.Label(grid,text=label).grid(row=0,column=j,padx=7)
        for i,aid in enumerate(IDS):
            ttk.Label(grid,text=aid).grid(row=i+1,column=0,pady=6)
            for j,var in enumerate(self.anchorvars[aid]):
                ttk.Entry(grid,textvariable=var,width=10).grid(row=i+1,column=j+1,padx=8)
        r=ttk.Frame(body);r.pack(anchor='w',pady=(9,3))
        ttk.Label(r,text='Chiều cao iPhone Z (m)').pack(side='left')
        ttk.Entry(r,textvariable=self.phonez,width=7).pack(side='left',padx=6)
        ttk.Label(body,text='Dời anchor hoặc đổi chiều cao sẽ XÓA CALIB đã thu.',style='Muted.TLabel').pack(anchor='w',pady=6)
        def apply():
            try:
                layout=validate_layout({'polygon':[[float(v.get()) for v in row] for row in self.polyvars],
                    'anchors':{a:[float(v.get()) for v in self.anchorvars[a]] for a in IDS},
                    'phone_z':float(self.phonez.get())})
                r=self.act('set_layout',layout=layout)
                if r:
                    self.layout=layout;self.raw=None;self.current=None;self.track.clear()
                    write_json(ROOT/'config'/'layout_draft.json',layout)
                    self.draw();window.destroy()
                    if r['calibration_cleared']:self.note('Đổi tọa độ anten: cần CALIB lại.')
            except ValueError as e:messagebox.showerror('Sơ đồ không hợp lệ',str(e),parent=window)
        ttk.Button(body,text='ÁP DỤNG VÀ LƯU BỐ CỤC',style='Accent.TButton',command=apply).pack(fill='x',pady=(15,0))
    def close(self):
        self.stop_master();self.root.destroy()

if __name__=='__main__':
    root=tk.Tk();App(root);root.mainloop()
