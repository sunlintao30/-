from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles

import os, subprocess, time, json, ipaddress, tempfile, datetime, asyncio, socket, shlex, base64, threading
import psutil, requests
from collections import deque

# 使用脚本所在目录作为应用根目录，所有持久化文件均位于此
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(APP_DIR, "state")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
WHITELIST_FILE = os.path.join(APP_DIR, "whitelist.json")
LOG_FILE = os.path.join(APP_DIR, "firewall_web.log")
GEO_MMDB = os.path.join(APP_DIR, "GeoLite2-City.mmdb")
GEO_MMDB_URL = "https://git.io/GeoLite2-City.mmdb"
DEFAULT_PORT = 48080
MAX_WL = 1000

COMMON_PORTS = [21,22,23,25,53,67,68,69,80,110,123,137,139,143,161,389,443,465,587,993,995,1433,1521,1723,2049,2379,2380,3000,3128,3306,3389,3478,3690,4000,4040,4369,5000,5432,5601,5672,5900,5984,6379,7001,7070,8000,8008,8080,8081,8088,8090,8443,8500,8778,8888,9000,9042,9090,9092,9200,9418,9999,11211,18080,27017]

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key="change_me_strong", session_cookie="fw_session", same_site="lax", https_only=False, max_age=7*24*3600)
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")

USERNAME="admin"
PASSWORD="admin"

def ensure_dirs():
    os.makedirs(STATE_DIR, exist_ok=True)

def state_load():
    ensure_dirs()
    try:
        with open(STATE_FILE,"r") as f: s=json.load(f)
    except: s={}
    s.setdefault("panel_port", DEFAULT_PORT)
    s.setdefault("username", USERNAME)
    s.setdefault("password", PASSWORD)
    s.setdefault("forwards", [])
    s.setdefault("acc_rx", 0); s.setdefault("acc_tx", 0)
    s.setdefault("last_rx", 0); s.setdefault("last_tx", 0); s.setdefault("last_ts", 0.0)
    s.setdefault("log_max_bytes", 5*1024*1024)
    return s

def state_save(s):
    with open(STATE_FILE,"w") as f: json.dump(s,f)

state = state_load()
USERNAME = state.get("username", USERNAME)
PASSWORD = state.get("password", PASSWORD)

def wl_load():
    try:
        with open(WHITELIST_FILE,"r") as f: arr=json.load(f)
        if isinstance(arr, list): return [x for x in arr if isinstance(x,str)]
    except: pass
    return []

def wl_save(arr):
    with open(WHITELIST_FILE,"w") as f: json.dump(arr[:MAX_WL], f)

whitelist = deque(wl_load(), maxlen=MAX_WL)
apply_forward_rules()
<<<<<<< ours
<<<<<<< ours
=======

# 恢复白名单对应的 UFW 规则
apply_whitelist_rules()
>>>>>>> theirs
=======

# 恢复白名单对应的 UFW 规则
apply_whitelist_rules()
>>>>>>> theirs

def rotate_log_if_needed():
    try:
        maxb=int(state.get("log_max_bytes",5*1024*1024))
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > maxb:
            os.replace(LOG_FILE, LOG_FILE+".1")
            open(LOG_FILE,"w").close()
    except: pass

def log_action(user, client_ip, action):
    rotate_log_if_needed()
    now=datetime.datetime.now().strftime("%F %T")
    with open(LOG_FILE,"a") as f:
        f.write(f"[{now}] user={user} ip={client_ip} action={action}\n")

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def ufw_enabled():
    out = run("ufw status")
    return "Status: active" in out

def ufw_enable():
    subprocess.run("yes | ufw enable", shell=True)

def ufw_status_numbered():
    return run("ufw status numbered")

def ufw_allow_anywhere(port):
    subprocess.run(f"ufw allow {int(port)}/tcp comment 'fw-web-panel'", shell=True)

def ufw_allow_from_ip_any(ip):
    subprocess.run(f"ufw insert 1 allow from {ip} to any", shell=True)

def ufw_allow_from_ip_port(ip, port):
    subprocess.run(f"ufw insert 1 allow from {ip} to any port {int(port)}", shell=True)

def ufw_delete_rule_number(num):
    subprocess.run(f"yes | ufw delete {int(num)}", shell=True)

def normalize_ip(ip):
    if not ip: return ip
    if ip.startswith("::ffff:"): return ip.split("::ffff:")[-1]
    if "%" in ip: return ip.split("%",1)[0]
    return ip

def apply_forward_rules():
    try:
        for l in run("iptables -t nat -S PREROUTING").splitlines():
            if "fw-web-forward" in l:
                subprocess.run("iptables -t nat " + l.replace("-A","-D",1), shell=True)
        for l in run("iptables -t nat -S POSTROUTING").splitlines():
            if "fw-web-forward" in l:
                subprocess.run("iptables -t nat " + l.replace("-A","-D",1), shell=True)
    except: pass
    try:
        for line in run("ufw status numbered").splitlines():
            if "]" in line and "fw-web-forward" in line:
                try:
                    num=int(line.split("]")[0].strip("[ "))
                    ufw_delete_rule_number(num)
                except: pass
    except: pass
    for f in state.get("forwards", []):
        try:
            sp=int(f.get("src_port")); dip=f.get("dst_ip"); dp=int(f.get("dst_port"))
            subprocess.run(f"iptables -t nat -A PREROUTING -p tcp --dport {sp} -j DNAT --to-destination {dip}:{dp} -m comment --comment fw-web-forward", shell=True)
            subprocess.run(f"iptables -t nat -A POSTROUTING -p tcp -d {dip} --dport {dp} -j MASQUERADE -m comment --comment fw-web-forward", shell=True)
            subprocess.run(f"ufw route allow proto tcp from any to {dip} port {dp} comment 'fw-web-forward'", shell=True)
        except: pass

def apply_whitelist_rules():
    # 还原白名单对应的「全端口放行」
    for ip in list(whitelist):
        ufw_allow_from_ip_any(ip)

# 初始化防火墙规则，确保面板端口对所有 IP 放行
ufw_allow_anywhere(state.get("panel_port", DEFAULT_PORT))
apply_forward_rules()
apply_whitelist_rules()

# ---- Auth helpers ----
def check_basic_header(request: Request):
    auth = request.headers.get("Authorization","")
    if not auth.startswith("Basic "): return False
    try:
        userpass=base64.b64decode(auth.split(" ",1)[1]).decode("utf-8","ignore")
        u,p=userpass.split(":",1)
        if u==USERNAME and p==PASSWORD:
            # 将当前来源 IP 纳入白名单（符合你的需求）
            ip=normalize_ip(request.client.host)
            try:
                ipaddress.ip_address(ip)
                if ip not in whitelist:
                    if len(whitelist) >= MAX_WL:
                        whitelist.popleft()
                    whitelist.append(ip); wl_save(list(whitelist))
                    ufw_allow_from_ip_any(ip)
            except: pass
            return True
    except: pass
    return False

def require_auth(request: Request):
    # 允许两种方式：1) 会话 2) BasicAuth 头
    if request.session.get("logged_in"): return True
    if check_basic_header(request): return True
    raise HTTPException(status_code=401, detail="unauthorized")

def current_user(request: Request):
    if request.session.get("logged_in"): return USERNAME
    auth=request.headers.get("Authorization","")
    if auth.startswith("Basic "):
        try:
            up=base64.b64decode(auth.split(" ",1)[1]).decode("utf-8","ignore")
            return up.split(":",1)[0]
        except: pass
    return "-"

def audit(action):
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            async def wrapper(*args, **kwargs):
                request=kwargs.get("request")
                if request is None:
                    for a in args:
                        if isinstance(a, Request):
                            request=a; break
                user=current_user(request) if request else "-"
                ip=normalize_ip(request.client.host) if request else "-"
                log_action(user, ip, action.format(**kwargs))
                return await func(*args, **kwargs)
            return wrapper
        else:
            def wrapper(*args, **kwargs):
                request=kwargs.get("request")
                if request is None:
                    for a in args:
                        if isinstance(a, Request):
                            request=a; break
                user=current_user(request) if request else "-"
                ip=normalize_ip(request.client.host) if request else "-"
                log_action(user, ip, action.format(**kwargs))
                return func(*args, **kwargs)
            return wrapper
    return decorator

# ---- Geo helpers ----
_geo_reader=None; geo_cache_local={}; geo_cache_online={}
def _ensure_mmdb():
    if not os.path.exists(GEO_MMDB):
        try:
            r=requests.get(GEO_MMDB_URL, timeout=10)
            if r.status_code==200 and len(r.content)>1024*1024:
                with open(GEO_MMDB,"wb") as f: f.write(r.content)
        except: pass
def _geo_reader_init():
    global _geo_reader
    if _geo_reader is None:
        _ensure_mmdb()
        if os.path.exists(GEO_MMDB):
            try:
                from geoip2.database import Reader
                _geo_reader=Reader(GEO_MMDB)
            except: _geo_reader=None
def flag_emoji(cc):
    if not cc or len(cc)!=2: return ""
    cc=cc.upper(); return chr(0x1F1E6+ord(cc[0])-65)+chr(0x1F1E6+ord(cc[1])-65)
def geo_local(ip):
    if ip in geo_cache_local: return geo_cache_local[ip]
    _geo_reader_init()
    try: ipaddress.ip_address(ip)
    except: geo_cache_local[ip]={"text":"未知","cc":""}; return geo_cache_local[ip]
    if _geo_reader:
        try:
            rec=_geo_reader.city(ip)
            country=(rec.country.names.get("zh-CN") or rec.country.name or "")
            cc=rec.country.iso_code or ""
            region=(rec.subdivisions.most_specific.names.get("zh-CN") or rec.subdivisions.most_specific.name or "")
            city=(rec.city.names.get("zh-CN") or rec.city.name or "")
            text=",".join([x for x in [country,region,city] if x]) or "未知"
            geo_cache_local[ip]={"text":text,"cc":cc}; return geo_cache_local[ip]
        except: pass
    geo_cache_local[ip]={"text":"未知","cc":""}; return geo_cache_local[ip]
def geo_online(ip):
    if ip in geo_cache_online: return geo_cache_online[ip]
    try:
        r=requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=3)
        data=r.json()
        if data.get("status")=="success":
            country=data.get("country","") or ""; cc=data.get("countryCode","") or ""
            region=data.get("regionName","") or ""; city=data.get("city","") or ""; isp=data.get("isp","") or ""
            text=",".join([x for x in [country,region,city] if x]); 
            if isp: text+=f" | {isp}"
            text=text or "未知"
            geo_cache_online[ip]={"text":text,"cc":cc}
        else:
            geo_cache_online[ip]={"text":"未知","cc":""}
    except:
        geo_cache_online[ip]={"text":"未知","cc":""}
    return geo_cache_online[ip]
def geo_both(ip):
    ip=normalize_ip(ip); l=geo_local(ip); o=geo_online(ip)
    return {"local":l["text"], "online":o["text"], "flag":flag_emoji(o["cc"] or l["cc"])}

# ---- Pages ----
def login_html():
    return f"""<!doctype html><html lang='zh-CN'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>登录 · UFW 控制台</title>
<style>
  body{margin:0;min-height:100vh;background:radial-gradient(1200px 800px at 70% -10%, #1b2550 0%, transparent 60%),linear-gradient(180deg,#0b1020,#0f1630);font:14px/1.6 system-ui;color:#e6edf6;display:flex;align-items:center;justify-content:center;}
  .card{width:360px;background:#111a33cc;border:1px solid #1f2a44;border-radius:16px;backdrop-filter:blur(8px);box-shadow:0 10px 30px rgba(0,0,0,.35);padding:22px}
  h2{margin:0 0 12px} .muted{color:#aab3c0}
  input{width:100%;background:#0e1833;border:1px solid #233258;color:#e6edf6;border-radius:12px;padding:10px 12px;outline:none;margin:6px 0 12px}
  input:focus{border-color:#7dd3fc;box-shadow:0 0 24px rgba(125,211,252,.35)}
  button{width:100%;background:linear-gradient(135deg,#1a2b55,#132446);border:1px solid #234;color:#e6f7ff;padding:10px 14px;border-radius:12px;cursor:pointer}
  button:hover{border-color:#7dd3fc;box-shadow:0 0 24px rgba(125,211,252,.35)}
  .tip{font-size:12px;margin-top:12px}
  code{background:#0b142b;border:1px dashed #24365f;border-radius:8px;padding:2px 6px}
</style>
</head><body>
  <div class="card">
    <h2>登录 · 防火墙控制台</h2>
    <form method="post" action="/login">
      <label>用户名</label>
      <input name="username" value="{USERNAME}" autocomplete="username">
      <label>密码</label>
      <input type="password" name="password" autocomplete="current-password">
      <button type="submit">登录</button>
    </form>
    <div class="tip muted">命令行（自动登录并加入白名单）：<br>
      <code>curl -u {USERNAME}:密码 http://主机:端口/api/ports</code>
    </div>
  </div>
</body></html>"""

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return login_html()

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = normalize_ip(request.client.host)
    if username==USERNAME and password==PASSWORD:
        request.session["logged_in"]=True
        log_action(username, ip, "login success")
        try:
            ipaddress.ip_address(ip)
            if ip not in whitelist:
                if len(whitelist) >= MAX_WL: whitelist.popleft()
                whitelist.append(ip); wl_save(list(whitelist)); ufw_allow_from_ip_any(ip)
        except: pass
        return RedirectResponse("/", 302)
    log_action(username, ip, "login failed")
    return HTMLResponse(login_html().replace("</form>","</form><div class='muted' style='color:#ffb4c1'>用户名或密码错误</div>"), status_code=401)

@app.get("/logout")
def logout(request: Request):
    ip=normalize_ip(request.client.host)
    log_action(current_user(request), ip, "logout")
    request.session.clear()
    return RedirectResponse("/login")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    try:
        require_auth(request)
    except HTTPException:
        return RedirectResponse("/login")
    html=open(APP_DIR+"/static/index.html","r",encoding="utf-8").read()
    html = html.replace("__PANEL_PORT__", str(state.get("panel_port", DEFAULT_PORT)))
    html = html.replace("__PANEL_USER__", USERNAME)
    html = html.replace("__LOG_MB__", str(round(state.get("log_max_bytes",5*1024*1024)/1024/1024)))
    return html

# ---- Panel get/set ----
@app.get("/api/panel/cred")
def api_panel_cred_get(request: Request):
    require_auth(request); return {"username": USERNAME, "panel_port": state.get("panel_port", DEFAULT_PORT)}

@app.post("/api/panel/set")
@audit("panel port set {port}")
def api_panel_set(request: Request, port: int = Form(...)):
    require_auth(request)
    port=int(port);
    if port<1 or port>65535: return JSONResponse({"error":"invalid port"}, status_code=400)
    state["panel_port"]=port; state_save(state)
    subprocess.run(f"ufw allow {port}/tcp comment 'fw-web-panel'", shell=True)  # 永久放行新端口
    threading.Thread(target=lambda: (time.sleep(1), os._exit(3))).start()
    return {"status":"ok","msg":"端口已保存，服务即将自动重启生效","panel_port":port}

@app.post("/api/panel/cred")
@audit("panel cred set user {username} port {port}")
def api_panel_cred_set(request: Request, username: str = Form(...), password: str = Form(...), port: int = Form(...)):
    require_auth(request)
    port=int(port)
    if port<1 or port>65535 or not username or not password:
        return JSONResponse({"error":"invalid params"}, status_code=400)
    state["panel_port"]=port
    state["username"]=username
    state["password"]=password
    state_save(state)
    global USERNAME, PASSWORD
    USERNAME=username; PASSWORD=password
    subprocess.run(f"ufw allow {port}/tcp comment 'fw-web-panel'", shell=True)
    threading.Thread(target=lambda: (time.sleep(1), os._exit(3))).start()
    return {"status":"ok","panel_port":port,"username":username}

# ---- Port forward APIs ----
@app.get("/api/forward/list")
def api_forward_list(request: Request):
    require_auth(request)
    return {"forwards": state.get("forwards", [])}

@app.post("/api/forward/add")
@audit("forward add {src_port}->{dst_ip}:{dst_port}")
def api_forward_add(request: Request, src_port: int = Form(...), dst_ip: str = Form(...), dst_port: int = Form(...)):
    require_auth(request)
    try:
        ipaddress.ip_address(dst_ip)
    except:
        return JSONResponse({"error":"invalid ip"}, status_code=400)
    src_port=int(src_port); dst_port=int(dst_port)
    if not (1<=src_port<=65535 and 1<=dst_port<=65535):
        return JSONResponse({"error":"invalid port"}, status_code=400)
    forwards=[f for f in state.get("forwards", []) if f.get("src_port")!=src_port]
    forwards.append({"src_port":src_port,"dst_ip":dst_ip,"dst_port":dst_port})
    state["forwards"]=forwards; state_save(state)
    apply_forward_rules()
    return {"status":"ok"}

@app.post("/api/forward/delete/{src_port}")
@audit("forward delete {src_port}")
def api_forward_delete(src_port: int, request: Request):
    require_auth(request)
    src_port=int(src_port)
    forwards=[f for f in state.get("forwards", []) if f.get("src_port")!=src_port]
    state["forwards"]=forwards; state_save(state)
    apply_forward_rules()
    return {"status":"ok"}

# ---- UFW APIs ----
@app.get("/api/ports")
def api_ports(request: Request):
    require_auth(request); return {"rules": run("ufw status numbered").splitlines()}

@app.post("/api/open/{port}")
@audit("open port {port}")
def api_open_port(port: int, request: Request):
    require_auth(request)
    for ip in list(whitelist): ufw_allow_from_ip_port(ip, port)
    panel = state.get("panel_port", DEFAULT_PORT)
    if port != panel:
        for line in reversed(run("ufw status numbered").splitlines()):
            if "]" in line and "ALLOW IN" in line and "From Anywhere" in line and f"{port}" in line:
                try: num=int(line.split("]")[0].strip("[ ")); ufw_delete_rule_number(num)
                except: pass
    return {"status": f"port {port} allowed for whitelist only"}

@app.get("/api/whitelist")
def api_wl(request: Request):
    require_auth(request)
    res=[]
    for ip in list(whitelist):
        g=geo_both(ip)
        res.append({"ip":ip,"local":g["local"],"online":g["online"],"flag":g["flag"]})
    return {"whitelist":res}

@app.post("/api/whitelist/{ip}")
@audit("whitelist add {ip}")
def api_wl_add(ip: str, request: Request):
    require_auth(request)
    ip=normalize_ip(ip)
    try: ipaddress.ip_address(ip)
    except: return {"status":"invalid ip"}
    if ip not in whitelist:
        if len(whitelist)>=MAX_WL: whitelist.popleft()
        whitelist.append(ip); wl_save(list(whitelist))
        ufw_allow_from_ip_any(ip)
    return {"status": f"{ip} added"}

@app.post("/api/whitelist/delete/{ip}")
@audit("whitelist delete {ip}")
def api_wl_del(ip: str, request: Request):
    require_auth(request)
    ip=normalize_ip(ip)
    try: whitelist.remove(ip)
    except: pass
    wl_save(list(whitelist))
    for line in reversed(run("ufw status numbered").splitlines()):
        if "]" in line and "ALLOW IN" in line and f"From {ip}" in line:
            try: num=int(line.split("]")[0].strip("[ ")); ufw_delete_rule_number(num)
            except: pass
    return {"status": f"{ip} removed"}

@app.post("/api/ufw/strictify")
@audit("strictify")
def api_strictify(request: Request):
    require_auth(request)
    panel = state.get("panel_port", DEFAULT_PORT)
    deleted=0
    for line in reversed(run("ufw status numbered").splitlines()):
        if "]" in line and "ALLOW IN" in line and "From Anywhere" in line:
            if f"{panel}" in line:  # 面板端口跳过
                continue
            try: num=int(line.split("]")[0].strip("[ ")); ufw_delete_rule_number(num); deleted+=1
            except: pass
    subprocess.run(f"ufw allow {panel}/tcp comment 'fw-web-panel'", shell=True)
    return {"status":"ok","deleted_anywhere":deleted,"panel_port":panel}

# ---- Export/Import/Logs ----
@app.get("/export/whitelist")
def export_wl(request: Request):
    if not request.session.get("logged_in") and not check_basic_header(request):
        return RedirectResponse("/login")
    tmp=tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt")
    for ip in list(whitelist):
        g=geo_both(ip); tmp.write(f"{ip} | {g['flag']} 本地:{g['local']} 在线:{g['online']}\n")
    tmp.close()
    return FileResponse(tmp.name, filename="whitelist.txt", media_type="text/plain")

@app.post("/import/whitelist")
async def import_wl(request: Request, file: UploadFile = File(...)):
    if not request.session.get("logged_in") and not check_basic_header(request):
        return RedirectResponse("/login")
    content=(await file.read()).decode(errors="ignore"); added=0
    for line in content.splitlines():
        ip=line.split("|")[0].strip()
        try:
            ipaddress.ip_address(ip)
            if ip not in whitelist:
                if len(whitelist)>=MAX_WL: whitelist.popleft()
                whitelist.append(ip); ufw_allow_from_ip_any(ip); added+=1
        except: pass
    wl_save(list(whitelist))
    return RedirectResponse("/", 302)

@app.get("/export/logs")
def export_logs(request: Request):
    require_auth(request)
    if not os.path.exists(LOG_FILE): return PlainTextResponse("暂无日志")
    return FileResponse(LOG_FILE, filename="firewall.log", media_type="text/plain")

@app.post("/api/loglimit/{mb}")
@audit("set log limit {mb}MB")
def set_log_limit(mb: int, request: Request):
    require_auth(request)
    state["log_max_bytes"]=max(1,int(mb))*1024*1024; state_save(state)
    rotate_log_if_needed(); return {"status":"ok","max_bytes":state["log_max_bytes"]}

# ---- Traffic & Connections ----
@app.get("/api/traffic")
def api_traffic(request: Request):
    require_auth(request)
    io=psutil.net_io_counters(); rx,tx=io.bytes_recv, io.bytes_sent
    now=time.time()
    last_ts=float(state.get("last_ts",0.0)); last_rx=int(state.get("last_rx",0)); last_tx=int(state.get("last_tx",0))
    rx_rate=tx_rate=0.0
    if last_ts>0:
        dt=max(0.001, now-last_ts); drx=max(0, rx-last_rx); dtx=max(0, tx-last_tx)
        rx_rate=drx/dt; tx_rate=dtx/dt; state["acc_rx"]+=drx; state["acc_tx"]+=dtx
    state["last_rx"],state["last_tx"],state["last_ts"]=rx,tx,now; state_save(state)
    ifs=[{"iface":iface,"rx":st.bytes_recv,"tx":st.bytes_sent} for iface,st in psutil.net_io_counters(pernic=True).items()]
    return {"acc_rx":state["acc_rx"],"acc_tx":state["acc_tx"],"rx_rate":rx_rate,"tx_rate":tx_rate,"ifaces":ifs,"ts":now}

@app.get("/api/connections")
def api_connections(request: Request):
    require_auth(request)
    out=[]
    for c in psutil.net_connections(kind='inet'):
        try:
            pid=c.pid or 0; proc=psutil.Process(pid).name() if pid else ""
        except: pid,proc=(c.pid or 0),""
        laddr=f"{normalize_ip(c.laddr.ip)}:{c.laddr.port}" if c.laddr else ""
        if c.raddr and c.raddr.ip:
            rip=normalize_ip(c.raddr.ip); raddr=f"{rip}:{c.raddr.port}"; g=geo_both(rip)
            out.append({"proc":proc,"pid":pid,"laddr":laddr,"raddr":raddr,"status":c.status,"local":g["local"],"online":g["online"],"flag":g["flag"],"geo":(g["online"] or g["local"])})
        else:
            out.append({"proc":proc,"pid":pid,"laddr":laddr,"raddr":"","status":c.status,"local":"","online":"","flag":"","geo":""})
    return {"connections":out}

# ---- Port search ----
@app.get("/api/portsearch")
def api_portsearch(request: Request, port: int):
    require_auth(request)
    res=[]
    for c in psutil.net_connections(kind='inet'):
        if (c.laddr and c.laddr.port==port) or (c.raddr and c.raddr.port==port):
            try:
                pid=c.pid or 0; p=psutil.Process(pid); name=p.name() if pid else ""; exe=p.exe() if pid else ""
            except: pid,name,exe=(c.pid or 0),"",""
            laddr=f"{normalize_ip(c.laddr.ip)}:{c.laddr.port}" if c.laddr else ""
            raddr=f"{normalize_ip(c.raddr.ip)}:{c.raddr.port}" if c.raddr else ""
            res.append({"pid":pid,"proc":name,"exe":exe,"laddr":laddr,"raddr":raddr,"status":c.status})
    return {"port":port,"results":res}

# ---- ICMP/TCP/UDP & Scan ----
def resolve_host(host):
    try: return socket.gethostbyname(host)
    except: return ""
def icmp_ping(host, count=3, timeout=1):
    ip = resolve_host(host) or host
    cmd = f"ping -n -c {count} -W {timeout} {shlex.quote(host)}"
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=max(timeout*count+2, 5))
        out = res.stdout + res.stderr
        ok = (res.returncode == 0)
        avg = None
        for line in out.splitlines():
            line=line.strip()
            if "min/avg/max" in line and "=" in line and "ms" in line:
                part=line.split("=")[-1].strip().split()[0]
                fields=part.split("/")
                if len(fields)>=2:
                    avg=float(fields[1])
        if avg is None:
            for line in out.splitlines():
                if "time=" in line and " ms" in line:
                    try: avg=float(line.split("time=")[-1].split()[0]); break
                    except: pass
        return {"host": host, "ip": ip, "ok": ok, "avg_ms": avg}
    except Exception as e:
        return {"host": host, "ip": ip, "ok": False, "error": str(e)}

async def tcp_probe(host, port, timeout=1.0):
    loop = asyncio.get_event_loop(); ip = resolve_host(host) or host; t0=loop.time()
    try:
        fut=asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        dt=(loop.time()-t0)*1000.0; writer.close(); 
        try: await writer.wait_closed()
        except: pass
        return {"host":host,"ip":ip,"port":port,"open":True,"latency_ms":dt}
    except Exception:
        dt=(loop.time()-t0)*1000.0; return {"host":host,"ip":ip,"port":port,"open":False,"latency_ms":dt}

async def udp_probe(host, port, timeout=1.0):
    loop=asyncio.get_event_loop(); ip=resolve_host(host) or host; t0=loop.time()
    try:
        transport, protocol = await asyncio.wait_for(loop.create_datagram_endpoint(lambda: asyncio.DatagramProtocol(), remote_addr=(host, port)), timeout=timeout)
        try:
            transport.sendto(b''); await asyncio.sleep(timeout)
        finally:
            transport.close()
        dt=(loop.time()-t0)*1000.0
        return {"host":host,"ip":ip,"port":port,"status":"no_response","latency_ms":dt}
    except Exception as e:
        dt=(loop.time()-t0)*1000.0
        return {"host":host,"ip":ip,"port":port,"status":"error","latency_ms":dt,"error":str(e)}

@app.post("/api/scan")
async def api_scan(request: Request):
    require_auth(request)
    body = await request.json()
    hosts = body.get("hosts") or []
    mode = (body.get("mode") or "icmp").lower()
    ports_raw = body.get("ports") or ""
    timeout = float(body.get("timeout") or 1.0)
    norm_hosts = [ (h or "").strip() for h in hosts if (h or "").strip() ][:64]
    if not norm_hosts: return {"error":"no hosts"}
    if mode == "icmp":
        results=[icmp_ping(h, count=3, timeout=int(timeout)) for h in norm_hosts]
        return {"mode":"icmp","results":results}
    ports=[]
    if isinstance(ports_raw,str):
        if ports_raw.strip().lower()=="common" or ports_raw.strip()=="":
            ports = COMMON_PORTS[:]
        else:
            for tok in ports_raw.replace("，",",").split(","):
                tok=tok.strip()
                if tok.isdigit():
                    p=int(tok)
                    if 1<=p<=65535: ports.append(p)
    elif isinstance(ports_raw,list):
        for p in ports_raw:
            try:
                p=int(p)
                if 1<=p<=65535: ports.append(p)
            except: pass
    ports=sorted(set(ports))[:256]
    tasks=[]
    if mode=="tcp":
        for h in norm_hosts:
            for p in ports: tasks.append(tcp_probe(h,p,timeout=timeout))
    elif mode=="udp":
        for h in norm_hosts:
            for p in ports: tasks.append(udp_probe(h,p,timeout=timeout))
    else:
        return {"error":"mode not supported"}
    results=[]
    if tasks:
        step=128
        for i in range(0,len(tasks),step):
            results += await asyncio.gather(*tasks[i:i+step])
    return {"mode":mode,"results":results}

# ---- Speedtest ----
@app.get("/api/speedtest/down")
def speedtest_down(request: Request, size_mb: int = 10):
    require_auth(request)
    size = max(1, min(200, int(size_mb))) * 1024 * 1024
    chunk = os.urandom(64*1024)
    def gen():
        sent=0
        while sent < size:
            n=min(len(chunk), size-sent)
            sent+=n; yield chunk[:n]
    return StreamingResponse(gen(), media_type="application/octet-stream")

@app.post("/api/speedtest/up")
async def speedtest_up(request: Request):
    require_auth(request)
    data = await request.body()
    return {"received": len(data)}

# ---- Client info & DoH ----
@app.get("/api/clientinfo")
def api_clientinfo(request: Request):
    require_auth(request)
    ip=normalize_ip(request.client.host)
    g=geo_both(ip)
    return {"ip":ip,"geo":g}

@app.get("/api/dohinfo")
def api_dohinfo(request: Request):
    require_auth(request)
    out = {}
    tests = {
        "google": "https://dns.google/resolve?name=example.com&type=A",
        "cloudflare": "https://cloudflare-dns.com/dns-query?name=example.com&type=A"
    }
    headers = {"accept":"application/dns-json"}
    for name,url in tests.items():
        t0=time.time()
        try:
            r=requests.get(url, headers=headers, timeout=3)
            dt=(time.time()-t0)*1000.0
            ok = r.status_code==200
            data = {}
            try: data = r.json()
            except: pass
            out[name] = {"ok":ok,"ms":round(dt,2),"resolver":name,"answer": data.get("Answer", [])[0] if isinstance(data.get("Answer"),list) and data.get("Answer") else None}
        except Exception as e:
            out[name] = {"ok":False,"error":str(e)}
    return {"doh":out}
