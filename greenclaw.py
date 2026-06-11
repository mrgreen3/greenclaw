#!/usr/bin/env python3
"""Minimal Claude router.

Two front ends, one core:
  python greenclaw.py              terminal stdin loop
  python greenclaw.py --tasks     run always-on tasks from tasks/ (Telegram etc.)

Per-message channels:
  <prompt>               -> Qwen first (local); it delegates to Claude Code when needed
  cc <prompt>            -> force Claude Code CLI (OAuth/Pro, full autonomy)
  gc <prompt>            -> force local Ollama (Qwen2.5:3b, free, on-device)
  /<trigger> ...         -> a skill recipe from skills/
  usage / calls          -> CC invocation count today
  /cheat                 -> built-in cheat sheet (prefixes, commands, skills)

Skills vs tasks:
  skills/*.md   triggered recipes — what to do with a request
  tasks/*.py    always-on connectors — how messages get in and out.
                A task implements start(on_message) and calls
                on_message(text, reply, chat_id) per incoming message, where
                reply(text) sends the answer back on the same channel.

LAN / sole-user box. Secrets in .env (TELEGRAM_*).
Deps: pip install httpx
"""

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
SKILL_BODY_WARN = 6000  # chars; warn if a local skill body is large for Qwen's context

# Tasks: always-on connectors (Telegram, Signal, ...) loaded from tasks/*.py.
TASKS_DIR = os.path.join(_HERE, "tasks")

NOTES_FILE = os.path.expanduser("~/notes.md")

SKILLS = {}  # name -> {description, exposes, trigger, locked, source, path}; filled at boot

# Per-chat rolling history for converse_local. In-memory only; cleared on restart.
# Keys are chat_id strings; values are lists of {role, content} dicts.
_history: dict = {}
HISTORY_MAX_TURNS = 10  # pairs (user + assistant); older turns are dropped

SYSTEM = (
    "You are the first responder on the user's home server (Linux). "
    "You are a small local model: handle simple things yourself and be honest about your limits. "
    "Use run_shell to inspect the box or run commands. "
    "Delegate to Claude Code via delegate_to_cc WHENEVER a request needs reach you "
    "don't have — email/Gmail, the web, GitHub, calendar, APIs, or any multi-step or "
    "complex task. In particular, if the user asks about email, their inbox, messages, or "
    "whether someone has written, replied or been in touch, call delegate_to_cc. "
    "When you delegate, pass a complete, specific instruction that includes the user's "
    "original request. Never invent things you can't actually access — delegate instead. "
    "Be concise — lead with the answer. Confirm before anything destructive."
)

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
    return "".join(lines[-int(limit):]).rstrip()


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


def ask_cc(prompt):
    """Hand the whole job to Claude Code headless, full autonomy."""
    if not os.path.exists(CC_BIN):
        return "[error] claude CLI not found"

    log_cc_call(prompt)
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
        return out or "(no output)"
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
    system = SYSTEM if not system_extra else f"{SYSTEM}\n\n--- skill ---\n{system_extra}"
    history = _history.get(str(chat_id), []) if chat_id is not None else []
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
            msgs.append({"role": "tool", "content": dispatch_tool(fn, args)})
    reply = "\n".join(parts).strip() or "(no reply)"
    # Save history: append this user/assistant pair and trim to the rolling window.
    if chat_id is not None:
        key = str(chat_id)
        updated = _history.get(key, []) + [
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply},
        ]
        _history[key] = updated[-(HISTORY_MAX_TURNS * 2):]
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
            head = f.read(4096)  # front matter only; bodies load on demand
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


def match_skill_trigger(text):
    """Return the skill whose trigger is the first whitespace token of text, else None."""
    first = text.split(None, 1)[0] if text.split() else ""
    for skill in SKILLS.values():
        if skill["trigger"] and skill["trigger"] == first:
            return skill
    return None


def run_skill(skill, text):
    """Load the skill body on demand and dispatch to the declared engine."""
    try:
        with open(skill["path"]) as f:
            body = parse_front_matter(f.read())[1]
    except Exception as e:  # noqa: BLE001
        return f"[skill error] could not read {skill['path']}: {e}"
    arg = text[len(skill["trigger"]):].strip() if skill["trigger"] else text
    if skill["exposes"] == "cc":
        prompt = f"{body}\n\n--- user request ---\n{arg}" if arg else body
        return ask_cc(prompt)
    # local or both: run on Qwen (which can still delegate_to_cc itself if needed)
    if len(body) > SKILL_BODY_WARN:
        print(f"[skills] warning: '{skill['name']}' body is {len(body)} chars — may crowd Qwen's {LOCAL_NUM_CTX}-token context")
    return converse_local(arg or "Run this skill now.", system_extra=body)


def route(text, chat_id=None):
    """Shared routing logic for every front end (terminal and all tasks).

    Qwen-first: with no prefix, the local model handles it and delegates to Claude
    Code itself when it needs more reach. `cc ` forces Claude Code; `gc ` forces local.
    chat_id: passed through to converse_local for per-chat history tracking.
    """
    if text in ("usage", "calls"):
        return report_usage()
    if text in ("/cheat", "cheat"):
        return report_cheat()
    skill = match_skill_trigger(text)
    if skill:
        return run_skill(skill, text)
    if text.startswith("cc "):
        return ask_cc(text[3:].strip())
    if text.startswith("gc "):
        return converse_local(text[3:].strip(), chat_id=chat_id)
    return converse_local(text, chat_id=chat_id)  # default: Qwen first


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
    load_skills()
    threads = start_tasks()
    if sys.stdin.isatty():
        run_terminal()  # tasks run alongside in their threads
    elif threads:
        keepalive(threads)
    else:
        sys.exit("[tasks] no tasks loaded and no TTY — nothing to do")


if __name__ == "__main__":
    main()
