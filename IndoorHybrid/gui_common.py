"""Shared GUI layout and protocol, Python standard library only."""
from __future__ import annotations
import os,sys,socket,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BG='#FFFFFF';PANEL='#F5F5F5';TEXT='#171717';MUTED='#686868';DARK='#222222';BORDER='#DCDCDC'
COLORS={'bg':BG,'panel':PANEL,'panel2':'#EEEEEE','fg':TEXT,'muted':MUTED,
        'accent':DARK,'warn':'#6A6A6A','bad':'#AD3333','blue':'#333333'}

def configure_style(root):
    import tkinter as tk
    from tkinter import ttk
    root.configure(bg=BG)
    st=ttk.Style(root)
    try:st.theme_use('clam')
    except tk.TclError:pass
    font=('DejaVu Sans',10)
    st.configure('.',font=font,background=BG,foreground=TEXT)
    st.configure('TFrame',background=BG)
    st.configure('Panel.TFrame',background=PANEL)
    st.configure('TLabel',background=BG,foreground=TEXT)
    st.configure('Panel.TLabel',background=PANEL,foreground=TEXT)
    st.configure('Muted.TLabel',background=BG,foreground=MUTED)
    st.configure('Header.TLabel',font=('DejaVu Sans',16,'bold'),background=BG,foreground=TEXT)
    st.configure('TLabelframe',background=BG,foreground=TEXT,bordercolor=BORDER)
    st.configure('TLabelframe.Label',background=BG,foreground=TEXT,font=('DejaVu Sans',10,'bold'))
    st.configure('TButton',background='#E9E9E9',foreground=TEXT,padding=(11,7),borderwidth=0)
    st.map('TButton',background=[('active','#D3D3D3'),('disabled','#F2F2F2')],foreground=[('disabled','#909090')])
    st.configure('Accent.TButton',background=DARK,foreground='white',padding=(11,8),font=('DejaVu Sans',10,'bold'))
    st.map('Accent.TButton',background=[('active','#454545'),('disabled','#B0B0B0')],foreground=[('active','white'),('disabled','white')])
    st.configure('TEntry',fieldbackground='white',foreground=TEXT,insertcolor=TEXT)
    st.configure('TCombobox',fieldbackground='white',background='#ECECEC',foreground=TEXT)
    st.configure('Treeview',background='white',fieldbackground='white',foreground=TEXT,rowheight=24)
    st.map('Treeview',background=[('selected','#D6D6D6')],foreground=[('selected',TEXT)])
    st.configure('Treeview.Heading',background='#ECECEC',foreground=TEXT,font=('DejaVu Sans',9,'bold'))
    st.configure('TProgressbar',troughcolor='#F2F2F2',background=DARK)
    return st

def python_cmd(script,*args):return [sys.executable,'-u',str(ROOT/script),*map(str,args)]

def new_process(cmd):
    kw={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    return subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
       stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,**kw)

def send_control(action,port=8766,**args):
    msg={'protocol_version':2,'type':'control','action':action,**args}
    with socket.create_connection(('127.0.0.1',port),timeout=1.5) as sk:
        sk.settimeout(3)
        sk.sendall((json.dumps(msg)+'\n').encode())
        with sk.makefile('rb') as fp:data=fp.readline(200000)
    if not data:raise ConnectionError('Không nhận được phản hồi từ Collector')
    res=json.loads(data.decode('utf-8'))
    if not res.get('ok'):raise ValueError(res.get('error','Lỗi Collector'))
    return res

def recent_lan_ips():
    addrs=[]
    try:
        if sys.platform.startswith('linux'):
            p=subprocess.run(['hostname','-I'],text=True,capture_output=True,timeout=2)
            addrs.extend(p.stdout.split())
        addrs.extend(x[4][0] for x in socket.getaddrinfo(socket.gethostname(),None,family=socket.AF_INET))
    except (OSError,subprocess.TimeoutExpired):pass
    return list(dict.fromkeys(x for x in addrs if not x.startswith('127.')))

def read_json(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return default

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    p=path.with_suffix(path.suffix+'.tmp')
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');p.replace(path)
