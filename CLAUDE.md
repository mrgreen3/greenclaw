# GreenClaw — Developer Context

GreenClaw is Kev's personal Telegram→AI bridge running on Lenovo M710q (192.168.1.64, Arch Linux).
Single file: `greenclaw.py` (~476 lines). Lean, auditable. Do not add unnecessary abstraction.

## Architecture

```
Telegram message
    │
    ├── "gc <query>"             →  converse_local() → Ollama (qwen2.5:3b-instruct, local, no CC)
    ├── "h <prompt>"             →  converse()       → Anthropic API (haiku, paid — high-burn fallback)
    ├── "usage" / "tokens" / "cost"  →  report_usage()
    │
    └── anything else            →  ask_cc()         → claude CLI (CC, sonnet, free via Pro sub)
```

Qwen monitors 24/7. CC is invoked per-message as a one-shot subprocess (not persistent).
No quiet hours. No CC daily call limit.

## Key constants (top of greenclaw.py)

| Var | Value | Purpose |
|-----|-------|---------|
| `MODEL` | `claude-haiku-4-5-20251001` | Anthropic API model (paid path) |
| `LOCAL_MODEL` | `qwen2.5:3b-instruct` | Ollama model (default free path) |
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Local Ollama endpoint |
| `CC_BIN` | `~/.local/bin/claude` | Claude Code CLI binary |
| `SPEND_CAP` | set in code | Daily $ cap for Anthropic API spend |
| `CC_DAILY_LIMIT` | set in code | Max CC calls per day |

## Adding a feature

**Simple command** — add a branch in `converse()` before the final `else` (Ollama fallback):
```python
elif text.startswith("/weather"):
    location = text[8:].strip() or "London"
    return get_weather(location)  # implement above converse()
```

**Tool for local model** — add to `_ollama_tools()` and handle in `dispatch_tool()`.

**Tool for Haiku path** — add to `TOOLS` list and handle in the tool dispatch loop inside `converse()`.

## Running / restarting

```bash
# Check running
systemctl --user status greenclaw-bot.service

# Restart
systemctl --user restart greenclaw-bot.service

# Logs
journalctl --user -u greenclaw-bot.service -f
```

## Files

| File | Purpose |
|------|---------|
| `greenclaw.py` | Everything — single file intentional |
| `.env` | `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `TELEGRAM_CHAT_ID` |
| `usage.jsonl` | Anthropic API token spend log |
| `cc_calls.jsonl` | CC invocation log |
| `~/notes.md` | Persistent notes written via `add_note` tool |

## Rules

- Keep it single-file. No new modules without good reason.
- No features beyond what Kev asks for.
- Test by restarting and sending a Telegram message.
- Confirm before anything destructive.
- Kev values lean and auditable over clever.
