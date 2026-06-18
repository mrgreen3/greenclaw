---
type: Index
title: Services Index
description: External services and APIs that greenclaw integrates with.
---

Services are external platforms, APIs, or backends that greenclaw consumes or produces to. Each service has specific authentication, configuration, and behavior.

## Inference services

Primary paths for reasoning and code generation:

- [claude-code-cli](claude-code-cli.md) — Claude Code CLI (`claude` command); primary inference path
- [gemini](gemini.md) — Google Gemini 2.5 Flash; free secondary/fallback path

## Communication services

Input/output channels:

- [telegram](telegram.md) — Telegram Bot API; primary user interface

## Data services

Not documented yet but used:

- GitHub API — fetch open issues (for dashboard)
- wttr.in — weather lookups
- Google AI Studio — Gemini API endpoint

## Routing and fallbacks

Greenclaw's `converse()` function routes messages to inference services in this order:

1. **Prefix-based routing**:
   - `gg <query>` → Gemini (forced)
   - `cc <query>` → Claude Code CLI (forced)
   - `/<trigger>` → Skill recipe (local)

2. **Default fallback chain**:
   - Claude Code CLI (if `ANTHROPIC_API_KEY` set)
   - Gemini (if `GEMINI_API_KEY` set)
   - Error message (if no inference service configured)

## Configuration summary

All service configuration is in `.env`:

| Service | Config variables |
|---------|------------------|
| Claude Code CLI | `ANTHROPIC_API_KEY`, `MODEL` (in code) |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Dashboard | `DASHBOARD_PORT`, `DASHBOARD_HOST`, `GITHUB_TOKEN` |

## See also

- [[tasks]] — Always-on connectors that use these services
- [[config]] — Configuration and environment setup
