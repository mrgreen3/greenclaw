# GreenClaw

> A lightweight AI assistant that runs on old hardware and talks to you via Telegram. No GPU required, no per-token billing, no waste.

<img src="mrclaw-green.svg" width="100"/>

A personal Telegram→AI bridge running on a low-power home server. Send a message, get a capable AI response — no GPU, no cloud subscription beyond what you already have, no waste.

Single Python file. Lean, auditable, yours.

---

## What it does

GreenClaw sits on a headless Lenovo M710q (Arch Linux, ~10W idle) and listens for Telegram messages via long-poll. Each message is routed to the right AI backend depending on what you need. Results come back to Telegram.

It can run shell commands on the server, take notes, answer questions, and hand off complex tasks to Claude Code for full agentic autonomy — all from a phone.

---

## How it works

### Message routing

| Prefix | Goes to | Cost |
|--------|---------|------|
| _(anything)_ | Claude Code CLI via OAuth | Pro subscription (no per-token billing) |
| `gc <prompt>` | Local Ollama (Qwen2.5:3b) | Free — runs on the box |
| `usage` / `tokens` / `cost` | CC invocation count | — |

**Default path** (no prefix) delegates to Claude Code running headlessly on the server. Claude Code uses your claude.ai Pro OAuth session — no API credits consumed.

**`gc` path** runs Qwen2.5:3b-instruct locally via Ollama. Zero cloud, zero cost, instant for routine tasks like checking system state or running commands.

### Tools available to the AI

- `run_shell` — execute any command on the server and return output
- `add_note` — append a timestamped note to `~/notes.md`
- `list_notes` — read notes back

Claude Code (default path) has full autonomy: web search, file access, GitHub, email, anything Claude Code can do.

### Architecture

```
Telegram message
    │
    ├── gc <prompt>     →  Ollama (local, Qwen2.5:3b)  →  free
    ├── usage           →  CC invocation count
    │
    └── anything else   →  Claude Code CLI (OAuth/Pro)  →  subscription
```

Runs as a systemd user service. Survives reboots and SSH disconnects.

---

## The green angle

GreenClaw was designed around a simple principle: **don't burn resources you don't need to**.

**Hardware**: The Lenovo M710q is a mini PC that draws around 10W at idle, 35W under load. It was already running 24/7. GreenClaw adds negligible overhead to a box that would be on anyway.

**No GPU**: Most personal AI setups assume you need a GPU. GreenClaw doesn't — it routes to the right tool for the job rather than running a large local model constantly.

**Local first where it fits**: The `gc` path runs Qwen2.5:3b on-device via Ollama. For simple tasks — check a log, run a command, look something up — it never leaves the house. No API call, no cloud inference, no energy spent in a data centre.

**Subscription over metered for heavy work**: For tasks that need a capable model, GreenClaw delegates to Claude Code using an OAuth session tied to a flat-rate Pro subscription. The cost is fixed regardless of usage — no incentive to minimise tokens at the expense of quality, and no surprise bills from heavy use.

**No metered API path**: GreenClaw has no Anthropic API key dependency. There is no paid-per-token path, no spend guards needed, no surprise bills. If something routes to Claude Code and it fails, it fails cleanly — it doesn't fall back to a billing path.

**Sleeps when you do**: The optional hourly Gmail digest pauses overnight (22:00–05:00 by default, set via `REST_START`/`REST_END`). The box doesn't wake the cloud model to summarise mail while you're asleep — work tracks the hours you're actually around to act on it.

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
# Terminal (interactive)
python greenclaw.py

# Telegram bot
python greenclaw.py --telegram
```

### Systemd service

```bash
# Install the service file
cp greenclaw-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload

# Enable and start
systemctl --user enable --now greenclaw-bot.service

# Survive logout
loginctl enable-linger $USER

# Logs
journalctl --user -u greenclaw-bot.service -f

# Restart after changes
systemctl --user restart greenclaw-bot.service
```

---

## Files

| File | Purpose |
|------|---------|
| `greenclaw.py` | Everything — single file, intentional |
| `.env` | Secrets — never commit this |
| `cc_calls.jsonl` | Claude Code invocation log |
| `~/notes.md` | Notes written via `add_note` tool |

---

## Hardware

Lenovo M710q Tiny — Intel Core i5, 16GB RAM, 234GB NVMe, running SwayBang Linux (Arch-based). Headless, boots to TTY. Accessible via Tailscale and SSH.

---

## Roadmap

GreenClaw is a few days old and actively being shaped. Things being explored:

- Skills system — drop in `.md` files to add new capabilities
- System management tasks (updates, cache clearing, health checks)
- Smarter routing between local and cloud models
- Hardware tier guide — Pi 4, mini PC, old laptop
- Easier first-run setup

---

## Name

GreenClaw: low footprint, runs quiet, shows up when needed. The green is in the approach — not a badge, just a design constraint.
