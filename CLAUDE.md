# GreenClaw — Developer Context

GreenClaw is a personal Telegram→AI bridge running on a low-power home server (Arch Linux).
Single file: `greenclaw.py` (~465 lines), plus `skills/*.md`. Lean, auditable. Do not
add unnecessary abstraction.

## Architecture

```
Telegram message (or terminal stdin)
    │
    ├── "/<trigger> …"               →  run_skill()      → skill recipe (local or CC, per `exposes`)
    ├── "cc <query>"                 →  ask_cc()         → claude CLI (Claude Code, OAuth/Pro) — forced
    ├── "gc <query>"                 →  converse_local() → Ollama (qwen2.5:3b-instruct) — forced
    ├── "usage" / "tokens" / "cost"  →  report_usage()   → CC invocation count for today
    │
    └── anything else                →  converse_local() → Qwen first; it calls delegate_to_cc when it needs more reach
```

`route(text)` is the single dispatch point, shared by both front ends
(`run_terminal()` and `run_telegram()`). **Qwen-first:** an un-prefixed message goes
to the local model, which delegates to Claude Code (via the `delegate_to_cc` tool)
only when it needs reach it lacks. Claude Code is invoked per-message as a one-shot
subprocess (`claude -p`, not persistent), using the claude.ai Pro OAuth session —
there is **no Anthropic API key path**.

## Nothing runs on a timer — important

Claude Code runs ONLY in response to a message or a triggered skill. There is no
background loop, no scheduled/cron CC invocation, no inbox polling. This is
deliberate: headless `claude -p` is automated use, which (a) sits outside "ordinary
individual" subscription use and (b) from 2026-06-15 draws a separate paid Agent SDK
credit pool rather than the Pro subscription. Do NOT add timers, daemons, or
background threads that call `ask_cc()`. (An earlier hourly Gmail loop was removed for
exactly this reason.) Mail is on-demand via the `/mail` skill.

## No metered path — important

This project deliberately has **no `ANTHROPIC_API_KEY` dependency**. `ask_cc()`
builds a clean subprocess environment with the key stripped out, so Claude Code
always falls back to the OAuth/Pro session rather than billing API credits. Do
not reintroduce an API-key path, a spend cap, or a usage/token spend log — those
were removed on purpose. The only invocation record kept is `cc_calls.jsonl`
(a count of CC calls, no token data).

## Skills

Capability lives in `skills/*.md` — markdown recipes, not code. The gateway stays
static; adding a capability = drop a file + restart, never edit `route()`.

- `load_skills()` (called in `main()`) indexes `skills/*.md` at boot reading ONLY
  front matter (first 4 KB). Bodies are never read at boot.
- `run_skill()` loads a body on demand when a trigger fires — progressive disclosure,
  so skills don't crowd Qwen's 8k context at rest.
- Front matter: `name`, `description`, `exposes` (`local` | `cc` | `both`),
  `trigger` (e.g. `/health`), `locked` (`true` → must be listed in `skills.allow`),
  `source`. v1 is explicit-trigger only (`match_skill_trigger()` matches the first
  whitespace token); text after the trigger is passed through as freeform input.
  Model-selection from descriptions is the planned v2.
- Lock: `skills.allow` (one name per line, `#` comments) arms `locked: true` skills.
  Boot logs `[skills] loaded …` and `[skills] blocked …`.
- Shipped: `system-health` (local, unlocked), `mail` (cc, locked, armed, read-only),
  `blog-post` (cc, locked, NOT armed by default).

## Key constants (top of greenclaw.py)

| Var | Value | Purpose |
|-----|-------|---------|
| `LOCAL_MODEL` | `qwen2.5:3b-instruct` | Ollama model (the Qwen-first local path) |
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Local Ollama endpoint |
| `LOCAL_NUM_CTX` | `8192` | Ollama context window |
| `LOCAL_MAX_STEPS` | `8` | Max tool-call loop iterations for the local model |
| `SHELL_MAX_OUTPUT` | `6000` | Char cap on `run_shell` output (head+tail via `_truncate`) |
| `SKILLS_DIR` | `<dir>/skills` | Where skill recipes live |
| `SKILLS_ALLOW` | `<dir>/skills.allow` | Arms `locked` skills |
| `SKILL_BODY_WARN` | `6000` | Warn (don't refuse) if a local skill body is large for Qwen |
| `NOTES_FILE` | `~/notes.md` | Where `add_note`/`list_notes` read and write |
| `CC_LOG_FILE` | `~/greenclaw/cc_calls.jsonl` | CC invocation log (count only) |
| `CC_BIN` | `claude` on PATH, else `~/.local/bin/claude` | Claude Code CLI binary |

The Claude Code model (`claude-sonnet-4-6`) is currently passed inline in
`ask_cc()` via the `--model` flag, not a named constant. If it needs to change
in more than one place later, promote it to a constant then.

## Tools

`run_shell`, `add_note`, and `list_notes` are defined in the `TOOLS` list and
dispatched by `dispatch_tool()`. The local model additionally gets `delegate_to_cc`
(added in `_ollama_tools()`), which lets the local model hand a task to Claude Code
for anything needing external reach it lacks (Gmail, web, GitHub, APIs). This is the
escalation path the Qwen-first default relies on.

## Adding a feature

**Most things: write a skill, not code.** Add `skills/<name>.md` with front matter and
a recipe body, arm it in `skills.allow` if `locked`, restart. No code change.

**New top-level prefix/command** (rare) — add a branch in `route()` before the final
`converse_local(text)` default:
```python
if text.startswith("/weather"):
    location = text[len("/weather"):].strip() or "London"
    return get_weather(location)  # implement above route()
```

**New tool for the local model** — add the schema to the `TOOLS` list (and, if it's
local-only, to `_ollama_tools()`), then handle it in `dispatch_tool()`.

## Running / restarting

```bash
# Check running
systemctl --user status greenclaw-bot.service

# Restart (do this after any code OR skill change)
systemctl --user restart greenclaw-bot.service

# Logs (watch the [skills] boot lines)
journalctl --user -u greenclaw-bot.service -f
```

## Files

| File | Purpose |
|------|---------|
| `greenclaw.py` | The gateway — single file, intentional |
| `skills/` | Skill recipes (`*.md`) — add capabilities here, no code |
| `skills.allow` | Arms `locked` skills — one name per line |
| `.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (no API key) |
| `cc_calls.jsonl` | Claude Code invocation log (count only) |
| `~/notes.md` | Persistent notes written via `add_note` |

## Rules

- Keep it single-file. No new modules without good reason.
- Prefer a skill over code. Only edit `route()` for genuinely new top-level routing.
- No metered/API-key path. OAuth only. (See "No metered path".)
- Nothing on a timer. No scheduled/background CC calls. (See "Nothing runs on a timer".)
- No features beyond what the user asks for.
- Test by restarting the service and sending a Telegram message.
- Confirm before anything destructive.
- Lean and auditable over clever.
