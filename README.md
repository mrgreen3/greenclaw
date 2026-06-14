# GreenClaw

> A lightweight AI assistant that runs on old hardware and talks to you via Telegram. No GPU required, no per-token billing, no waste.

<img src="mrclaw-green.svg" width="100"/>

A personal Telegram→AI bridge running on a low-power home server. Send a message, get a capable AI response — no GPU, no cloud subscription beyond what you already have, no waste.

Single Python file. Lean, auditable, yours.

---

## What it does

GreenClaw sits on a headless Lenovo M710q (Arch Linux, ~10W idle) and listens for Telegram messages via long-poll. Each message is routed to the right AI backend depending on what you need. Results come back to Telegram.

It can run shell commands on the server, take notes, answer questions, and hand off complex tasks to Claude Code for full agentic autonomy — all from a phone. It maintains per-chat rolling conversation history, so follow-up messages work naturally without repeating context. New capabilities are added as [skills](#skills) (markdown recipes you drop in a folder) and new ways to talk to it are added as [tasks](#tasks) (small Python connectors).

---

## How it works

### Message routing

| Prefix | Goes to | Cost |
|--------|---------|------|
| _(anything)_ | Qwen first — delegates to Claude Code when it needs more reach | Free unless it delegates |
| `cc <prompt>` | Forces Claude Code CLI via OAuth | Pro subscription (no per-token billing) |
| `gc <prompt>` | Forces local Ollama (Qwen2.5:3b) | Free — runs on the box |
| `/<trigger> …` | A skill recipe (see [Skills](#skills)) | Free or subscription, per skill |
| `/cheat` | Built-in cheat sheet — prefixes, commands, loaded skills | — |
| `usage` / `calls` | CC invocation count today | — |

**Default path** (no prefix) goes to the local model first. Qwen handles what it can on the box and delegates to Claude Code itself when a request needs more reach — email, the web, GitHub, or anything multi-step. Claude Code runs headlessly via your claude.ai Pro OAuth session, only when something actually calls for it.

**Force a model** when you want to skip the triage: `cc <prompt>` goes straight to Claude Code, `gc <prompt>` stays on local Qwen. Qwen is zero cloud, zero cost — instant for routine tasks like checking system state or running commands.

### Tools available to the AI

- `run_shell` — execute any command on the server and return output
- `add_note` — append a timestamped note to `~/notes.md`
- `list_notes` — read notes back

Claude Code has full autonomy: web search, file access, GitHub, email, anything Claude Code can do.

### Architecture

```
Incoming message (Telegram or other task)
    │
    ├── /<trigger> …    →  matching skill recipe       →  local or CC, per skill
    ├── cc <prompt>     →  Claude Code CLI (OAuth/Pro)  →  forced
    ├── gc <prompt>     →  Ollama (local, Qwen2.5:3b)   →  forced
    ├── /cheat          →  built-in cheat sheet         →  no LLM
    ├── usage / calls   →  CC invocation count          →  no LLM
    │
    └── anything else   →  Qwen first  →  delegates to Claude Code only when needed
```

The core gateway is dispatch-only — it doesn't know or care which connector a message came in on. [Tasks](#tasks) own the connectors (Telegram today, others later); the same routing applies to all.

Runs as a systemd user service. Survives reboots and SSH disconnects.

---

## Skills

Skills are how you add new capabilities **without touching the code**. The gateway stays static; you drop a markdown file in `skills/`, restart, and it's live.

A skill is a recipe — instructions the assistant follows — not a plugin or a chunk of code. Claude Code already has the muscle (shell, web, GitHub, email); a skill just tells it what to do. They're plain markdown with a small front-matter block:

```markdown
---
name: system-health
description: Check disk, memory, load, and the bot service. Use when the user asks how the box is doing.
exposes: local          # local (Qwen) | cc (Claude Code) | both
trigger: /health        # the command that runs it
locked: false           # true = must be armed in skills.allow before it runs
source: owner           # who wrote it — for auditing
---

Run df -h, free -h and uptime, then summarise in a few lines.
Flag anything that looks off. Don't suggest fixes unless something's wrong.
```

Send `/health` and the recipe runs. Anything you type after the trigger is passed straight through as input, so `/post write about the M710q build` hands that prompt to the `blog-post` skill.

**Loaded lean.** At startup the gateway reads only each skill's front matter — never the body — so skills don't eat into the local model's context just by existing. The full recipe is loaded from disk only on the turn it actually runs.

**The lock.** A skill marked `locked: true` won't run unless its name is listed in `skills.allow`. That's the safety catch for anything with reach — destructive commands, anything touching external accounts. The shipped `blog-post` skill is locked by default; uncomment it in `skills.allow` and restart to arm it. To see exactly what the bot can do right now: `cat skills.allow` plus the boot log, which prints what loaded and what was blocked.

**Adding one.** Write `skills/my-thing.md`, restart the service. That's the whole workflow.

---

## Tasks

Skills are recipes for **what to do** with a message. Tasks are connectors for **how messages get in and out** — Telegram, and whatever you add next.

A task is a small Python module in `tasks/` that exposes one function:

```python
def start(on_message):
    # loop forever, and for each incoming message call:
    #   on_message(text, reply, chat_id)
    # where reply(text) sends the answer back on the same channel,
    # and chat_id is a string identifying the conversation (for history tracking).
```

Tasks load at boot and each runs in its own daemon thread, so a long Claude Code call on one channel doesn't freeze the others. The core routing (`cc `, `gc `, `/<trigger>`, etc.) is shared between every task.

**Shipped.** `tasks/telegram.py` — long-polls the Telegram Bot API, locks to a single chat ID, dispatches each incoming message in a worker thread so 15-minute CC calls never stall the poll loop. Sends a `typing…` indicator before dispatching so the chat feels responsive during longer calls.

**Adding one.** Write `tasks/signal.py` (or `discord.py`, or anything else), restart. No flags, no wiring — anything in `tasks/` that has a `start(on_message)` runs.

---

## The green angle

GreenClaw was designed around a simple principle: **don't burn resources you don't need to**.

**Hardware**: The Lenovo M710q is a mini PC that draws around 10W at idle, 35W under load. It was already running 24/7. GreenClaw adds negligible overhead to a box that would be on anyway.

**No GPU**: Most personal AI setups assume you need a GPU. GreenClaw doesn't — it routes to the right tool for the job rather than running a large local model constantly.

**Local first by default**: Qwen2.5:3b runs on-device via Ollama and is the first responder for every message. For simple tasks — check a log, run a command, look something up — it never leaves the house. No API call, no cloud inference, no energy spent in a data centre.

**Subscription over metered for heavy work**: For tasks that need a capable model, GreenClaw delegates to Claude Code using an OAuth session tied to a flat-rate Pro subscription. The cost is fixed regardless of usage — no incentive to minimise tokens at the expense of quality, and no surprise bills from heavy use.

**No metered API path**: GreenClaw has no Anthropic API key dependency. There is no paid-per-token path, no spend guards needed, no surprise bills. If something routes to Claude Code and it fails, it fails cleanly — it doesn't fall back to a billing path.

**Nothing runs on a timer**: GreenClaw never wakes the cloud model on a schedule. There's no background polling of your inbox, no cron job quietly burning through your subscription while you sleep. Claude Code runs only when a message — or a skill you triggered — actually needs it. Want your mail summarised? Ask (`/mail`), and it happens then, not every hour whether you're looking or not.

**The fix that started it**: An early version passed the Anthropic API key to Claude Code subprocesses, causing OAuth-authed Claude Code to fall back to billing API credits. That was caught, fixed, and then the metered path removed entirely. Claude Code now runs in a clean environment without the API key, ensuring it always uses the OAuth session.

---

## This is not for you if...

- You want a polished, point-and-click setup
- You need it to work on Windows or macOS (Linux only, intentionally)
- You're looking for a hosted service — this runs on your hardware, your network
- You want a large capable local model — GreenClaw is built around small, efficient ones

---

## Setup

### Requirements

- Python 3.11+
- [Ollama](https://ollama.com) with `qwen2.5:3b-instruct` pulled
- Claude Code CLI installed and logged in (`claude login`)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

### Install

```bash
git clone git@github.com:mrgreen3/greenclaw.git
cd greenclaw
python -m venv .venv && source .venv/bin/activate
pip install httpx
cp .env.example .env   # fill in your keys
```

### `.env`

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...   # your Telegram user ID — locks the bot to you only
```

To find your chat ID: leave `TELEGRAM_CHAT_ID` blank, start the bot, message it — it will report your ID. Set it and restart.

> **Security model**: access is gated on your Telegram chat ID, and the bot can run shell commands and drive Claude Code with `--dangerously-skip-permissions`. In practice that means the bot token is the key to the box — anyone holding it can reach it. Treat it like a root password. This is fine for a sole-user box on a private network (Tailscale here); it is not hardened for wider exposure.

### Run

```bash
python greenclaw.py
```

No flags. Tasks in `tasks/` always start. If stdin is a TTY (you ran it interactively) the terminal prompt opens alongside; if not (running under systemd) the process just keeps the tasks alive.

### Systemd service

```bash
# Install the service file
cp greenclaw.service ~/.config/systemd/user/
systemctl --user daemon-reload

# Enable and start
systemctl --user enable --now greenclaw.service

# Survive logout
loginctl enable-linger $USER

# Logs
journalctl --user -u greenclaw.service -f

# Restart after changes
systemctl --user restart greenclaw.service
```

---

## Files

| File | Purpose |
|------|---------|
| `greenclaw.py` | The gateway — single file, intentional |
| `skills/` | Skill recipes (`*.md`) — add capabilities here, no code |
| `skills.allow` | Arms `locked` skills — one name per line |
| `tasks/` | Always-on connectors (`*.py`) — Telegram and any others |
| `static/` | Editable static text — `cheat.md` lives here |
| `.env` | Secrets (chmod 600) — never commit this |
| `cc_calls.jsonl` | Claude Code invocation log (gitignored) |
| `~/notes.md` | Notes written via `add_note` tool |

---

## Hardware

Lenovo M710q Tiny — Intel Core i5, 16GB RAM, 234GB NVMe, running SwayBang Linux (Arch-based). Headless, boots to TTY. Accessible via Tailscale and SSH.

---

## Roadmap

GreenClaw is a few days old and actively being shaped. Things being explored:

- Skills v2 — let the local model pick a skill from a description menu, on top of the explicit triggers that work today
- Smarter routing between local and cloud models
- Hardware tier guide — Pi 4, mini PC, old laptop
- Easier first-run setup

Done so far:
- [Skills](#skills) — static gateway, markdown recipes, explicit triggers, lock file
- [Tasks](#tasks) — pluggable always-on connectors (Telegram today, room for more)
- Built-in `/cheat` cheat sheet driven by `static/cheat.md`
- Per-chat rolling history — Qwen remembers the last 10 exchanges per conversation; context survives within a session (in-memory; cleared on restart — see [#7](https://github.com/mrgreen3/greenclaw/issues/7))
- Telegram typing indicator — `typing…` sent before dispatching so the chat feels live during longer calls
- Runtime-aware system prompt — at startup, `_build_system()` reads `/etc/os-release` and probes installed tools via `which`, so Qwen knows the actual OS and what's available without being told each time
- System management via natural language — common sysadmin phrases (`update system`, `disk space`, `what's running`) are handled immediately via `run_shell` without asking for clarification; Qwen knows it's on Arch and uses `pacman`, not `apt`

---

## Name

GreenClaw: low footprint, runs quiet, shows up when needed. The green is in the approach — not a badge, just a design constraint.
