"""Small one-click GUI for L1..L4 client laptops, Windows and Ubuntu."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import queue
import re
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from gui_common import COLORS, ROOT, configure_style, new_process, python_cmd, read_json, write_json


class AnchorApp:
    def __init__(self, root):
        self.root = root
        root.title('IndoorSystem · Anchor Client')
        root.geometry('700x595')
        root.minsize(570, 530)
        configure_style(root)
        self.process = None
        self.events = queue.Queue()
        self.config_path = ROOT / 'data' / 'gui' / ('anchor_' + re.sub(r'[^A-Za-z0-9_.-]', '_', socket.gethostname()) + '.json')
        config = read_json(self.config_path, {})
        self.anchor = tk.StringVar(value=config.get('anchor', 'L2'))
        self.session = tk.StringVar(value=config.get('session', 'room_final_01'))
        self.host = tk.StringVar(value=config.get('host', '172.20.10.2'))
        self.interval = tk.StringVar(value=config.get('interval', '1.0'))
        self.iface = tk.StringVar(value=config.get('iface', ''))
        self.keep_awake = tk.BooleanVar(value=config.get('keep_awake', True))
        self.connection = tk.StringVar(value='Chưa chạy')
        self.rssi = tk.StringVar(value='-- dBm')
        self.sample_count = tk.StringVar(value='0 mẫu')
        self.awake_active = False
        self.make_ui()
        root.after(150, self.process_events)
        root.protocol('WM_DELETE_WINDOW', self.on_close)

    def make_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='TRẠM THU RSSI', style='Header.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Không nhập tọa độ ở đây. Tất cả thao tác TRAIN thực hiện trên Master.',
                  style='Muted.TLabel').pack(anchor='w', pady=(1, 12))
        params = ttk.LabelFrame(outer, text='Cấu hình kết nối', padding=12)
        params.pack(fill='x')
        for idx in range(2):
            params.columnconfigure(idx * 2 + 1, weight=1)
        labels = [('Anchor ID', self.anchor, 0, 0), ('Session', self.session, 0, 2),
                  ('Master IP', self.host, 1, 0), ('Interval (s)', self.interval, 1, 2),
                  ('Ubuntu interface (optional)', self.iface, 2, 0)]
        for label, variable, row, col in labels:
            ttk.Label(params, text=label).grid(row=row, column=col, sticky='w', padx=(0, 7), pady=6)
            if label == 'Anchor ID':
                widget = ttk.Combobox(params, textvariable=variable, values=('L1', 'L2', 'L3', 'L4'), state='readonly', width=10)
            else:
                widget = ttk.Entry(params, textvariable=variable, width=18)
            widget.grid(row=row, column=col + 1, sticky='ew', padx=(0, 12), pady=6)
        ttk.Checkbutton(params, text='Giữ Windows không tự Sleep khi đang thu (không đổi cài đặt lâu dài)',
                        variable=self.keep_awake).grid(row=3, column=0, columnspan=4, sticky='w', pady=4)
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=12)
        self.start_button = ttk.Button(controls, text='▶  BẮT ĐẦU THU RSSI', style='Accent.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(controls, text='■  DỪNG', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        stats = ttk.Frame(outer, style='Panel.TFrame', padding=12)
        stats.pack(fill='x')
        ttk.Label(stats, textvariable=self.rssi, style='Panel.TLabel', font=('DejaVu Sans', 17, 'bold')).pack(side='left', padx=(0, 25))
        ttk.Label(stats, textvariable=self.connection, style='Panel.TLabel').pack(side='left')
        ttk.Label(stats, textvariable=self.sample_count, style='Panel.TLabel').pack(side='right')
        ttk.Label(outer, text='Nhật ký thu và truyền dữ liệu', style='Muted.TLabel').pack(anchor='w', pady=(12, 4))
        logframe = ttk.Frame(outer)
        logframe.pack(fill='both', expand=True)
        self.log = tk.Text(logframe, wrap='word', bg=COLORS['panel'], fg=COLORS['fg'],
                           insertbackground=COLORS['fg'], relief='flat', font=('DejaVu Sans Mono', 9))
        scroll = ttk.Scrollbar(logframe, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.write_log('Kiểm tra IP Master và session rồi nhấn BẮT ĐẦU. Máy phải nối vào hotspot iPhone.')

    def write_log(self, line):
        self.log.insert('end', line.rstrip() + '\n')
        lines = int(self.log.index('end-1c').split('.')[0])
        if lines > 800:
            self.log.delete('1.0', '200.0')
        self.log.see('end')

    def windows_awake(self, enabled):
        if os.name != 'nt':
            return
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED. Do not prevent user-initiated sleep.
        try:
            flags = 0x80000001 if enabled else 0x80000000
            if ctypes.windll.kernel32.SetThreadExecutionState(flags) == 0:
                raise OSError('SetThreadExecutionState failed')
            self.awake_active = enabled
        except (OSError, AttributeError) as exc:
            self.write_log('[WARNING] Không đặt được chế độ chống tự Sleep: ' + str(exc))

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        session, aid = self.session.get().strip(), self.anchor.get().strip()
        host = self.host.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', session):
            messagebox.showerror('Session', 'Session chỉ dùng A-Z, 0-9, _, . hoặc -.')
            return
        if aid not in ('L1', 'L2', 'L3', 'L4') or not host or any(c.isspace() for c in host):
            messagebox.showerror('Cấu hình', 'Kiểm tra Anchor ID và Master IP.')
            return
        try:
            interval = float(self.interval.get())
            if not 0.2 <= interval <= 60:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Interval', 'Nhập giá trị từ 0.2 đến 60 giây.')
            return
        opts = ['--id', aid, '--session', session, '--server', host + ':8765', '--interval', str(interval)]
        if self.iface.get().strip():
            opts.extend(('--iface', self.iface.get().strip()))
        try:
            self.process = new_process(python_cmd('anchor/anchor_client.py', *opts))
        except OSError as exc:
            messagebox.showerror('Không khởi chạy được', str(exc))
            return
        write_json(self.config_path, {'anchor': aid, 'session': session, 'host': host,
                                      'interval': self.interval.get(), 'iface': self.iface.get(),
                                      'keep_awake': self.keep_awake.get()})
        if self.keep_awake.get():
            self.windows_awake(True)
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.connection.set('Đang đọc Wi-Fi…')
        self.write_log('--- BẮT ĐẦU ' + aid + ' / ' + session + ' / ' + host + ' ---')
        threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()

    def read_output(self, process):
        try:
            for line in process.stdout:
                self.events.put(('log', line))
        except (OSError, ValueError):
            pass
        self.events.put(('exit', process))

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.windows_awake(False)
        self.stop_button.configure(state='disabled')
        self.start_button.configure(state='normal')
        self.connection.set('Đã dừng')

    def process_events(self):
        while True:
            try:
                kind, item = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                line = item.rstrip()
                self.write_log(line)
                m = re.search(r'#[0-9]+\s*\|\s*(-?\d+(?:\.\d+)?) dBm\s*\|\s*(.+)$', line)
                if m:
                    self.rssi.set(m.group(1) + ' dBm')
                    count = re.search(r'#(\d+)', line)
                    if count:
                        self.sample_count.set(count.group(1) + ' mẫu')
                    self.connection.set(m.group(2))
                elif '[READ ERROR' in line:
                    self.connection.set('Lỗi đọc RSSI')
            elif kind == 'exit' and item is self.process:
                self.windows_awake(False)
                self.start_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                self.connection.set('Client đã thoát')
        self.root.after(150, self.process_events)

    def on_close(self):
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno('Dừng client?', 'Đóng cửa sổ sẽ dừng thu RSSI trên laptop này. Tiếp tục?'):
                return
            self.stop()
        self.root.destroy()


if __name__ == '__main__':
    app_root = tk.Tk()
    AnchorApp(app_root)
    app_root.mainloop()
