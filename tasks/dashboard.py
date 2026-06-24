"""Greenclaw web dashboard task.

Serves a read-only status page at http://localhost:PORT (default 7070).
Displays: system vitals, memory vault stats, CC call count + recent prompts,
open GitHub issues, scheduled jobs, and recent notes.

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
import urllib.request
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Paths (mirrors greenclaw.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CC_LOG_FILE = os.path.expanduser("~/greenclaw/cc_calls.jsonl")
MEMORY_DIR = os.path.expanduser("~/.claude/projects/-home-mrgreen/memory")
SCHEDULE_STATE_FILE = os.path.expanduser("~/.local/share/greenclaw/schedule.json")
SCHEDULES_DIR = os.path.join(_HERE, "schedules")
TASKS_DIR = os.path.join(_HERE, "tasks")
NOTES_FILE = os.path.expanduser("~/notes.md")
STATIC_DIR = os.path.join(_HERE, "static")

MEMORY_SIZE_THRESHOLD = 50_000

GITHUB_REPO = os.environ.get("GITHUB_REPO", "mrgreen3/greenclaw")

# greenclaw.py version, read once at import for the footer.
try:
    _VERSION = "?"
    with open(os.path.join(_HERE, "greenclaw.py")) as _f:
        for _line in _f:
            if _line.startswith("__version__"):
                _VERSION = _line.split("=", 1)[1].strip().strip('"').strip("'")
                break
except Exception:
    _VERSION = "?"


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

    # cpu (short sample via /proc/stat)
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


def _clean_prompt(text):
    """Tidy a logged prompt preview for display. Strips a leading
    [Current date/time: ...] stamp and any memory/history block markers left by
    older greenclaw versions, then collapses whitespace."""
    text = text or ""
    if text.startswith("[Current date/time:"):
        end = text.find("]")
        if end != -1:
            text = text[end + 1:]
    for marker in ("--- long-term memory ---", "--- recent conversation ---"):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    text = " ".join(text.split())
    return text.strip() or "(memory/context only)"


def recent_cc_calls(limit=6):
    """Return the most recent CC invocations: time + cleaned prompt preview."""
    if not os.path.exists(CC_LOG_FILE):
        return []
    try:
        with open(CC_LOG_FILE) as f:
            lines = [l for l in f if l.strip()]
    except Exception:
        return []
    out = []
    for line in lines[-limit:][::-1]:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            # show HH:MM from the ISO timestamp
            t = ts[11:16] if len(ts) >= 16 else ts
            out.append({"time": t, "prompt": _clean_prompt(r.get("prompt", ""))})
        except Exception:
            pass
    return out


def _parse_front_matter(text):
    """Minimal front-matter parser (mirrors greenclaw.parse_front_matter)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return meta
        if ":" in lines[i]:
            k, v = lines[i].split(":", 1)
            meta[k.strip()] = v.strip()
    return {}


def _days_str(raw):
    raw = (raw or "daily").strip().lower()
    if raw in ("daily", "*", ""):
        return "daily"
    return raw


def scheduled_jobs():
    """Read schedules/*.md front matter + schedule.json to list timed jobs."""
    if not os.path.isdir(SCHEDULES_DIR):
        return []
    try:
        with open(SCHEDULE_STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    jobs = []
    for fn in sorted(os.listdir(SCHEDULES_DIR)):
        if not fn.endswith(".md"):
            continue
        try:
            with open(os.path.join(SCHEDULES_DIR, fn)) as f:
                meta = _parse_front_matter(f.read())
        except Exception:
            continue
        schedule = (meta.get("schedule") or "").strip()
        if not schedule:
            continue
        name = meta.get("name") or fn[:-3]
        last = state.get(name, "never")
        if last != "never" and len(last) >= 16:
            last = last[5:16].replace("T", " ")  # MM-DD HH:MM
        jobs.append({
            "name": name,
            "schedule": schedule,
            "days": _days_str(meta.get("days", "daily")),
            "skill": (meta.get("skill") or "").strip(),
            "last": last,
        })
    return jobs


def recent_notes(limit=6):
    """Return the last few lines of the notes file."""
    try:
        with open(NOTES_FILE) as f:
            lines = [l.rstrip() for l in f if l.strip()]
    except Exception:
        return []
    return lines[-limit:][::-1]


def active_tasks():
    """List task module names present in tasks/ (excludes _ prefixed)."""
    if not os.path.isdir(TASKS_DIR):
        return []
    names = []
    for fn in sorted(os.listdir(TASKS_DIR)):
        if fn.endswith(".py") and not fn.startswith("_"):
            names.append(fn[:-3])
    return names


def github_issues():
    """Fetch open issues from the GitHub API. Returns list of dicts."""
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
  font-size: 16px;
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
.logo { color: #7BC950; font-size: 20px; font-weight: bold; letter-spacing: 0.1em; }
.badge {
  font-size: 13px; padding: 2px 8px;
  border-radius: 3px;
  background: #1c3a12;
  color: #7BC950;
  margin-left: 10px;
}
.ts { font-size: 14px; color: #999; }
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
  font-size: 13px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 10px;
}
.row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 5px;
  font-size: 15px;
}
.key { color: #666; }
.val { color: #bbb; }
.val.good   { color: #7BC950; }
.val.warn   { color: #E9A836; }
.val.bad    { color: #D05050; }
.val.orange { color: #E8830A; }
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
.issue-title { color: #ccc; font-size: 15px; margin-bottom: 2px; }
.issue-meta  { color: #555; font-size: 13px; }
.label-pill {
  display: inline-block;
  font-size: 12px;
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
  font-size: 15px;
}
.mem-row:last-of-type { border-bottom: none; }
.mem-key { color: #777; }
.mem-val { color: #7BC950; }
.sched {
  padding: 6px 0;
  border-bottom: 1px solid #1e1e1e;
}
.sched:last-of-type { border-bottom: none; }
.sched-head { display: flex; justify-content: space-between; font-size: 15px; }
.sched-name { color: #ccc; }
.sched-name .arrow { color: #7BC950; }
.sched-time { color: #7BC950; }
.sched-meta { font-size: 13px; color: #555; margin-top: 1px; }
.logline {
  padding: 6px 0;
  border-bottom: 1px solid #1e1e1e;
  font-size: 14px;
  display: flex;
  gap: 12px;
}
.logline:last-of-type { border-bottom: none; }
.logline .t { color: #7BC950; flex-shrink: 0; }
.logline .p { color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note {
  padding: 5px 0;
  border-bottom: 1px solid #1e1e1e;
  font-size: 14px;
  color: #aaa;
}
.note:last-of-type { border-bottom: none; }
.empty { color: #555; font-size: 14px; padding: 6px 0; }
.footer {
  background: #111;
  border-top: 1px solid #1e1e1e;
  padding: 8px 20px;
  font-size: 13px;
  color: #888;
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.footer .tasks { color: #7BC950; }
</style>
"""


def _pct_class(pct, warn=60, bad=85):
    if pct >= bad:
        return "bad"
    if pct >= warn:
        return "warn"
    return "good"


def _esc(s):
    return escape(str(s))


def render_html(sys, mem, cc, issues, jobs, calls, notes, tasks):
    now = datetime.now().strftime("%d %b %Y — %H:%M %Z").strip()

    # --- system panel ---
    cpu_cls = _pct_class(sys["cpu_pct"])
    mem_cls = _pct_class(sys["mem_pct"])
    dsk_cls = _pct_class(sys["disk_pct"])

    sys_panel = f"""
<div class="panel">
  <div class="label">system</div>
  <div class="row"><span class="key">host</span><span class="val orange">{_esc(sys['hostname'])}</span></div>
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
        mem_files_html += f'<div class="mem-row"><span class="mem-key">{_esc(f["name"])}</span><span class="mem-val">{f["size"]:,} b</span></div>\n'
    if not mem_files_html:
        mem_files_html = '<div class="mem-row"><span class="mem-key">(empty)</span></div>'

    cc_panel = f"""
<div class="panel">
  <div class="label">claude code calls</div>
  <div class="row"><span class="key">today</span><span class="val good">{cc['today']}</span></div>
  <div class="row"><span class="key">last 7 days</span><span class="val">{cc['week']}</span></div>

  <div class="label" style="margin-top:14px">memory vault</div>
  {mem_files_html}
  <div class="row" style="margin-top:8px; font-size:14px">
    <span class="key">{mem.get('total',0):,} b</span>
    <span class="val {mem_cls2}">{mem_pct}% of {MEMORY_SIZE_THRESHOLD//1000}KB threshold</span>
  </div>
  <div class="bar-wrap"><div class="bar {mem_cls2}" style="width:{min(mem_pct,100)}%"></div></div>
</div>
"""

    # --- scheduler panel ---
    sched_html = ""
    for j in jobs:
        arrow = f' <span class="arrow">→ {_esc(j["skill"])}</span>' if j["skill"] else ""
        sched_html += f"""
<div class="sched">
  <div class="sched-head"><span class="sched-name">{_esc(j['name'])}{arrow}</span><span class="sched-time">{_esc(j['schedule'])}</span></div>
  <div class="sched-meta">{_esc(j['days'])} · last ran: {_esc(j['last'])}</div>
</div>"""
    if not sched_html:
        sched_html = '<div class="empty">no schedules loaded</div>'

    sched_panel = f"""
<div class="panel">
  <div class="label">scheduled jobs</div>
  {sched_html}
</div>
"""

    # --- recent notes panel ---
    notes_html = ""
    for n in notes:
        notes_html += f'<div class="note">{_esc(n)}</div>\n'
    if not notes_html:
        notes_html = '<div class="empty">no notes yet</div>'

    notes_panel = f"""
<div class="panel">
  <div class="label">recent notes</div>
  {notes_html}
</div>
"""

    # --- issues panel ---
    issues_html = ""
    for issue in issues:
        labels_html = "".join(f'<span class="label-pill">{_esc(l)}</span>' for l in issue["labels"])
        num = issue["number"]
        link = f'<a href="{_esc(issue["url"])}" target="_blank">#{num}</a>' if issue["url"] else f"#{num}"
        issues_html += f"""
<div class="issue">
  <div class="issue-title">{link} — {_esc(issue['title'])}</div>
  <div class="issue-meta">{_esc(issue['created_at'])} {labels_html}</div>
</div>
"""
    if not issues_html:
        issues_html = '<div class="issue"><div class="issue-title">no open issues</div></div>'

    issues_panel = f"""
<div class="panel">
  <div class="label">open github issues — {GITHUB_REPO}</div>
  {issues_html}
</div>
"""

    # --- recent CC calls panel ---
    calls_html = ""
    for c in calls:
        calls_html += f'<div class="logline"><span class="t">{_esc(c["time"])}</span><span class="p">{_esc(c["prompt"])}</span></div>\n'
    if not calls_html:
        calls_html = '<div class="empty">no calls logged yet</div>'

    calls_panel = f"""
<div class="panel">
  <div class="label">recent claude code prompts</div>
  {calls_html}
</div>
"""

    tasks_str = ", ".join(tasks) if tasks else "none"
    footer = f"""
<div class="footer">
  <span>tasks: <span class="tasks">{_esc(tasks_str)}</span></span>
  <span>v{_VERSION}</span>
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
  <div style="display:flex;align-items:center;gap:10px">
    <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" style="height:32px;width:32px;flex-shrink:0">
      <defs><linearGradient id="lobster-gradient" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#22c55e"/><stop offset="100%" stop-color="#15803d"/></linearGradient></defs>
      <path d="M60 10 C30 10 15 35 15 55 C15 75 30 95 45 100 L45 110 L55 110 L55 100 C55 100 60 102 65 100 L65 110 L75 110 L75 100 C90 95 105 75 105 55 C105 35 90 10 60 10Z" fill="url(#lobster-gradient)"/>
      <path d="M20 45 C5 40 0 50 5 60 C10 70 20 65 25 55 C28 48 25 45 20 45Z" fill="url(#lobster-gradient)"/>
      <path d="M100 45 C115 40 120 50 115 60 C110 70 100 65 95 55 C92 48 95 45 100 45Z" fill="url(#lobster-gradient)"/>
      <path d="M45 15 Q35 5 30 8" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
      <path d="M75 15 Q85 5 90 8" stroke="#22c55e" stroke-width="3" stroke-linecap="round"/>
      <circle cx="45" cy="35" r="6" fill="#050810"/><circle cx="75" cy="35" r="6" fill="#050810"/>
      <circle cx="46" cy="34" r="2.5" fill="#00e5cc"/><circle cx="76" cy="34" r="2.5" fill="#00e5cc"/>
    </svg>
    <span class="logo">greenclaw</span>
    <span class="badge">&#x25CF; running</span>
  </div>
  <span class="ts">{now}</span>
</div>
<div class="grid">
  {sys_panel}
  {cc_panel}
</div>
<div class="grid">
  {sched_panel}
  {notes_panel}
</div>
<div class="grid" style="border-top:1px solid #1e1e1e">
  {issues_panel}
  {calls_panel}
</div>
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
            html = render_html(
                system_info(),
                memory_stats(),
                cc_call_stats(),
                github_issues(),
                scheduled_jobs(),
                recent_cc_calls(),
                recent_notes(),
                active_tasks(),
            )
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
    Set DASHBOARD_ENABLED=0 in .env to skip starting the server.
    """
    if os.environ.get("DASHBOARD_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        print("[dashboard] disabled via DASHBOARD_ENABLED — not starting")
        return
    port = int(os.environ.get("DASHBOARD_PORT", 7070))
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    server = HTTPServer((host, port), DashboardHandler)
    print(f"[dashboard] listening on http://{host}:{port}/dashboard")
    server.serve_forever()
