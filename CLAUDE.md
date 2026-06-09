# GreenClaw — Developer Context

GreenClaw is Kev's personal Telegram→AI bridge running on a Lenovo M710q (Arch Linux).
Single file: `greenclaw.py` (~330 lines). Lean, auditable. Do not add unnecessary abstraction.

## Architecture

```
Telegram message (or terminal stdin)
    │
    ├── "gc <query>"                 →  converse_local() → Ollama (qwen2.5:3b-instruct, local, free)
    ├── "usage" / "tokens" / "cost"  →  report_usage()   → CC invocation count for today
    │
    └── anything else                →  ask_cc()         → claude CLI (Claude Code, OAuth/Pro)
```

`route(text)` is the single dispatch point, shared by both front ends
(`run_terminal()` and `run_telegram()`). Qwen runs on the box for the free path;
Claude Code is invoked per-message as a one-shot subprocess (not persistent),
using the claude.ai Pro OAuth session — there is **no Anthropic API key path**.

No CC daily call limit. The Telegram front end also runs an hourly Gmail check
in a background thread (`_mail_check_loop`), which pauses overnight during the
rest window (`REST_START`–`REST_END`, default 22:00–05:00 local) so Claude Code
isn't woken while Kev sleeps. The post-rest check still only covers the last
hour, so overnight mail is not retro-summarised at wake.

## No metered path — important

This project deliberately has **no `ANTHROPIC_API_KEY` dependency**. `ask_cc()`
builds a clean subprocess environment with the key stripped out, so Claude Code
always falls back to the OAuth/Pro session rather than billing API credits. Do
not reintroduce an API-key path, a spend cap, or a usage/token spend log — those
were removed on purpose. The only invocation record kept is `cc_calls.jsonl`
(a count of CC calls, no token data).

## Key constants (top of greenclaw.py)

| Var | Value | Purpose |
|-----|-------|---------|
| `LOCAL_MODEL` | `qwen2.5:3b-instruct` | Ollama model (the `gc` free path) |
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Local Ollama endpoint |
| `LOCAL_NUM_CTX` | `8192` | Ollama context window |
| `LOCAL_MAX_STEPS` | `8` | Max tool-call loop iterations for the local model |
| `REST_START` / `REST_END` | `22` / `5` | Overnight quiet window for the mail loop (handles midnight wrap) |
| `SHELL_MAX_OUTPUT` | `6000` | Char cap on `run_shell` output (head+tail via `_truncate`) |
| `NOTES_FILE` | `~/notes.md` | Where `add_note`/`list_notes` read and write |
| `CC_LOG_FILE` | `~/greenclaw/cc_calls.jsonl` | CC invocation log (count only) |
| `CC_BIN` | `claude` on PATH, else `~/.local/bin/claude` | Claude Code CLI binary |

The Claude Code model (`claude-sonnet-4-6`) is currently passed inline in
`ask_cc()` via the `--model` flag, not a named constant. If it needs to change
in more than one place later, promote it to a constant then.

## Tools

`run_shell`, `add_note`, and `list_notes` are defined in the `TOOLS` list and
dispatched by `dispatch_tool()`. The local model additionally gets
`delegate_to_cc` (added in `_ollama_tools()`), which lets Qwen hand a task to
Claude Code for anything needing external access it lacks (Gmail, web, APIs).

## Adding a feature

**Simple command** — add a branch in `route()` before the final `ask_cc()` fallthrough:
```python
elif text.startswith("/weather"):
    location = text[len("/weather"):].strip() or "London"
    return get_weather(location)  # implement above route()
```

**Tool for the local model** — add the schema to the `TOOLS` list (and, if it's
local-only, to `_ollama_tools()`), then handle it in `dispatch_tool()`.

## Running / restarting

```bash
# Check running
systemctl --user status greenclaw-bot.service

# Restart (do this after any code change)
systemctl --user restart greenclaw-bot.service

# Logs
journalctl --user -u greenclaw-bot.service -f
```

## Files

| File | Purpose |
|------|---------|
| `greenclaw.py` | Everything — single file, intentional |
| `.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (no API key) |
| `cc_calls.jsonl` | Claude Code invocation log (count only) |
| `~/notes.md` | Persistent notes written via `add_note` |

## Rules

- Keep it single-file. No new modules without good reason.
- No metered/API-key path. OAuth only. (See "No metered path" above.)
- No features beyond what Kev asks for.
- Test by restarting the service and sending a Telegram message.
- Confirm before anything destructive.
- Kev values lean and auditable over clever.
