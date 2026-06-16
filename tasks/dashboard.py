"""Greenclaw web dashboard task.

Serves a read-only status page at http://localhost:PORT (default 7070).
Displays: system vitals, memory vault stats, CC call count, open GitHub
issues for the greenclaw repo, scheduler heartbeat, and active tasks.

Configuration (in .env):
  DASHBOARD_PORT   TCP port to listen on (default: 7070)
  DASHBOARD_HOST   Bind address (default: 0.0.0.0 — LAN-accessible)
  GITHUB_TOKEN     Optional — raises the GitHub API rate limit to 5000/hr

This file follows the tasks/*.py contract: it defines start(on_message)
and is loaded automatically by greenclaw.py at boot.
"""

NAME = "dashboard"

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Paths (mirrors greenclaw.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CC_LOG_FILE = os.path.expanduser("~/greenclaw/cc_calls.jsonl")
HEARTBEAT_FILE = os.path.expanduser("~/.local/share/greenclaw/heartbeat.jsonl")
MEMORY_DIR = os.path.expanduser("~/.claude/projects/-home-mrgreen/memory")
SCHEDULE_STATE_FILE = os.path.expanduser("~/.local/share/greenclaw/schedule.json")
STATIC_DIR = os.path.join(_HERE, "static")

MEMORY_SIZE_THRESHOLD = 50_000

GITHUB_REPO = os.environ.get("GITHUB_REPO", "mrgreen3/greenclaw")


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------

def _run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, timeout=5).strip()
    except Exception:
        return ""


def system_info():
    """Gather lightweight system stats without psutil."""
    # uptime
    uptime_raw = _run("cat /proc/uptime")
    try:
        secs = float(uptime_raw.split()[0])
        days = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        mins = int((secs % 3600) // 60)
        uptime = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"
    except Exception:
        uptime = "unknown"

    # cpu (1-second sample via /proc/stat)
    try:
        def _cpu_sample():
            with open("/proc/stat") as f:
                line = f.readline()
            vals = list(map(int, line.split()[1:]))
            idle = vals[3]
            total = sum(vals)
            return idle, total

        i1, t1 = _cpu_sample()
        time.sleep(0.5)
        i2, t2 = _cpu_sample()
        cpu_pct = round(100 * (1 - (i2 - i1) / max(t2 - t1, 1)))
    except Exception:
        cpu_pct = 0

    # memory
    meminfo = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                meminfo[k.strip()] = int(v.split()[0])  # kB
    except Exception:
        pass
    mem_total_kb = meminfo.get("MemTotal", 0)
    mem_avail_kb = meminfo.get("MemAvailable", 0)
    mem_used_kb = mem_total_kb - mem_avail_kb
    mem_pct = round(100 * mem_used_kb / max(mem_total_kb, 1))
    mem_used_gb = round(mem_used_kb / 1024 / 1024, 1)
    mem_total_gb = round(mem_total_kb / 1024 / 1024, 1)

    # disk
    disk_raw = _run("df -k / | tail -1")
    try:
        parts = disk_raw.split()
        disk_total_gb = round(int(parts[1]) / 1024 / 1024, 0)
        disk_used_gb = round(int(parts[2]) / 1024 / 1024, 0)
        disk_pct = round(int(parts[4].rstrip("%")))
    except Exception:
        disk_total_gb = disk_used_gb = 0
        disk_pct = 0

    # load average
    loadavg = _run("cat /proc/loadavg")
    load_parts = loadavg.split()[:3] if loadavg else ["?", "?", "?"]

    # hostname
    hostname = _run("hostname")

    return {
        "hostname": hostname or "greenclaw",
        "uptime": uptime,
        "cpu_pct": cpu_pct,
        "mem_pct": mem_pct,
        "mem_used_gb": mem_used_gb,
        "mem_total_gb": mem_total_gb,
        "disk_pct": disk_pct,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "load": " ".join(load_parts),
    }


def memory_stats():
    if not os.path.isdir(MEMORY_DIR):
        return {"files": [], "total": 0, "threshold": MEMORY_SIZE_THRESHOLD, "pct": 0}
    files = []
    total = 0
    for fn in sorted(os.listdir(MEMORY_DIR)):
        if fn.endswith(".md") and fn != "MEMORY.md":
            try:
                size = os.path.getsize(os.path.join(MEMORY_DIR, fn))
                files.append({"name": fn[:-3], "size": size})
                total += size
            except OSError:
                pass
    pct = round(100 * total / MEMORY_SIZE_THRESHOLD)
    return {"files": files, "total": total, "threshold": MEMORY_SIZE_THRESHOLD, "pct": pct}


def cc_call_stats():
    if not os.path.exists(CC_LOG_FILE):
        return {"today": 0, "week": 0}
    today_str = datetime.now().strftime("%Y-%m-%d")
    week_ago = time.time() - 7 * 86400
    today_count = week_count = 0
    try:
        with open(CC_LOG_FILE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    ts = r.get("ts", "")
                    if ts.startswith(today_str):
                        today_count += 1
                    try:
                        t = datetime.fromisoformat(ts).timestamp()
                        if t >= week_ago:
                            week_count += 1
                    except Exception:
                        pass
                except Exception:
                    pass
    except Exception:
        pass
    return {"today": today_count, "week": week_count}


def heartbeat_info():
    if not os.path.exists(HEARTBEAT_FILE):
        return {"last": "never", "version": "?"}
    try:
        with open(HEARTBEAT_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]
        if lines:
            last = json.loads(lines[-1])
            return {"last": last.get("ts", "?"), "version": last.get("version", "?")}
    except Exception:
        pass
    return {"last": "?", "version": "?"}


def github_issues():
    """Fetch open issues from the GitHub API. Returns list of dicts."""
    import urllib.request
    owner, repo = GITHUB_REPO.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=10"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "greenclaw-dashboard"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        issues = []
        for item in data:
            if "pull_request" in item:
                continue  # skip PRs
            labels = [lb["name"] for lb in item.get("labels", [])]
            issues.append({
                "number": item["number"],
                "title": item["title"],
                "labels": labels,
                "created_at": item.get("created_at", "")[:10],
                "url": item.get("html_url", ""),
            })
        return issues
    except Exception as e:
        return [{"number": 0, "title": f"(could not fetch: {e})", "labels": [], "created_at": "", "url": ""}]


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_CSS = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Courier New', Courier, monospace;
  background: #111;
  color: #ccc;
  font-size: 13px;
  min-height: 100vh;
}
a { color: #7BC950; text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar {
  background: #1a1a1a;
  border-bottom: 1px solid #2a2a2a;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo { color: #7BC950; font-size: 16px; font-weight: bold; letter-spacing: 0.1em; }
.badge {
  font-size: 10px; padding: 2px 8px;
  border-radius: 3px;
  background: #1c3a12;
  color: #7BC950;
  margin-left: 10px;
}
.ts { font-size: 11px; color: #555; }
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: #1e1e1e;
  border-top: 1px solid #222;
}
.panel {
  background: #131313;
  padding: 16px 20px;
}
.panel-full {
  background: #131313;
  padding: 16px 20px;
  border-top: 1px solid #1e1e1e;
}
.label {
  font-size: 10px;
  color: #444;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 10px;
}
.row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 5px;
  font-size: 12px;
}
.key { color: #666; }
.val { color: #bbb; }
.val.good { color: #7BC950; }
.val.warn { color: #E9A836; }
.val.bad  { color: #D05050; }
.bar-wrap {
  height: 3px;
  background: #222;
  border-radius: 2px;
  margin: 3px 0 10px;
  overflow: hidden;
}
.bar { height: 100%; border-radius: 2px; background: #7BC950; }
.bar.warn { background: #E9A836; }
.bar.bad  { background: #D05050; }
.issue {
  border-left: 2px solid #7BC950;
  padding: 7px 12px;
  margin-bottom: 8px;
  background: #1a1a1a;
  border-radius: 0 4px 4px 0;
}
.issue-title { color: #ccc; font-size: 12px; margin-bottom: 2px; }
.issue-meta  { color: #555; font-size: 10px; }
.label-pill {
  display: inline-block;
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #2a2a2a;
  color: #888;
  margin-right: 4px;
}
.mem-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid #1e1e1e;
  font-size: 12px;
}
.mem-row:last-of-type { border-bottom: none; }
.mem-key { color: #777; }
.mem-val { color: #7BC950; }
.footer {
  background: #111;
  border-top: 1px solid #1e1e1e;
  padding: 8px 20px;
  font-size: 10px;
  color: #444;
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.footer .hb { color: #7BC950; }
</style>
"""


def _pct_class(pct, warn=60, bad=85):
    if pct >= bad:
        return "bad"
    if pct >= warn:
        return "warn"
    return "good"


def render_html(sys, mem, cc, hb, issues):
    now = datetime.now().strftime("%d %b %Y — %H:%M %Z").strip()
    version = hb.get("version", "?")

    # --- system panel ---
    cpu_cls = _pct_class(sys["cpu_pct"])
    mem_cls = _pct_class(sys["mem_pct"])
    dsk_cls = _pct_class(sys["disk_pct"])

    sys_panel = f"""
<div class="panel">
  <div class="label">system</div>
  <div class="row"><span class="key">host</span><span class="val">{sys['hostname']}</span></div>
  <div class="row"><span class="key">uptime</span><span class="val good">{sys['uptime']}</span></div>
  <div class="row"><span class="key">cpu</span><span class="val {cpu_cls}">{sys['cpu_pct']}%</span></div>
  <div class="bar-wrap"><div class="bar {cpu_cls}" style="width:{sys['cpu_pct']}%"></div></div>
  <div class="row"><span class="key">memory</span><span class="val {mem_cls}">{sys['mem_pct']}% of {sys['mem_total_gb']} GB</span></div>
  <div class="bar-wrap"><div class="bar {mem_cls}" style="width:{sys['mem_pct']}%"></div></div>
  <div class="row"><span class="key">disk /</span><span class="val {dsk_cls}">{sys['disk_pct']}% of {int(sys['disk_total_gb'])} GB</span></div>
  <div class="bar-wrap"><div class="bar {dsk_cls}" style="width:{sys['disk_pct']}%"></div></div>
  <div class="row"><span class="key">load avg</span><span class="val">{sys['load']}</span></div>
</div>
"""

    # --- cc / memory panel ---
    mem_pct = mem.get("pct", 0)
    mem_cls2 = _pct_class(mem_pct, warn=70, bad=90)
    mem_files_html = ""
    for f in mem.get("files", []):
        mem_files_html += f'<div class="mem-row"><span class="mem-key">{f["name"]}</span><span class="mem-val">{f["size"]:,} b</span></div>\n'
    if not mem_files_html:
        mem_files_html = '<div class="mem-row"><span class="mem-key">(empty)</span></div>'

    cc_panel = f"""
<div class="panel">
  <div class="label">claude code calls</div>
  <div class="row"><span class="key">today</span><span class="val good">{cc['today']}</span></div>
  <div class="row"><span class="key">last 7 days</span><span class="val">{cc['week']}</span></div>

  <div class="label" style="margin-top:14px">memory vault</div>
  {mem_files_html}
  <div class="row" style="margin-top:8px; font-size:11px">
    <span class="key">{mem.get('total',0):,} b</span>
    <span class="val {mem_cls2}">{mem_pct}% of {MEMORY_SIZE_THRESHOLD//1000}KB threshold</span>
  </div>
  <div class="bar-wrap"><div class="bar {mem_cls2}" style="width:{min(mem_pct,100)}%"></div></div>
</div>
"""

    # --- issues panel ---
    issues_html = ""
    for issue in issues:
        labels_html = "".join(f'<span class="label-pill">{l}</span>' for l in issue["labels"])
        num = issue["number"]
        link = f'<a href="{issue["url"]}" target="_blank">#{num}</a>' if issue["url"] else f"#{num}"
        issues_html += f"""
<div class="issue">
  <div class="issue-title">{link} — {issue['title']}</div>
  <div class="issue-meta">{issue['created_at']} {labels_html}</div>
</div>
"""
    if not issues_html:
        issues_html = '<div class="issue"><div class="issue-title">no open issues</div></div>'

    issues_panel = f"""
<div class="panel-full">
  <div class="label">open github issues — {GITHUB_REPO}</div>
  {issues_html}
</div>
"""

    footer = f"""
<div class="footer">
  <span class="hb">&#x2665; last heartbeat: {hb.get('last','?')}</span>
  <span>v{version}</span>
  <span>auto-refresh every 30s</span>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>greenclaw dashboard</title>
{_CSS}
</head>
<body>
<div class="topbar">
  <div>
    <span class="logo">greenclaw</span>
    <span class="badge">&#x25CF; running</span>
  </div>
  <span class="ts">{now}</span>
</div>
<div class="grid">
  {sys_panel}
  {cc_panel}
</div>
{issues_panel}
{footer}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence access log

    def do_GET(self):
        if self.path not in ("/", "/dashboard"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        try:
            sys = system_info()
            mem = memory_stats()
            cc = cc_call_stats()
            hb = heartbeat_info()
            issues = github_issues()
            html = render_html(sys, mem, cc, hb, issues)
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"error: {e}".encode())


# ---------------------------------------------------------------------------
# Task entry point
# ---------------------------------------------------------------------------

def start(on_message):
    """Start the dashboard HTTP server in a daemon thread.
    on_message is accepted for API compatibility but not used.
    """
    port = int(os.environ.get("DASHBOARD_PORT", 7070))
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    server = HTTPServer((host, port), DashboardHandler)
    print(f"[dashboard] listening on http://{host}:{port}/dashboard")
    server.serve_forever()
