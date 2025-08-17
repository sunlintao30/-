import os, json, subprocess, sys
STATE_FILE = "/var/lib/firewall_web/state.json"
DEFAULT_PORT = 48080
def load_port():
    try:
        with open(STATE_FILE,"r") as f:
            s=json.load(f)
            p=int(s.get("panel_port", DEFAULT_PORT))
            if 1<=p<=65535: return p
    except: pass
    return DEFAULT_PORT
def ensure_panel_open(port):
    try: subprocess.run(["ufw","allow",f"{port}/tcp","comment","fw-web-panel"], check=False)
    except: pass
def main():
    port = load_port()
    ensure_panel_open(port)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "firewall_web:app", "--host", "0.0.0.0", "--port", str(port)])
if __name__=="__main__": main()
