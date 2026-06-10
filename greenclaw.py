#!/usr/bin/env python3
"""Minimal Claude router.

Two front ends, one core:
  python greenclaw.py              terminal stdin loop
  python greenclaw.py --telegram   Telegram bot (long-poll)

Per-message channels:
  <prompt>               -> Qwen first (local); it delegates to Claude Code when needed
  cc <prompt>            -> force Claude Code CLI (OAuth/Pro, full autonomy)
  gc <prompt>            -> force local Ollama (Qwen2.5:3b, free, on-device)
  /<trigger> ...         -> a skill recipe from skills/
  usage / tokens / cost  -> CC invocation count

LAN / sole-user box. Secrets in .env (TELEGRAM_*).
Deps: pip install httpx
"""

import json
import os
import shutil
import subprocess
import sys
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

SKILLS = {}  # name -> {description, exposes, trigger, locked, source, path}; filled at boot

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


def get_daily_cc_calls():
    if not os.path.exists(CC_LOG_FILE):
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for line in open(CC_LOG_FILE):
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
    cc_today = get_daily_cc_calls()
    return f"Claude Code invocations today: {cc_today}"


CC_BIN = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def ask_cc(prompt):
    """Hand the whole job to Claude Code headless, full autonomy."""
    if not (shutil.which("claude") or os.path.exists(CC_BIN)):
        return "[error] claude CLI not found"

    log_cc_call(prompt)
    print("  [-> Claude Code]")
    try:
        cc_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        p = subprocess.run(
            [CC_BIN, "-p", prompt, "--model", "claude-sonnet-4-6", "--dangerously-skip-permissions"],
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


def converse_local(text, system_extra=None):
    """Route to local Ollama — free, on-device, no cloud.

    system_extra: optional skill body, appended to SYSTEM for this run only.
    """
    system = SYSTEM if not system_extra else f"{SYSTEM}\n\n--- skill ---\n{system_extra}"
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]
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
            print(f"  [g:{fn}] {args.get('command') or args.get('query') or fn}")
            msgs.append({"role": "tool", "content": dispatch_tool(fn, args)})
    return "\n".join(parts).strip() or "(no reply)"


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
        for line in open(SKILLS_ALLOW):
            line = line.strip()
            if line and not line.startswith("#"):
                allow.add(line)
    loaded, blocked = [], []
    for fn in sorted(os.listdir(SKILLS_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(SKILLS_DIR, fn)
        head = open(path).read(4096)  # front matter only; bodies load on demand
        meta, _ = parse_front_matter(head)
        name = meta.get("name") or fn[:-3]
        locked = meta.get("locked", "false").lower() == "true"
        if locked and name not in allow:
            blocked.append(name)
            continue
        trigger = meta.get("trigger", "")
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
        body = parse_front_matter(open(skill["path"]).read())[1]
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


def route(text):
    """Shared routing logic for both terminal and Telegram.

    Qwen-first: with no prefix, the local model handles it and delegates to Claude
    Code itself when it needs more reach. `cc ` forces Claude Code; `gc ` forces local.
    """
    if text in ("usage", "tokens", "cost"):
        return report_usage()
    skill = match_skill_trigger(text)
    if skill:
        return run_skill(skill, text)
    if text.startswith("cc "):
        return ask_cc(text[3:].strip())
    if text.startswith("gc "):
        return converse_local(text[3:].strip())
    return converse_local(text)  # default: Qwen first, delegates to CC when needed


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


def run_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN not set in .env")
    allowed = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    api = f"https://api.telegram.org/bot{token}"
    offset = None

    def send(chat, text):
        text = text or "(empty)"
        for i in range(0, len(text), 4000):
            try:
                httpx.post(f"{api}/sendMessage",
                           json={"chat_id": chat, "text": text[i:i + 4000]}, timeout=30)
            except Exception as e:  # noqa: BLE001
                print(f"[send error] {e}")

    if allowed:
        print(f"telegram bot running — locked to chat {allowed}")
    else:
        print("telegram bot running — UNLOCKED: reports chat ids only, executes nothing. "
              "Message it, set TELEGRAM_CHAT_ID in .env, restart.")

    while True:
        try:
            r = httpx.get(f"{api}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            updates = r.json().get("result", [])
        except Exception as e:  # noqa: BLE001
            print(f"[poll error] {e}")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            text = (msg.get("text") or "").strip()
            chat = msg.get("chat", {}).get("id")
            if not text or chat is None:
                continue
            if not allowed:
                send(chat, f"Bot unlocked. Your chat id is {chat}. "
                           f"Set TELEGRAM_CHAT_ID={chat} in .env and restart to enable.")
                print(f"[unlocked] chat {chat} said: {text!r}")
                continue
            if str(chat) != allowed:
                send(chat, "unauthorized")
                print(f"[blocked] chat {chat}: {text!r}")
                continue
            print(f"[tg {chat}] {text}")
            send(chat, route(text))


def main():
    load_env()
    load_skills()
    if "--telegram" in sys.argv[1:]:
        run_telegram()
    else:
        run_terminal()


if __name__ == "__main__":
    main()
