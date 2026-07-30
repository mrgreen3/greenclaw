# GreenClaw

> A lightweight AI assistant that runs on old hardware and talks to you via Telegram. No GPU required, no per-token billing, no waste.

<img src="mrclaw-green.svg" width="100"/>

A personal Telegram→AI bridge running on a low-power home server. Send a message, get a capable AI response — no GPU, no cloud subscription beyond what you already have, no waste.

Single-file gateway. Task connectors and skills drop in alongside.

---

## What it does

GreenClaw sits on a headless Lenovo M920q (Arch Linux, ~10W idle) and listens for Telegram messages via long-poll. Each message is routed to the right AI backend depending on what you need. Results come back to Telegram.

It can run shell commands on the server, take notes, answer questions, and hand off complex tasks to Claude Code for full agentic autonomy — all from a phone. It maintains per-chat rolling conversation history, so follow-up messages work naturally without repeating context. New capabilities are added as [skills](#skills) (markdown recipes you drop in a folder) and new ways to talk to it are added as [tasks](#tasks) (small Python connectors).

---

## How it works

### Message routing

| Prefix | Goes to | Cost |
|--------|---------|------|
| _(anything)_ | Claude Code (default); falls back to the cloud model if CC errors | Pro subscription (no per-token billing) |
| `cc <prompt>` | Forces Claude Code CLI via OAuth | Pro subscription (no per-token billing) |
| `gg <prompt>` | Forces the cloud model (glm-5.2:cloud) | Ollama Cloud (metered) |
| `/<trigger> …` | A skill recipe (see [Skills](#skills)) | Free or subscription, per skill |
| `/cheat` | Built-in cheat sheet — prefixes, commands, loaded skills | — |
| `usage` / `calls` | CC invocation count today | — |
| `/version` / `version` | greenclaw version | — |
| `/model` / `model` | Cloud model info (primary + fallback) | — |
| `/memory` / `memory stats` | Memory vault stats | — |
| `/watch` | Scheduled jobs and when they last ran | — |
| `/inbox on` / `/inbox off` | Toggle the GitHub inbox watcher | — |
| `/regreen` | Restart the bot (`systemctl --user restart greenclaw.service`) | — |
| `remember <text>` | Save a fact to memory | — |

**Default path** (no prefix) goes straight to Claude Code via your claude.ai Pro OAuth session. For lighter tasks where you want a faster response, use `gg` to route to the cloud model (glm-5.2:cloud) instead.

**Force a model** when you want to be explicit: `cc <prompt>` goes straight to Claude Code, `gg <prompt>` routes to the cloud model. It runs on Ollama Cloud — fast for routine tasks like checking system state, running commands, or taking notes.

### Tools available to the AI

- `run_shell` — execute any command on the server and return output
- `add_note` — append a timestamped note to `~/notes.md`
- `list_notes` — read notes back

Claude Code has full autonomy: web search, file access, GitHub, email, anything Claude Code can do.

### Architecture

```
Incoming message (Telegram or other task)
    │
    ├── /<trigger> …    →  matching skill recipe       →  cloud model or CC, per skill
    ├── cc <prompt>     →  Claude Code CLI (OAuth/Pro)  →  forced
    ├── gg <prompt>     →  cloud model (glm-5.2:cloud, tools)  →  forced
    ├── /cheat          →  built-in cheat sheet         →  no LLM
    ├── usage / calls   →  CC invocation count          →  no LLM
    │
    └── anything else   →  Claude Code (default)
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
exposes: cc             # cc (Claude Code) | gg (cloud model) | both
trigger: /health        # the command that runs it
locked: false           # true = must be armed in skills.allow before it runs
source: owner           # who wrote it — for auditing
---

Run df -h, free -h and uptime, then summarise in a few lines.
Flag anything that looks off. Don't suggest fixes unless something's wrong.
```

Send `/health` and the recipe runs. Anything you type after the trigger is passed straight through as input, so `/post write about the M920q build` hands that prompt to the `blog-post` skill.

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

Tasks load at boot and each runs in its own daemon thread, so a long Claude Code call on one channel doesn't freeze the others. The core routing (`cc `, `gg `, `/<trigger>`, etc.) is shared between every task.

**Shipped.** `tasks/telegram.py` — long-polls the Telegram Bot API, locks to a single chat ID, dispatches each incoming message in a worker thread so 15-minute CC calls never stall the poll loop. Sends a `typing…` indicator before dispatching so the chat feels responsive during longer calls.

**Adding one.** Write `tasks/signal.py` (or `discord.py`, or anything else), restart. No flags, no wiring — anything in `tasks/` that has a `start(on_message)` runs.

---

## The green angle

GreenClaw was designed around a simple principle: **don't burn resources you don't need to**.

**Hardware**: The Lenovo M920q is a mini PC that draws around 10W at idle, 35W under load. It was already running 24/7. GreenClaw adds negligible overhead to a box that would be on anyway.

**No GPU**: Most personal AI setups assume you need a GPU. GreenClaw doesn't — it routes to the right tool for the job rather than running a large local model constantly.

**Lightweight work**: the cloud model (glm-5.2:cloud) handles shell commands, notes, quick lookups, and anything that doesn't need Claude Code's full reach. It falls back to kimi-k2.7-code:cloud, then Claude Code, if a call fails.

**Subscription over metered for heavy work**: For tasks that need a capable model, GreenClaw delegates to Claude Code using an OAuth session tied to a flat-rate Pro subscription. The cost is fixed regardless of usage — no incentive to minimise tokens at the expense of quality, and no surprise bills from heavy use.

**No Anthropic API key path**: Claude Code runs via an OAuth Pro session, not a metered Anthropic API key — no per-token spend on the heavy-work path, no surprise bills from CC usage. The lightweight cloud tier (`glm-5.2:cloud`) is metered via Ollama Cloud; cost there is bounded by the small-model routing.

**Schedules are opt-in**: GreenClaw doesn't wake the cloud model on a schedule by default — there's no cron job quietly burning through your subscription unless you add one yourself. `schedules/*.md` timed jobs exist (`/watch` lists them; `paper-trade` runs weekdays at 16:30 UTC) but they're something you deliberately add, not baseline behaviour. Claude Code otherwise runs only when a message — or a skill you triggered — actually needs it. Want your mail summarised? Ask (`/mail`), and it happens then, not every hour whether you're looking or not.

**The fix that started it**: An early version passed the Anthropic API key to Claude Code subprocesses, causing OAuth-authed Claude Code to fall back to billing API credits. That was caught, fixed, and then the metered path removed entirely. Claude Code now runs in a clean environment without the API key, ensuring it always uses the OAuth session.

---

## This is not for you if...

- You want a polished, point-and-click setup
- You need it to work on Windows or macOS (Linux only, intentionally)
- You're looking for a hosted service — this runs on your hardware, your network
- You want everything running locally with no cloud — GreenClaw relies on Claude Code (OAuth) and the Ollama Cloud tier (glm-5.2:cloud)

---

## Setup

### Requirements

- Python 3.11+
- Ollama installed and signed into Cloud (`ollama` → sign in to ollama.com); `glm-5.2:cloud` and `kimi-k2.7-code:cloud` resolvable
- Claude Code CLI installed and logged in (`claude login`)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

### Install

```bash
git clone git@github.com:mrgreen3/greenclaw.git
cd greenclaw
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
```

### `.env`

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...   # your Telegram user ID — locks the bot to you only
GC_CLOUD_MODEL=glm-5.2:cloud       # primary cloud model
GC_CLOUD_FALLBACK=kimi-k2.7-code:cloud  # secondary; auto-escalates to CC if both fail
```

Those four are all that's required to run the core bot. `.env.example` has
the full list, including optional ones for the email task (`EMAIL_*`),
dashboard (`DASHBOARD_*`), GitHub inbox watcher (`GITHUB_*`,
`GREENCLAW_GH_TOKEN`), and the paper-trading skill (`ALPHA_VANTAGE_API_KEY`).

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
| `greenclaw.py` | The gateway — routing, skills/tasks/schedules loading, cloud/CC calls |
| `shared.py` | Constants and pure helpers shared with `tasks/dashboard.py` |
| `skills/` | Skill recipes (`*.md`) and Python skills (`*.py`) — add capabilities here |
| `skills.allow` | Arms `locked` skills — one name per line |
| `tasks/` | Always-on connectors (`*.py`) — Telegram, email, dashboard, GitHub inbox |
| `tasks/telegram.py` | Telegram Bot API long-polling connector |
| `tasks/email.py` | IMAP/SMTP email connector |
| `tasks/dashboard.py` | Read-only web status page |
| `tasks/github_inbox.py` | Watches a GitHub repo for actionable issues |
| `schedules/` | Timed jobs (`*.md`) — when to run a skill automatically |
| `static/` | Editable static text — `cheat.md` lives here |
| `docs/` | Design notes and skill-specific docs (e.g. paper trading) |
| `tests/` | Test suite (`python -m unittest discover -s tests`) |
| `etfs.json` | ETF config for the paper-trade skill |
| `.env` | Secrets (chmod 600) — never commit this |
| `greenclaw.service` | systemd user service unit |
| `cc_calls.jsonl` | Claude Code invocation log (gitignored) |
| `~/notes.md` | Notes written via `add_note` tool |

---

## Hardware

Lenovo M920q Tiny — Intel Core i5, 16GB RAM, 234GB NVMe, running SwayBang Linux (Arch-based). Headless, boots to TTY. Accessible via Tailscale and SSH.

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
- Per-chat rolling history — the last 10 exchanges per conversation are preserved; persisted to disk (`~/.local/share/greenclaw/history.json`) and reloaded on restart, with a 7-day TTL on stale entries
- Telegram typing indicator — `typing…` sent before dispatching so the chat feels live during longer calls
- Runtime-aware system prompt — at startup, `_build_system()` reads `/etc/os-release` and probes installed tools via `which`, so the AI knows the actual OS and what's available without being told each time
- System management via natural language — common sysadmin phrases (`update system`, `disk space`, `what's running`) are handled immediately via `run_shell` without asking for clarification; the cloud model knows it's on Arch and uses `pacman`, not `apt`

---

## Name

GreenClaw: low footprint, runs quiet, shows up when needed. The green is in the approach — not a badge, just a design constraint.

---

## License

MIT — see [LICENSE](LICENSE).
