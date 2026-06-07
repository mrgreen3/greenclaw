#!/usr/bin/env python3
"""Minimal Claude router.

Two front ends, one core:
  python iris.py              terminal stdin loop
  python iris.py --telegram   Telegram bot (long-poll)

Per-message channels:
  <prompt>               -> Claude API loop (MODEL): run_shell / add_note / list_notes
  iris <prompt> / ask iris   -> hand the whole job to Claude Code (full autonomy)
  usage / tokens / cost  -> report API token spend (router loop only; cc bills separately)

LAN / sole-user box. Secrets in .env (ANTHROPIC_API_KEY, TELEGRAM_*).
Deps: pip install anthropic   (httpx ships with it — no extra install)
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

import anthropic
import httpx

# Haiku for cheap/fast routine routing. Bump to claude-sonnet-4-6 / claude-opus-4-8 when a task earns it.
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 8192  # terse router replies; raise if shell output gets truncated

# Local model channel (`g <prompt>`): Ollama on the box — free, for the routine run_shell/notes loop.
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5:3b-instruct")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
LOCAL_NUM_CTX = 8192   # routing needs little; no 64k, no KV-quant
LOCAL_MAX_STEPS = 8    # tool-loop cap

NOTES_FILE = os.path.expanduser("~/notes.md")
USAGE_FILE = os.path.expanduser("~/iris/usage.jsonl")
CC_LOG_FILE = os.path.expanduser("~/iris/cc_calls.jsonl")
ALERT_FLAG_FILE = os.path.expanduser("~/iris/alerted.txt")

# Spend guards (Haiku API spend tracked in usage.jsonl; CC billed separately via CC_DAILY_LIMIT)
SPEND_ALERT = 0.50   # warn when daily Haiku spend crosses this
SPEND_CAP   = 2.00   # hard-stop Haiku calls above this
CC_DAILY_LIMIT = 20  # max CC invocations per day

# (input, output) USD per 1M tokens.
RATES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}

SYSTEM = (
    "You are a terse router agent on Kev's home server (Lenovo M710q, Linux). "
    "Use run_shell to inspect the box and carry out tasks. Use add_note to jot "
    "something down when Kev says remember/note/jot, and list_notes to read them "
    "back. Be concise — lead with the answer. Confirm before anything destructive."
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
    """Tiny KEY=value loader — no extra deps."""
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
    """Execute a shell command, return combined result text."""
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


def get_daily_spend():
    """Sum today's Haiku API spend from usage.jsonl."""
    if not os.path.exists(USAGE_FILE):
        return 0.0
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0.0
    for line in open(USAGE_FILE):
        try:
            r = json.loads(line)
            if r.get("ts", "").startswith(today):
                total += r.get("cost", 0.0)
        except Exception:  # noqa: BLE001
            continue
    return total


def get_daily_cc_calls():
    """Count today's CC invocations from cc_calls.jsonl."""
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


def should_alert():
    """True if alert threshold crossed and not yet alerted today."""
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(ALERT_FLAG_FILE):
        if open(ALERT_FLAG_FILE).read().strip() == today:
            return False
    if get_daily_spend() >= SPEND_ALERT:
        with open(ALERT_FLAG_FILE, "w") as f:
            f.write(today)
        return True
    return False


CC_BIN = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def ask_cc(prompt):
    """Hand the whole job to Claude Code headless, full autonomy. Bypasses the API loop."""
    if not (shutil.which("claude") or os.path.exists(CC_BIN)):
        return "[error] claude CLI not found"

    cc_today = get_daily_cc_calls()
    if cc_today >= CC_DAILY_LIMIT:
        return f"[blocked] CC daily limit reached ({CC_DAILY_LIMIT} calls). Reset tomorrow."

    log_cc_call(prompt)
    print(f"  [-> Claude Code, full autonomy — may take a while] (CC call {cc_today + 1}/{CC_DAILY_LIMIT} today)")
    try:
        p = subprocess.run(
            [CC_BIN, "-p", prompt, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=900,
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


def _cost(model, u):
    r_in, r_out = RATES.get(model, (3.0, 15.0))
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    return (u.input_tokens * r_in + u.output_tokens * r_out
            + cr * 0.1 * r_in + cw * 1.25 * r_in) / 1e6


def log_usage(model, u):
    try:
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "model": model,
            "in": u.input_tokens, "out": u.output_tokens,
            "cr": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cw": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cost": round(_cost(model, u), 6),
        }
        with open(USAGE_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001 — never let logging break a reply
        print(f"[usage log error] {e}")


def report_usage():
    if not os.path.exists(USAGE_FILE):
        return "no API usage logged yet."
    today = datetime.now().strftime("%Y-%m-%d")
    t_cost = t_n = a_cost = a_n = 0
    a_in = a_out = 0
    for line in open(USAGE_FILE):
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        a_cost += r.get("cost", 0); a_n += 1
        a_in += r.get("in", 0); a_out += r.get("out", 0)
        if r.get("ts", "").startswith(today):
            t_cost += r.get("cost", 0); t_n += 1
    cc_today = get_daily_cc_calls()
    return (
        f"API token spend (Haiku loop only — CC jobs bill via Claude Code separately):\n"
        f"  today: ${t_cost:.4f} over {t_n} calls | alert at ${SPEND_ALERT:.2f} | cap at ${SPEND_CAP:.2f}\n"
        f"  CC invocations today: {cc_today}/{CC_DAILY_LIMIT}\n"
        f"  total: ${a_cost:.4f} over {a_n} calls ({a_in:,} in / {a_out:,} out tokens)"
    )


def dispatch_tool(name, inp):
    if name == "run_shell":
        return run_shell(inp.get("command", ""))
    if name == "add_note":
        return add_note(inp.get("text", ""))
    if name == "list_notes":
        return list_notes()
    return f"[error] unknown tool {name}"


def _ollama_tools():
    """Convert the Anthropic-style TOOLS list to Ollama's function-tool format."""
    return [
        {"type": "function", "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }}
        for t in TOOLS
    ]


def converse_local(text):
    """`g <prompt>`: the run_shell/notes tool loop against local Ollama (granite). Stateless per call, free, no API spend."""
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
            print(f"  [g:{fn}] {args.get('command') or args.get('text') or fn}")
            msgs.append({"role": "tool", "content": dispatch_tool(fn, args)})
    return "\n".join(parts).strip() or "(no reply)"


def converse(client, messages, text):
    """Handle one user message. Returns reply text; mutates `messages`."""
    # sleep window: silent drop 22:00-05:00
    hour = datetime.now().hour
    if hour >= 22 or hour < 5:
        return None

    # router-level commands (no model call)
    if text in ("usage", "tokens", "cost"):
        return report_usage()
    if text.startswith("h "):
        pass  # fall through to Haiku below
    elif text.startswith("ask iris "):
        return ask_cc(text[9:].strip())
    elif text.startswith("iris "):
        return ask_cc(text[5:].strip())
    else:
        return converse_local(text.strip())  # default: free local Ollama
    # Haiku spend guard
    daily = get_daily_spend()
    if daily >= SPEND_CAP:
        return f"[blocked] daily Haiku spend cap ${SPEND_CAP:.2f} reached (${daily:.4f} spent). Reset tomorrow."

    messages.append({"role": "user", "content": text})
    parts = []
    while True:
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM, tools=TOOLS, messages=messages
        )
        log_usage(MODEL, resp.usage)
        messages.append({"role": "assistant", "content": resp.content})

        for block in resp.content:
            if block.type == "text" and block.text.strip():
                parts.append(block.text)

        if resp.stop_reason != "tool_use":
            break

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                marker = block.input.get("command") or block.input.get("text") or block.name
                print(f"  [{block.name}] {marker}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": dispatch_tool(block.name, block.input),
                })
        messages.append({"role": "user", "content": results})

    reply = "\n".join(parts).strip() or "(no reply)"
    if should_alert():
        reply += f"\n\n⚠️ spend alert: Haiku daily spend crossed ${SPEND_ALERT:.2f} (${get_daily_spend():.4f} so far). Cap at ${SPEND_CAP:.2f}."
    return reply


def run_terminal(client):
    messages = []
    print("router ready — type a prompt, 'usage' for spend, Ctrl-D or 'exit' to quit.\n")
    while True:
        try:
            user = input("> ").strip()
        except EOFError:
            print()
            break
        if not user:
            continue
        if user in ("exit", "quit"):
            break
        reply = converse(client, messages, user)
        if reply is not None:
            print(reply)
        print()


def run_telegram(client):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN not set in .env")
    allowed = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    api = f"https://api.telegram.org/bot{token}"
    messages = []
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
            reply = converse(client, messages, text)
            if reply is not None:
                send(chat, reply)


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set — put it in .env or export it.")
    client = anthropic.Anthropic()
    if "--telegram" in sys.argv[1:]:
        run_telegram(client)
    else:
        run_terminal(client)


if __name__ == "__main__":
    main()
