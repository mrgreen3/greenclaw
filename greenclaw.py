#!/usr/bin/env python3
"""Minimal Claude router.

Two front ends, one core:
  python greenclaw.py              terminal stdin loop
  python greenclaw.py --tasks     run always-on tasks from tasks/ (Telegram etc.)

Per-message channels:
  <prompt>               -> Claude Code (default)
  cc <prompt>            -> Claude Code CLI (explicit)
  gc <prompt>            -> force local Ollama (Qwen2.5:3b, on-device)
  /<trigger> ...         -> a skill recipe from skills/
  /watch                 -> show scheduled jobs and when they last ran
  usage / calls          -> CC invocation count today
  /version               -> show greenclaw version
  /cheat                 -> built-in cheat sheet (prefixes, commands, skills)

Skills vs tasks vs schedules:
  skills/*.md     triggered recipes — what to do with a request
  schedules/*.md  timed jobs — when to run a skill automatically
  tasks/*.py      always-on connectors — how messages get in and out.
                  A task implements start(on_message) and calls
                  on_message(text, reply, chat_id) per incoming message, where
                  reply(text) sends the answer back on the same channel.

LAN / sole-user box. Secrets in .env (TELEGRAM_*).
Deps: pip install httpx
"""

__version__ = "0.4.0"

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

import httpx

# Local model channel: Ollama on the box — free, for the run_shell loop.
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5:3b-instruct")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
LOCAL_NUM_CTX = 8192
LOCAL_MAX_STEPS = 8

# Cap run_shell output so a chatty command can't blow the local context or Telegram.
SHELL_MAX_OUTPUT = 6000  # chars

CC_LOG_FILE = os.path.expanduser("~/greenclaw/cc_calls.jsonl")

# Skills: markdown recipes loaded at boot (front matter only), bodies loaded on demand.
_HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(_HERE, "skills")
SKILLS_ALLOW = os.path.join(_HERE, "skills.allow")

# Tasks: always-on connectors (Telegram, Signal, ...) loaded from tasks/*.py.
TASKS_DIR = os.path.join(_HERE, "tasks")

# Schedules: timed jobs loaded from schedules/*.md.
SCHEDULES_DIR = os.path.join(_HERE, "schedules")
SCHEDULE_STATE_FILE = os.path.expanduser("~/.local/share/greenclaw/schedule.json")

NOTES_FILE = os.path.expanduser("~/notes.md")

MEMORY_DIR = os.path.expanduser("~/.claude/projects/-home-mrgreen/memory")
MEMORY_SIZE_THRESHOLD = 50_000  # bytes — trigger CC compaction when exceeded
MEMORY_COMPACTION_COOLDOWN = 86_400  # seconds (24h) between auto-compactions
MEMORY_COMPACTION_STATE = os.path.expanduser("~/.local/share/greenclaw/memory_compaction.json")
HEARTBEAT_FILE = os.path.expanduser("~/.local/share/greenclaw/heartbeat.jsonl")

SKILLS = {}  # name -> {description, exposes, trigger, locked, source, path}; filled at boot

_memory_context = ""  # loaded at boot, refreshed after every save

# Per-chat rolling history for converse_local. Persisted to disk across restarts.
# Keys are chat_id strings; values are lists of {role, content} dicts.
_history: dict = {}
_history_updated: dict = {}  # key -> float; per-chat last-active timestamp
_history_lock = threading.Lock()
HISTORY_MAX_TURNS = 10  # pairs (user + assistant); older turns are dropped
HISTORY_FILE = os.path.expanduser("~/.local/share/greenclaw/history.json")
HISTORY_TTL_DAYS = 7  # discard entries older than this on load


def load_history():
    global _history, _history_updated
    if not os.path.exists(HISTORY_FILE):
        return
    try:
        with open(HISTORY_FILE) as f:
            data = json.load(f)
        cutoff = time.time() - HISTORY_TTL_DAYS * 86400
        with _history_lock:
            _history = {
                k: v["messages"]
                for k, v in data.items()
                if v.get("updated", 0) >= cutoff
            }
            _history_updated = {
                k: v.get("updated", 0)
                for k, v in data.items()
                if v.get("updated", 0) >= cutoff
            }
        print(f"[history] loaded {len(_history)} chat(s) from disk")
    except Exception as e:
        print(f"[history] failed to load: {e}")


def save_history(key):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with _history_lock:
        data = {
            k: {"messages": v, "updated": _history_updated.get(k, 0)}
            for k, v in _history.items()
        }
    tmp = HISTORY_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        print(f"[history] failed to save: {e}")


def _load_memory_from_disk():
    """Read all memory files from CC's memory dir and return a single context block."""
    if not os.path.isdir(MEMORY_DIR):
        return ""
    parts = []
    for fn in sorted(os.listdir(MEMORY_DIR)):
        if fn == "MEMORY.md" or not fn.endswith(".md"):
            continue
        try:
            with open(os.path.join(MEMORY_DIR, fn)) as f:
                content = f.read().strip()
            if content:
                parts.append(content)
        except Exception:
            continue
    return "\n\n".join(parts)


def reload_memory():
    global _memory_context
    _memory_context = _load_memory_from_disk()
    print(f"[memory] loaded {len(_memory_context)} chars from {MEMORY_DIR}")


def _memory_total_size():
    if not os.path.isdir(MEMORY_DIR):
        return 0
    total = 0
    for fn in os.listdir(MEMORY_DIR):
        if fn.endswith(".md"):
            try:
                total += os.path.getsize(os.path.join(MEMORY_DIR, fn))
            except OSError:
                pass
    return total


def report_memory_stats():
    if not os.path.isdir(MEMORY_DIR):
        return "No memory directory found."
    files = sorted(fn for fn in os.listdir(MEMORY_DIR) if fn.endswith(".md") and fn != "MEMORY.md")
    total = _memory_total_size()
    pct = int(total / MEMORY_SIZE_THRESHOLD * 100)
    lines = [f"Memory: {len(files)} entries, {total:,} bytes ({pct}% of {MEMORY_SIZE_THRESHOLD//1000}KB compaction threshold)"]
    for fn in files:
        try:
            size = os.path.getsize(os.path.join(MEMORY_DIR, fn))
            lines.append(f"  {fn[:-3]}: {size:,}b")
        except OSError:
            pass
    return "\n".join(lines)


def _check_memory_threshold():
    """If memory is over the size threshold and hasn't been compacted recently, ask CC to compact."""
    if _memory_total_size() < MEMORY_SIZE_THRESHOLD:
        return
    now = time.time()
    try:
        if os.path.exists(MEMORY_COMPACTION_STATE):
            with open(MEMORY_COMPACTION_STATE) as f:
                last = json.load(f).get("last_compacted", 0)
            if now - last < MEMORY_COMPACTION_COOLDOWN:
                return
    except Exception:
        pass
    print(f"[memory] size threshold exceeded — requesting CC compaction")
    ask_cc(
        "Memory has grown large. Review all files in ~/.claude/projects/-home-mrgreen/memory/, "
        "consolidate overlapping entries, summarise older content into fewer files, and remove "
        "trivial or outdated facts. Preserve user preferences, recurring patterns, and active "
        "project context. Update MEMORY.md accordingly."
    )
    os.makedirs(os.path.dirname(MEMORY_COMPACTION_STATE), exist_ok=True)
    try:
        with open(MEMORY_COMPACTION_STATE, "w") as f:
            json.dump({"last_compacted": now}, f)
    except Exception as e:
        print(f"[memory] could not save compaction state: {e}")
    reload_memory()


def log_heartbeat():
    os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
    try:
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "version": __version__}
        with open(HEARTBEAT_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[heartbeat] {e}")


def _build_system():
    """Build the Qwen system prompt from real runtime facts gathered once at startup."""
    try:
        raw = subprocess.check_output(
            "grep PRETTY_NAME /etc/os-release", shell=True, text=True
        ).strip()
        os_name = raw.split("=", 1)[-1].strip('"')
    except Exception:
        os_name = "Linux"
    try:
        probe = subprocess.check_output(
            "which pacman yay systemctl journalctl git python ollama claude 2>/dev/null",
            shell=True, text=True,
        ).strip()
        tools = ", ".join(os.path.basename(t) for t in probe.splitlines() if t)
    except Exception:
        tools = "standard Linux tools"
    return (
        f"You are the first responder on the user's home server ({os_name}). "
        "You are a small local model: handle simple things yourself and be honest about your limits. "
        "Use run_shell to inspect the box or run commands. "
        "Delegate to Claude Code via delegate_to_cc WHENEVER a request needs reach you "
        "don't have — email/Gmail, the web, GitHub, calendar, APIs, or any multi-step or "
        "complex task. In particular, if the user asks about email, their inbox, messages, or "
        "whether someone has written, replied or been in touch, call delegate_to_cc. "
        "When you delegate, pass a complete, specific instruction that includes the user's "
        "original request. Never invent things you can't actually access — delegate instead. "
        "Be concise — lead with the answer. Confirm before anything destructive. "
        f"Confirmed tools on this machine: {tools}. "
        "Do not assume a tool is missing — verify with run_shell first. "
        "Never refuse a task without attempting it. If a command fails, report the actual error. "
        "The user is the sole owner of this machine — no need to ask for sudo confirmation. "
        "For common sysadmin phrases, act immediately without asking for clarification. Examples:\n"
        "  'update system' or 'update' -> run: sudo pacman -Syu --noconfirm\n"
        "  'disk space' or 'storage' -> run: df -h\n"
        "  'memory' or 'ram' -> run: free -h\n"
        "  'what's running' or 'processes' -> run: ps aux or systemctl list-units --state=running\n"
        "  'uptime' -> run: uptime\n"
        "  'logs' -> run: journalctl -n 50 --no-pager\n"
        "  'reboot' or 'restart' -> run: sudo reboot (confirm first)\n"
        "If a request is ambiguous but has an obvious sysadmin interpretation, use it."
    )


SYSTEM = _build_system()

TOOLS = [
    {
        "name": "run_shell",
        "description": (
            "Run a shell command on the server and return stdout, stderr, and exit "
            "code. Use for inspecting the system, reading files, and running tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."}
            },
            "required": ["command"],
        },
    },
    {
        "name": "add_note",
        "description": (
            "Append a timestamped note to the user's notes file. Use this for any "
            "'remember', 'note', 'jot' request — never shell out to echo for this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The note text to append verbatim."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_notes",
        "description": "Return the most recent saved notes from the notes file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max number of recent lines to return (default 40).", "default": 40}
            },
        },
    },
    {
        "name": "save_memory",
        "description": (
            "Save something to long-term memory so it persists across sessions. "
            "Use when the user says 'remember', or when you learn something important "
            "about the user, their preferences, or their system that should persist."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "What to remember. Be specific and include context."}
            },
            "required": ["fact"],
        },
    },
]


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _truncate(text, limit=SHELL_MAX_OUTPUT):
    """Keep head and tail when output is too long; the exit line lives in the tail."""
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - limit
    return f"{text[:half]}\n... [truncated {omitted} chars] ...\n{text[-half:]}"


def run_shell(command):
    try:
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        out = p.stdout
        if p.stderr:
            out += "\n[stderr]\n" + p.stderr
        out += f"\n[exit {p.returncode}]"
        return _truncate(out.strip())
    except subprocess.TimeoutExpired:
        return "[error] command timed out (60s)"
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"


def add_note(text):
    text = (text or "").strip()
    if not text:
        return "[error] empty note"
    line = f"- [{datetime.now().strftime('%Y-%m-%d %H:%M')}] {text}\n"
    try:
        with open(NOTES_FILE, "a") as f:
            f.write(line)
        return f"noted: {text}"
    except Exception as e:  # noqa: BLE001
        return f"[error] could not write note: {e}"


def list_notes(limit=40):
    try:
        with open(NOTES_FILE) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return "(no notes yet)"
    except Exception as e:  # noqa: BLE001
        return f"[error] could not read notes: {e}"
    if not lines:
        return "(no notes yet)"
    try:
        n = max(1, int(limit))
    except (TypeError, ValueError):
        n = 40
    return "".join(lines[-n:]).rstrip()


def save_memory(fact):
    """Write a memory note to the greenbrain vault directly."""
    try:
        from skills.vault import write_note
        # Try to split "topic: content" if the fact contains a colon early on
        if ":" in fact[:40]:
            topic, content = fact.split(":", 1)
        else:
            topic, content = "notes", fact
        return write_note(topic.strip(), content.strip())
    except Exception as e:  # noqa: BLE001
        return f"[memory] {e}"


def get_daily_cc_calls():
    if not os.path.exists(CC_LOG_FILE):
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    with open(CC_LOG_FILE) as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get("ts", "").startswith(today):
                    count += 1
            except Exception:  # noqa: BLE001
                continue
    return count


def log_cc_call(prompt_preview):
    try:
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "prompt": prompt_preview[:120],
        }
        with open(CC_LOG_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[cc log error] {e}")


def report_usage():
    return f"Claude Code calls today: {get_daily_cc_calls()}"


def report_version():
    return f"greenclaw {__version__}"


STATIC_DIR = os.path.join(_HERE, "static")
CHEAT_FILE = os.path.join(STATIC_DIR, "cheat.md")


def report_cheat():
    """Built-in cheat sheet — no LLM. Static text from cheat.md with {skills}
    placeholder substituted from the live SKILLS dict."""
    try:
        with open(CHEAT_FILE) as f:
            template = f.read()
    except Exception as e:  # noqa: BLE001
        return f"[error] could not read cheat.md: {e}"
    if SKILLS:
        width = max(len(s["trigger"] or s["name"]) for s in SKILLS.values())
        rows = []
        for s in sorted(SKILLS.values(), key=lambda x: x["trigger"] or x["name"]):
            key = s["trigger"] or f"({s['name']})"
            rows.append(f"  {key:<{width}}  {s['description']}")
        skills_block = "\n".join(rows)
    else:
        skills_block = "  (none loaded)"
    return template.replace("{skills}", skills_block).rstrip()


CC_BIN = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def ask_cc(prompt, chat_id=None):
    """Hand the whole job to Claude Code headless, full autonomy."""
    if not os.path.exists(CC_BIN):
        return "[error] claude CLI not found"

    original_prompt = prompt
    now = datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    mem_block = f"\n\n--- long-term memory ---\n{_memory_context}" if _memory_context else ""

    hist_block = ""
    if chat_id is not None:
        with _history_lock:
            history = list(_history.get(str(chat_id), []))
        if history:
            lines = []
            for msg in history:
                role = "Kev" if msg["role"] == "user" else "GreenClaw"
                lines.append(f"{role}: {msg['content']}")
            hist_block = "\n\n--- recent conversation ---\n" + "\n".join(lines)

    prompt = f"[Current date/time: {now} GMT+1]{mem_block}{hist_block}\n\n{prompt}"
    log_cc_call(original_prompt)  # log the user's actual request, not the augmented prompt
    print("  [-> Claude Code]")
    try:
        cc_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        p = subprocess.run(
            [CC_BIN, "-p", prompt, "--model", "claude-haiku-4-5-20251001", "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=900, env=cc_env,
        )
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        if err:
            out += ("\n[stderr] " + err) if out else ("[stderr] " + err)
        out = out or "(no output)"
        if chat_id is not None:
            key = str(chat_id)
            with _history_lock:
                existing = _history.get(key, [])
                merged = existing + [
                    {"role": "user", "content": original_prompt},
                    {"role": "assistant", "content": out},
                ]
                _history[key] = merged[-(HISTORY_MAX_TURNS * 2):]
                _history_updated[key] = time.time()
            save_history(key)
        return out
    except subprocess.TimeoutExpired:
        return "[error] Claude Code timed out (15m)"
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"


def dispatch_tool(name, inp):
    if name == "run_shell":
        return run_shell(inp.get("command", ""))
    if name == "add_note":
        return add_note(inp.get("text", ""))
    if name == "list_notes":
        return list_notes(inp.get("limit", 40))
    if name == "delegate_to_cc":
        return ask_cc(inp.get("query", ""))
    if name == "save_memory":
        return save_memory(inp.get("fact", ""))
    return f"[error] unknown tool {name}"


def _ollama_tools():
    tools = [
        {"type": "function", "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }}
        for t in TOOLS
    ]
    tools.append({"type": "function", "function": {
        "name": "delegate_to_cc",
        "description": (
            "Delegate to Claude Code when you cannot handle a task yourself — "
            "e.g. checking email/Gmail, searching the web, or anything requiring "
            "external access you don't have. Returns Claude Code's reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The task or question to send to Claude Code."}},
            "required": ["query"],
        },
    }})
    return tools


def converse_local(text, system_extra=None, chat_id=None):
    """Route to local Ollama — free, on-device, no cloud.

    system_extra: optional skill body, appended to SYSTEM for this run only.
    chat_id: if provided, rolling history is loaded before the call and saved
             after. None (terminal mode) means no history accumulates.
    """
    mem_block = f"\n\n--- long-term memory ---\n{_memory_context}" if _memory_context else ""
    system = SYSTEM + mem_block
    if system_extra:
        system = f"{system}\n\n--- skill ---\n{system_extra}"
    with _history_lock:
        history = list(_history.get(str(chat_id), [])) if chat_id is not None else []
    msgs = (
        [{"role": "system", "content": system}]
        + history
        + [{"role": "user", "content": text}]
    )
    parts = []
    for _ in range(LOCAL_MAX_STEPS):
        try:
            r = httpx.post(OLLAMA_URL, json={
                "model": LOCAL_MODEL,
                "messages": msgs,
                "tools": _ollama_tools(),
                "stream": False,
                "options": {"num_ctx": LOCAL_NUM_CTX, "temperature": 0},
            }, timeout=300)
            m = r.json().get("message", {})
        except Exception as e:  # noqa: BLE001
            return f"[local error] {e}"
        msgs.append(m)
        if (m.get("content") or "").strip():
            parts.append(m["content"])
        calls = m.get("tool_calls")
        if not calls:
            break
        for tc in calls:
            fn = tc.get("function", {}).get("name", "")
            args = tc.get("function", {}).get("arguments") or {}
            preview = args.get('command') or args.get('query') or args.get('text') or ''
            print(f"  [g:{fn}] {preview[:120]}")
            msgs.append({"role": "tool", "content": dispatch_tool(fn, args), "name": fn})
    reply = "\n".join(parts).strip() or "(no reply)"
    # Save history: append this user/assistant pair and trim to the rolling window.
    if chat_id is not None:
        key = str(chat_id)
        with _history_lock:
            existing = _history.get(key, [])
            merged = existing + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply},
            ]
            _history[key] = merged[-(HISTORY_MAX_TURNS * 2):]
            _history_updated[key] = time.time()
        save_history(key)
    return reply


def parse_front_matter(text):
    """Split a skill file into (metadata dict, body). Front matter is a --- fenced
    block of trivial key: value lines at the top. Returns ({}, text) if absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body = "\n".join(lines[i + 1:]).strip()
            return meta, body
        if ":" in lines[i]:
            k, v = lines[i].split(":", 1)
            meta[k.strip()] = v.strip()
    return {}, text  # unterminated front matter -> treat as no metadata


def load_skills():
    """Index skills/*.md at boot — front matter only, never the body. Applies the
    skills.allow lock to locked skills and logs what loaded / was blocked."""
    SKILLS.clear()
    if not os.path.isdir(SKILLS_DIR):
        print("[skills] no skills/ directory — none loaded")
        return
    allow = set()
    if os.path.exists(SKILLS_ALLOW):
        with open(SKILLS_ALLOW) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    allow.add(line)
    loaded, blocked = [], []
    triggers_seen = {}  # trigger -> first skill name that claimed it
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(SKILLS_DIR, fn)
        with open(path) as f:
            head = f.read()  # body is discarded here; loaded on demand by run_skill
        meta, _ = parse_front_matter(head)
        name = meta.get("name") or fn[:-3]
        locked = meta.get("locked", "false").lower() == "true"
        if locked and name not in allow:
            blocked.append(name)
            continue
        trigger = meta.get("trigger", "")
        if trigger and trigger in triggers_seen:
            print(f"[skills] WARNING: {name} declares trigger {trigger!r} already used by {triggers_seen[trigger]} — ignoring trigger on {name}")
            trigger = ""
        elif trigger:
            triggers_seen[trigger] = name
        SKILLS[name] = {
            "name": name,
            "description": meta.get("description", ""),
            "exposes": meta.get("exposes", "cc").lower(),
            "trigger": trigger,
            "locked": locked,
            "source": meta.get("source", "unknown"),
            "path": path,
        }
        loaded.append(f"{name}({SKILLS[name]['source']})")
        if not trigger:
            print(f"[skills] {name}: no trigger — not reachable until model-selection (v2)")
    if loaded:
        print(f"[skills] loaded {len(loaded)}: {', '.join(loaded)}")
    if blocked:
        print(f"[skills] blocked {len(blocked)} (locked, not in skills.allow): {', '.join(blocked)}")

    # Load Qwen-native Python skills from skills/*.py
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(SKILLS_DIR, fn)
        try:
            spec = importlib.util.spec_from_file_location(f"greenclaw_skills.{fn[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001
            print(f"[skills] {fn}: failed to load — {e}")
            continue
        if not callable(getattr(mod, "run", None)):
            print(f"[skills] {fn}: no run() — skipped")
            continue
        name = getattr(mod, "NAME", fn[:-3])
        trigger = getattr(mod, "TRIGGER", "")
        description = getattr(mod, "DESCRIPTION", "")
        if trigger and trigger in triggers_seen:
            print(f"[skills] WARNING: {name} trigger {trigger!r} already claimed by {triggers_seen[trigger]} — ignoring trigger on {name}")
            trigger = ""
        elif trigger:
            triggers_seen[trigger] = name
        SKILLS[name] = {
            "name": name,
            "description": description,
            "exposes": "qwen",
            "trigger": trigger,
            "locked": False,
            "source": "qwen",
            "path": path,
            "module": mod,
        }
        loaded.append(f"{name}(qwen)")
        if not trigger:
            print(f"[skills] {name}: no trigger — not reachable")


# ---------------------------------------------------------------------------
# SCHEDULER — schedules/*.md define timed jobs; this section owns the watch.
# ---------------------------------------------------------------------------

def load_schedules():
    """Parse schedules/*.md — front matter only.

    Front matter fields:
        name      unique id (defaults to filename stem)
        schedule  HH:MM  (24-hour)
        days      mon,tue,wed,thu,fri,sat,sun  or  mon-fri  or  daily (default)
        skill     skill name to invoke (must exist in SKILLS)
        note      optional extra instruction appended to the skill body
    """
    if not os.path.isdir(SCHEDULES_DIR):
        return []
    scheds = []
    for fn in sorted(os.listdir(SCHEDULES_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(SCHEDULES_DIR, fn)
        with open(path) as f:
            text = f.read()
        meta, body = parse_front_matter(text)
        name = meta.get("name") or fn[:-3]
        schedule = meta.get("schedule", "").strip()
        if not schedule:
            print(f"[scheduler] {fn}: no schedule field — skipped")
            continue
        try:
            hour, minute = [int(x) for x in schedule.split(":")]
        except ValueError:
            print(f"[scheduler] {fn}: bad schedule {schedule!r} — skipped")
            continue
        days_raw = meta.get("days", "daily").strip().lower()
        days = _parse_days(days_raw)
        skill_name = meta.get("skill", "").strip()
        note = meta.get("note", "").strip() or body.strip()
        scheds.append({
            "name": name,
            "hour": hour,
            "minute": minute,
            "days": days,
            "skill": skill_name,
            "note": note,
            "path": path,
        })
        print(f"[scheduler] loaded: {name} @ {hour:02d}:{minute:02d} days={days_raw} skill={skill_name or '—'}")
    return scheds


def _parse_days(raw):
    """Return a set of weekday ints (0=Mon … 6=Sun) from a days string."""
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if raw in ("daily", "*", ""):
        return set(range(7))
    # range like mon-fri
    if "-" in raw and "," not in raw:
        parts = raw.split("-")
        if len(parts) == 2 and parts[0] in names and parts[1] in names:
            start, end = names.index(parts[0]), names.index(parts[1])
            return set(range(start, end + 1))
    # comma list like mon,wed,fri
    result = set()
    for token in raw.split(","):
        token = token.strip()
        if token in names:
            result.add(names.index(token))
    return result or set(range(7))


def _load_schedule_state():
    """Return dict of name -> last_fired ISO string."""
    if not os.path.exists(SCHEDULE_STATE_FILE):
        return {}
    try:
        with open(SCHEDULE_STATE_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"[scheduler] could not load state: {e}")
        return {}


def _save_schedule_state(state):
    os.makedirs(os.path.dirname(SCHEDULE_STATE_FILE), exist_ok=True)
    tmp = SCHEDULE_STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, SCHEDULE_STATE_FILE)
    except Exception as e:
        print(f"[scheduler] could not save state: {e}")


def _schedule_due(sched, now, state):
    """True if this schedule should fire right now."""
    if now.weekday() not in sched["days"]:
        return False
    if now.hour != sched["hour"] or now.minute != sched["minute"]:
        return False
    last = state.get(sched["name"])
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            # Already fired within the last 30 minutes — don't repeat.
            if (now - last_dt).total_seconds() < 1800:
                return False
        except ValueError:
            pass
    return True


def report_schedule():
    """/watch command — show what's scheduled and when each last ran."""
    scheds = load_schedules()
    if not scheds:
        return "No schedules loaded."
    state = _load_schedule_state()
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    lines = ["🕐 Greenclaw's watch\n"]
    for s in scheds:
        days = s.get("days", set(range(7)))
        if days == set(range(7)):
            day_str = "daily"
        elif days == set(range(5)):
            day_str = "mon-fri"
        else:
            day_str = ",".join(day_names[d] for d in sorted(days))
        last = state.get(s["name"], "never")
        skill_str = f" → {s['skill']}" if s["skill"] else ""
        lines.append(
            f"  {s['name']}{skill_str}\n"
            f"    {s['hour']:02d}:{s['minute']:02d} {day_str}  |  last ran: {last}"
        )
    return "\n".join(lines)


def _run_schedule(sched):
    """Invoke a schedule: run its named skill (with optional note), or route the note directly."""
    skill_name = sched.get("skill")
    note = sched.get("note", "")
    if skill_name:
        skill = SKILLS.get(skill_name)
        if not skill:
            return f"[scheduler] skill '{skill_name}' not found in loaded skills"
        if note:
            with open(skill["path"]) as f:
                original = f.read()
            _, body = parse_front_matter(original)
            augmented_body = f"{body}\n\nAdditional instruction: {note}"
            return converse_local("Run this skill now.", system_extra=augmented_body)
        return run_skill(skill, "")
    elif note:
        return route(note)
    return "[scheduler] nothing to run — no skill or note in schedule"


def start_scheduler(reply_fn):
    """Start the scheduler thread. reply_fn(text) sends output to the user."""
    scheds = load_schedules()
    if not scheds:
        print("[scheduler] no schedules found — not started")
        return

    def loop():
        state = _load_schedule_state()
        while True:
            now = datetime.now().replace(second=0, microsecond=0)
            for sched in scheds:
                if not _schedule_due(sched, now, state):
                    continue
                print(f"[scheduler] firing: {sched['name']}")
                try:
                    result = _run_schedule(sched)
                except Exception as e:  # noqa: BLE001
                    result = f"[scheduler error] {sched['name']}: {e}"
                state[sched["name"]] = now.isoformat()
                _save_schedule_state(state)
                reply_fn(f"⏰ {sched['name']}\n\n{result}")
            # Sleep until the next whole minute.
            sleep_secs = 60 - datetime.now().second
            time.sleep(max(sleep_secs, 1))

    t = threading.Thread(target=loop, daemon=True, name="scheduler")
    t.start()
    print("[scheduler] started")


# ---------------------------------------------------------------------------
# END SCHEDULER
# ---------------------------------------------------------------------------


def match_skill_trigger(text):
    """Return the skill whose trigger is the first whitespace token of text, else None."""
    first = text.split(None, 1)[0] if text.split() else ""
    for skill in SKILLS.values():
        if skill["trigger"] and skill["trigger"].lower() == first:
            return skill
    return None


def run_skill(skill, text):
    """Dispatch to a Qwen Python skill (direct) or a CC markdown skill (via ask_cc)."""
    arg = text[len(skill["trigger"]):].strip() if skill["trigger"] else text
    if skill.get("exposes") == "qwen":
        try:
            return skill["module"].run(arg)
        except Exception as e:  # noqa: BLE001
            return f"[skill error] {skill['name']}: {e}"
    try:
        with open(skill["path"]) as f:
            body = parse_front_matter(f.read())[1]
    except Exception as e:  # noqa: BLE001
        return f"[skill error] could not read {skill['path']}: {e}"
    prompt = f"{body}\n\n--- user request ---\n{arg}" if arg else body
    return ask_cc(prompt)


def route(text, chat_id=None):
    """Shared routing logic for every front end (terminal and all tasks).

    Qwen-first: with no prefix, the local model handles it and delegates to Claude
    Code itself when it needs more reach. `cc ` forces Claude Code; `gc ` forces local.
    chat_id: passed through to converse_local for per-chat history tracking.
    """
    text_lower = text.lower()
    if text_lower in ("usage", "calls"):
        return report_usage()
    if text_lower in ("/version", "version"):
        return report_version()
    if text_lower in ("/cheat", "cheat"):
        return report_cheat()
    if text_lower in ("/watch", "watch"):
        return report_schedule()
    if text_lower in ("/memory", "memory stats"):
        return report_memory_stats()
    if text_lower == "/regreen":
        threading.Timer(1.5, lambda: subprocess.run(
            ["systemctl", "--user", "restart", "greenclaw.service"]
        )).start()
        return "restarting…"
    skill = match_skill_trigger(text_lower)
    if skill:
        return run_skill(skill, text)
    if text_lower.startswith("remember "):
        return save_memory(text[9:].strip())
    if text_lower.startswith("cc "):
        return ask_cc(text[3:].strip())
    if text_lower.startswith("gc "):
        return converse_local(text[3:].strip(), chat_id=chat_id)
    return ask_cc(text, chat_id=chat_id)  # default: Claude Code


def load_tasks():
    """Import every tasks/*.py that defines start(on_message). Tasks own their own
    config (read from env) and decide for themselves whether to run."""
    tasks = []
    if not os.path.isdir(TASKS_DIR):
        print("[tasks] no tasks/ directory — none loaded")
        return tasks
    for fn in sorted(os.listdir(TASKS_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(TASKS_DIR, fn)
        try:
            spec = importlib.util.spec_from_file_location(f"greenclaw_tasks.{fn[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001
            print(f"[tasks] {fn}: failed to load — {e}")
            continue
        if not callable(getattr(mod, "start", None)):
            print(f"[tasks] {fn}: no start(on_message) — skipped")
            continue
        tasks.append(mod)
    return tasks


def start_tasks():
    """Start all tasks in background threads. Returns list of (name, thread)."""
    tasks = load_tasks()
    if not tasks:
        return []

    def on_message(text, reply, chat_id=None):
        try:
            reply(route(text, chat_id=chat_id))
        except Exception as e:  # noqa: BLE001
            print(f"[tasks] on_message error: {e}")

    # Wire the scheduler to Telegram so timed jobs push to the right chat.
    _tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    _tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if _tg_token and _tg_chat:
        def _sched_reply(text):
            try:
                for i in range(0, len(text), 4000):
                    httpx.post(
                        f"https://api.telegram.org/bot{_tg_token}/sendMessage",
                        json={"chat_id": _tg_chat, "text": text[i:i + 4000]},
                        timeout=30,
                    )
            except Exception as e:  # noqa: BLE001
                print(f"[scheduler] telegram send error: {e}")
        start_scheduler(_sched_reply)
    else:
        print("[scheduler] TELEGRAM_BOT_TOKEN/CHAT_ID not set — scheduler outputs to stdout only")
        start_scheduler(print)

    threads = []
    for mod in tasks:
        name = getattr(mod, "NAME", mod.__name__)
        print(f"[tasks] starting {name}")
        t = threading.Thread(target=mod.start, args=(on_message,), daemon=True, name=name)
        t.start()
        threads.append((name, t))
    return threads


def keepalive(threads):
    """Block until all task threads have exited. Log individual deaths as they happen."""
    reported_dead = set()
    try:
        while True:
            time.sleep(5)
            dead = [n for n, t in threads if not t.is_alive()]
            for n in dead:
                if n not in reported_dead:
                    print(f"[tasks] {n} thread has died — other tasks continue running")
                    reported_dead.add(n)
            if len(dead) == len(threads):
                print(f"[tasks] all tasks have exited ({', '.join(dead)}) — shutting down")
                return
    except KeyboardInterrupt:
        print("\n[tasks] interrupted — bye")


def run_terminal():
    print("router ready — Qwen handles messages and calls Claude Code when needed. "
          "Prefix `cc ` to force Claude Code, `gc ` to force local. Ctrl-D to quit.\n")
    while True:
        try:
            user = input("> ").strip()
        except EOFError:
            print()
            break
        if not user or user in ("exit", "quit"):
            break
        print(route(user))
        print()


def main():
    load_env()
    load_history()
    load_skills()
    reload_memory()
    log_heartbeat()
    threads = start_tasks()
    if sys.stdin.isatty():
        run_terminal()  # tasks run alongside in their threads
    elif threads:
        keepalive(threads)
    else:
        sys.exit("[tasks] no tasks loaded and no TTY — nothing to do")


if __name__ == "__main__":
    main()
