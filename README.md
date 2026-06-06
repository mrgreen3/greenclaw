# GreenWire

Thin Claude router — a lean relay, not a brain. Takes prompts (terminal or
Telegram), hands the thinking to the Claude API, runs tools locally, returns the
answer. Runs on a low-power always-on box (Lenovo M710q). **No local model.**

## Why
Agentic AI without buying a GPU: rent intelligence per-call from the API, keep a
tiny auditable harness on hardware you already own.

## Channels
- `<prompt>`        cheap routine loop (Haiku) with shell + notes tools
- `cc <prompt>`     hand the whole job to Claude Code (full autonomy)
- `usage`           API token spend so far (router loop; cc bills separately)

## Run
    python -m venv .venv && . .venv/bin/activate
    pip install anthropic            # httpx ships with it
    cp .env.example .env             # add ANTHROPIC_API_KEY (+ TELEGRAM_* for bot)
    python router.py                 # terminal
    python router.py --telegram      # Telegram bot

Boot: systemd user service + `loginctl enable-linger`.

## Layout
- `router.py`      the whole thing
- `.env.example`   config template (never commit `.env`)
