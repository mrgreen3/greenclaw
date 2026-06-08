#!/usr/bin/env python3
"""Minimal Claude router.

Two front ends, one core:
  python greenclaw.py              terminal stdin loop
  python greenclaw.py --telegram   Telegram bot (long-poll)

Per-message channels:
  <prompt>               -> Claude Code CLI (OAuth/Pro, full autonomy)
  gc <prompt>            -> local Ollama (Qwen2.5:3b, free, on-device)
  usage / tokens / cost  -> CC invocation count

LAN / sole-user box. Secrets in .env (TELEGRAM_*).
Deps: pip install httpx
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

import httpx

# Local model channel: Ollama on the box — free, for the routine run_shell/notes loop.
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5:3b-instruct")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
LOCAL_NUM_CTX = 8192
LOCAL_MAX_STEPS = 8

NOTES_FILE = os.path.expanduser("~/notes.md")
CC_LOG_FILE = os.path.expanduser("~/greenclaw/cc_calls.jsonl")

SYSTEM = (
    "You are a terse router agent on Kev's home server (Lenovo M710q, Linux). "
    "Use run_shell to inspect the box and carry out tasks. Use add_note to jot "
    "something down when Kev says remember/note/jot, and list_notes to read them "
    "back. Use delegate_to_cc for anything requiring external access you lack — "
    "Gmail, web search, calendar, APIs — never say you can't do it, just delegate. "
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
        "description": "Append a timestamped note to Kev's notes file. Use when he says remember/note/jot/add to notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The note text."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_notes",
        "description": "Read back Kev's saved notes.",
        "input_schema": {"type": "object", "properties": {}},
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


def run_shell(command):
    try:
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        out = p.stdout
        if p.stderr:
            out += "\n[stderr]\n" + p.stderr
        out += f"\n[exit {p.returncode}]"
        return out.strip()
    except subprocess.TimeoutExpired:
        return "[error] command timed out (60s)"
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"


def add_note(text):
    text = (text or "").strip()
    if not text:
        return "[error] empty note"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(NOTES_FILE, "a") as f:
        f.write(f"- [{ts}] {text}\n")
    return f"noted: {text}"


def list_notes():
    if not os.path.exists(NOTES_FILE):
        return "(no notes yet)"
    lines = open(NOTES_FILE).read().strip().splitlines()
    if not lines:
        return "(no notes yet)"
    tail = lines[-40:]
    head = "" if len(lines) <= 40 else f"(last 40 of {len(lines)})\n"
    return head + "\n".join(tail)


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
    if name == "add_note":
        return add_note(inp.get("text", ""))
    if name == "list_notes":
        return list_notes()
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


def converse_local(text):
    """Route to local Ollama — free, on-device, no cloud."""
    msgs = [
        {"role": "system", "content": SYSTEM},
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
            print(f"  [g:{fn}] {args.get('command') or args.get('text') or args.get('query') or fn}")
            msgs.append({"role": "tool", "content": dispatch_tool(fn, args)})
    return "\n".join(parts).strip() or "(no reply)"


def route(text):
    """Shared routing logic for both terminal and Telegram."""
    if text in ("usage", "tokens", "cost"):
        return report_usage()
    if text.startswith("gc "):
        return converse_local(text[3:].strip())
    return ask_cc(text)


def run_terminal():
    print("router ready — gc <prompt> for local, anything else via Claude Code. Ctrl-D to quit.\n")
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


def _mail_check_loop(send, chat):
    """Background thread: hourly email check via CC."""
    time.sleep(3600)
    while True:
        print("[hourly] checking mail via CC")
        reply = ask_cc(
            "Check my Gmail for any new emails received in the last hour. "
            "Summarise anything that needs attention — sender, subject, one line. "
            "If nothing worth flagging just say: No new mail."
        )
        send(chat, reply)
        time.sleep(3600)


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
        threading.Thread(target=_mail_check_loop, args=(send, allowed), daemon=True).start()
    else:
        print("telegram bot running — UNLOCKED: reports chat ids only, executes nothing. "
              "Message it, set TELEGRAM_CHAT_ID in .env, restart.")

    while True:
        try:
            r = httpx.get(f"{api}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=40)
            updates = r.json().get("result", [])
        except Exception as e:  # noqa: BLE001
            print(f"[poll error] {e}")
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
    if "--telegram" in sys.argv[1:]:
        run_telegram()
    else:
        run_terminal()


if __name__ == "__main__":
    main()
