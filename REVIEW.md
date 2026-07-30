# GreenClaw Code Review

Date: 2026-07-30
Reviewer: Hermes Agent
Scope: Full codebase audit of mrgreen3/greenclaw@1a5507d

---

## 1. Security

### S1. Blog post email bypasses the restricted-cloud path
**File:** greenclaw.py, lines 1640-1648 (route())

When an email arrives with subject "blog: ..." or "post: ...", `handle_blog_post_email()` runs BEFORE the `allow_shell=False` cloud path. This function calls `create_blog_post()` which writes files to `~/blog/content/posts/` and runs `git add`, `git commit`, and `deploy.sh` — all from email input. The code acknowledges From: header spoofing (no SPF/DKIM) and withholds `run_shell` from the regular email cloud path, but the blog path has no such restriction. A spoofed email from a trusted address could write arbitrary markdown and trigger a deploy.

**Fix:** Either (a) require the `EMAIL_CC_KEYWORD` for blog posts too, or (b) move the blog check after the keyword/restricted-cloud decision so unkeyworded blog emails go through the restricted path, or (c) add a separate `BLOG_ALLOWED_SENDERS` list.

### S2. Hardcoded memory path with username
**File:** greenclaw.py line 65, dashboard.py line 40

```python
MEMORY_DIR = os.path.expanduser("~/.claude/projects/-home-mrgreen/memory")
```

This path is hardcoded to `-home-mrgreen`. If the username differs (another user, or a different machine), memory silently doesn't load — `_load_memory_from_disk` returns `""`. The `CC_WORKDIR` in github_inbox.py also hardcodes `~/greenclaw`.

**Fix:** Derive from the actual home directory dynamically:
```python
MEMORY_DIR = os.path.expanduser(f"~/.claude/projects/-home-{os.environ.get('USER', 'mrgreen')}/memory")
```
Or make it configurable: `GC_MEMORY_DIR` env var with the current path as default.

### S3. Dashboard token accepted via query string
**File:** dashboard.py line 693

```python
qtok = (parse_qs(parsed.query).get("token") or [""])[0]
```

Tokens in URLs are logged by reverse proxies, browser history, and Referer headers. The `?token=` path exists for convenience but undermines the security the token gate provides.

**Fix:** Remove the query-string token path; accept only the Authorization header. If a URL-accessible token is needed for browser bookmarks, use a cookie set on first auth instead.

### S4. shell=True in system probes
**File:** greenclaw.py lines 258, 265; dashboard.py line 73

`_build_system()` and dashboard's `_run()` use `shell=True` for hardcoded commands (`grep PRETTY_NAME /etc/os-release`, `which ...`, `df -k /`, etc.). The commands are static so this isn't exploitable, but it's unnecessary and a habit worth breaking.

**Fix:** Use `subprocess.check_output(["grep", "PRETTY_NAME", "/etc/os-release"], ...)` — no shell needed.

---

## 2. Code Quality / Structure

### Q1. Duplicate service files
**Files:** greenclaw.service, greenclaw-bot.service

These two files are byte-for-byte identical. One should be deleted. The docs/paper-trading.md references `greenclaw-bot.service` while the README references `greenclaw.service` — pick one.

### Q2. Duplicate front-matter parser
**Files:** greenclaw.py line 921, dashboard.py line 240

`parse_front_matter()` and `_parse_front_matter()` are near-identical implementations. The dashboard duplicates it to avoid importing greenclaw.py (which has side effects at import time). Consider extracting to a shared `utils.py` with no side effects.

### Q3. Duplicate SMTP send logic
**Files:** tasks/email.py lines 52-84, greenclaw.py lines 1266-1326

`send_reply()` in the email task and `send_email()` in the gateway both implement SMTP sending with the same port-465-vs-587 branching. Consolidate to a single function.

### Q4. converse_local_ondemand is dead code
**File:** greenclaw.py lines 808-841

This function (local Qwen fallback) is defined but never called. `route()` falls back to `converse_cloud()` when CC fails, not to `converse_local_ondemand()`. The cheat.md references "falls back to local Qwen if CC errors" which is also wrong. Either wire it in as a second fallback or delete it.

### Q5. Redundant import in parse_blog_email
**File:** greenclaw.py lines 1048-1049

```python
import re
import re as _re
```

Two imports of the same module under different names in the same function. `re` is unused (all usage uses `_re`). Delete line 1048.

### Q6. save_memory imports from gitignored module
**File:** greenclaw.py line 457

```python
from skills.vault import write_note
```

`skills/*` is gitignored, so this always hits `ImportError` on a fresh clone and falls back to `add_note`. The fallback works but the vault path is dead code for anyone cloning the repo.

### Q7. Duplicate path constants across modules
**Files:** greenclaw.py lines 48-69, dashboard.py lines 39-47

`CC_LOG_FILE`, `MEMORY_DIR`, `NOTES_FILE`, `SCHEDULES_DIR`, `TASKS_DIR`, `MEMORY_SIZE_THRESHOLD` are all redefined in dashboard.py. If any path changes in greenclaw.py, dashboard.py silently desyncs.

**Fix:** Extract shared constants to a `config.py` that both modules import.

### Q8. GC_CLOUD_FALLBACK default doesn't match docs
**File:** greenclaw.py line 90

```python
GC_CLOUD_FALLBACK = os.environ.get("GC_CLOUD_FALLBACK", "gemma4:cloud")
```

README says `kimi-k2.7-code:cloud`, .env.example says `kimi-k2.7-code:cloud`, tests use `kimi-k2.7-code:cloud`, but the code default is `gemma4:cloud`. Anyone running without the env var gets a different fallback model than documented.

**Fix:** Change default to `"kimi-k2.7-code:cloud"`.

### Q9. paper-trade.py hardcodes config path
**File:** skills/paper-trade.py line 15

```python
ETFS_CONFIG = os.path.expanduser("~/Projects/greenclaw/etfs.json")
```

But `etfs.json` ships in the repo root. The skill should look for it relative to its own location, not in a hardcoded `~/Projects/greenclaw/` path that doesn't exist on most setups.

**Fix:**
```python
_HERE = os.path.dirname(os.path.abspath(__file__))
ETFS_CONFIG = os.path.join(_HERE, "..", "etfs.json")
```

---

## 3. Error Handling

### E1. _prune_file swallows all exceptions
**File:** greenclaw.py lines 230-241

```python
except Exception:
    pass
```

If pruning fails (permissions, disk full), the file grows silently. For heartbeat and CC log files this is low-stakes, but the pattern hides bugs.

**Fix:** At minimum log the error: `except Exception as e: print(f"[prune] {e}")`.

### E2. No retry on transient cloud failures
**File:** greenclaw.py call_cloud_model() line 625

A 429 (rate limit) or 503 (temporarily unavailable) from the cloud model immediately raises `CloudCallError("http", 429)` and triggers a fallback to the next model in the chain. For transient errors, a brief retry-with-backoff on the same model would be cheaper than switching models.

**Fix:** Retry once after 2-3 seconds for 429/503/502 before falling through the chain.

### E3. Telegram poll loop has no escalating backoff
**File:** tasks/telegram.py lines 61-63

On persistent errors (revoked token, network down), the loop prints the same error every 5 seconds forever. systemd journal will accumulate thousands of identical messages.

**Fix:** Exponential backoff (5s, 10s, 20s, ... capped at 60s) and log "still failing" only on interval changes.

### E4. Dashboard _run silently returns empty string on failure
**File:** dashboard.py line 75

```python
except Exception:
    return ""
```

If a system command fails, the dashboard shows a blank value with no indication something went wrong. Distinguish "command returned empty" from "command failed".

---

## 4. Testing

### T1. No tests for critical parsers
**File:** tests/test_cloud.py

The test file covers cloud model calls, tools, and the cloud fallback chain well. But several critical pure functions have zero tests:
- `parse_front_matter()` — used by skills, schedules, and dashboard
- `_parse_days()` — schedule day parsing with ranges (mon-fri) and lists (mon,wed,fri)
- `match_skill_trigger()` — trigger matching
- `save_history()` / `load_history()` — persistence with TTL pruning
- `handle_blog_post_email()` / `parse_blog_email()` — email-to-blog parsing
- `route()` for static commands (`/cheat`, `/version`, `/model`, `/memory`, `/inbox on|off`, `/regreen`, `remember`)

**Fix:** Add a `test_parsers.py` and `test_routing.py` covering these. The audit checklist has a template for this.

### T2. No CI pipeline
No `.github/workflows/` directory exists. Tests only run if someone remembers to run them locally.

**Fix:** Add a minimal GitHub Actions workflow that runs `python -m pytest tests/` or `python tests/test_cloud.py` on push.

---

## 5. Documentation

### D1. README routing table is stale
**File:** README.md lines 25-32

Missing routes that exist in code:
- `/model` / `model` — show cloud model info (line 1609)
- `/memory` / `memory stats` — memory vault stats (line 1615)
- `/inbox on` / `/inbox off` — toggle GitHub inbox watcher (lines 1617-1624)
- `/regreen` — restart the bot (line 1625)
- `/watch` — scheduled jobs (line 1613, also missing from table but in cheat.md)
- `remember <text>` — save to memory (line 1633)
- `version` (without `/` prefix) — also works (line 1607)

### D2. README "Single Python file" claim is stale
**File:** README.md line 9

> Single Python file. Lean, auditable, yours.

The project is now 5 Python files (greenclaw.py + 4 task modules) + 1 Python skill + 1 test file + 747-line dashboard with embedded HTML/CSS. The single-file philosophy is visible in the gateway itself, but the claim is misleading for the project as a whole.

**Fix:** "Single-file gateway. Task connectors and skills drop in alongside."

### D3. README .env section is incomplete
**File:** README.md lines 168-173

Shows only `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GC_CLOUD_MODEL`, `GC_CLOUD_FALLBACK`. Missing all the env vars the code actually reads:
- `GC_CC_MODEL` (line 93)
- `EMAIL_IMAP_HOST`, `EMAIL_IMAP_PORT`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_TRUSTED_SENDERS` (email task)
- `EMAIL_CC_KEYWORD` (line 1654 — also missing from .env.example)
- `DASHBOARD_PORT`, `DASHBOARD_HOST`, `DASHBOARD_TOKEN`, `DASHBOARD_ENABLED` (dashboard task)
- `GITHUB_TOKEN`, `GITHUB_REPO` (dashboard + github_inbox)
- `ALPHA_VANTAGE_API_KEY` (paper-trade skill)
- `OLLAMA_MODEL` (line 86)
- `GREENCLAW_GH_TOKEN` (github_inbox task)

### D4. README Files table is stale
**File:** README.md lines 211-220

Missing: `tasks/email.py`, `tasks/github_inbox.py`, `tasks/dashboard.py`, `tests/test_cloud.py`, `etfs.json`, `schedules/`, `docs/`, `greenclaw-bot.service` (or `greenclaw.service`).

### D5. README "Nothing runs on a timer" is contradicted by the scheduler
**File:** README.md line 132

> Nothing runs on a timer: GreenClaw never wakes the cloud model on a schedule.

But the scheduler section (lines 1348-1545) and `schedules/paper-trade.md` implement exactly this — a 16:30 UTC weekday schedule that runs the paper-trade skill. The README even has a `/watch` command to view schedules.

**Fix:** Soften to "Nothing runs on a timer by default" or "Schedules are opt-in — GreenClaw never wakes the cloud model unless you add a schedule."

### D6. README "history cleared on restart" is stale
**File:** README.md line 243

> Per-chat rolling history — the last 10 exchanges per conversation are preserved; context survives within a session (in-memory; cleared on restart — see #7)

But `load_history()` (line 106) loads from `~/.local/share/greenclaw/history.json` on boot, and `save_history()` (line 130) persists after every message. History survives restarts with a 7-day TTL. The README contradicts the code.

### D7. cheat.md says "falls back to local Qwen" — wrong
**File:** static/cheat.md line 4

> (no prefix)   Claude Code; falls back to local Qwen if CC errors

`route()` (line 1664-1666) falls back to `converse_cloud()` (cloud model), not local Qwen. `converse_local_ondemand()` is dead code.

### D8. cheat.md missing commands
**File:** static/cheat.md

Missing `/model`, `/memory`, `remember <text>`, and `version` (without `/`) — all exist in `route()`.

### D9. .env.example missing EMAIL_CC_KEYWORD
**File:** .env.example

`EMAIL_CC_KEYWORD` is read by `route()` (line 1654) but not listed in `.env.example`. Users won't know it exists.

### D10. README install says `pip install httpx` but requirements.txt has 30 packages
**File:** README.md line 162

> pip install httpx

But `requirements.txt` includes httpx, beautifulsoup4, pandas, numpy, yfinance, peewee, websockets, rich, etc. New users who follow the README will be missing dependencies.

**Fix:** `pip install -r requirements.txt` (or split into `requirements-core.txt` and `requirements-extra.txt`).

### D11. docs/paper-trading.md references wrong service name
**File:** docs/paper-trading.md line 23

> systemctl --user restart greenclaw-bot.service

But README says `greenclaw.service`. With two identical service files, this is confusing. Pick one name and use it everywhere.

---

## 6. Project Hygiene

### H1. .gitignore over-ignores skills/ and schedules/
**File:** .gitignore lines 12-13

```
skills/*
schedules/*
!skills/paper-trade.py
!schedules/paper-trade.md
```

No example `.md` skill ships. The README references `blog-post` and `system-health` skills but they don't exist in the repo. New users have nothing to copy from.

**Fix:** Ship `skills/example.md` (or `skills/example-skill.md`) as a template, and add `!skills/example.md` to .gitignore exceptions. Same for schedules.

### H2. No LICENSE mention in README
The LICENSE file exists (MIT) but README never mentions it. Convention is to state the license near the end.

### H3. docs/ has design specs but no CONTRIBUTING.md or issue templates
For a public repo, a CONTRIBUTING.md (even a short one) and issue templates help structure outside contributions. Low priority for a personal project.

---

## 7. Enhancements

### N1. No structured logging
Everything uses `print()`. For a systemd service, Python's `logging` module gives log levels, timestamps (via journald), and filtering (`journalctl --user -u greenclaw -p err`). The `[tag]` prefix convention is a partial substitute but doesn't support level filtering.

### N2. No graceful shutdown
**File:** greenclaw.py main() line 1761

No SIGTERM handler. systemd sends SIGTERM on stop/restart, which kills in-flight CC calls (up to 15 min) and their results. A handler could save state, finish current messages, and shut down cleanly.

```python
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
```

### N3. save_history does a full JSON dump per message
**File:** greenclaw.py save_history() line 130

Every message triggers a full read-modify-write of the entire history file. For 10 chats this is fine, but an append-only JSONL per chat would scale better if the project grows.

### N4. Email task polls every 30s — IMAP IDLE would be more efficient
**File:** tasks/email.py line 212

IMAP IDLE (RFC 2177) pushes new messages instantly without polling. For a sole-user box on a private network, 30s polling is fine, but IDLE is the "green" option — fewer connections, instant responses.

### N5. Dashboard uses full-page refresh
**File:** dashboard.py line 639

`<meta http-equiv="refresh" content="30">` reloads the entire page every 30s. Server-Sent Events (SSE) or a simple `/api/json` endpoint with client-side fetch would be smoother and use less bandwidth.

### N6. Memory compaction is fire-and-forget
**File:** greenclaw.py _check_memory_threshold() line 201

`ask_cc()` is called to compact memory, but the result isn't checked. If CC fails to compact (or compacts badly), there's no feedback. The compaction state is marked as done regardless of whether `ask_cc` succeeded.

---

## 8. Quick Wins (easy, high-value fixes)

| # | Fix | Effort |
|---|-----|--------|
| 1 | Delete `greenclaw-bot.service` (duplicate of `greenclaw.service`) | 1 min |
| 2 | Fix `GC_CLOUD_FALLBACK` default: `gemma4:cloud` → `kimi-k2.7-code:cloud` | 1 min |
| 3 | Fix `etfs.json` path in `paper-trade.py` to use repo-relative path | 2 min |
| 4 | Delete duplicate `import re` in `parse_blog_email` | 1 min |
| 5 | Update README routing table with missing commands | 5 min |
| 6 | Update README Files table with missing files | 5 min |
| 7 | Fix "Nothing runs on a timer" claim in README | 2 min |
| 8 | Fix "falls back to local Qwen" in cheat.md → "falls back to cloud model" | 1 min |
| 9 | Add `EMAIL_CC_KEYWORD` to `.env.example` | 1 min |
| 10 | Change `pip install httpx` → `pip install -r requirements.txt` in README | 1 min |
| 11 | Fix "history cleared on restart" in README → "persists with 7-day TTL" | 2 min |
| 12 | Add "Single-file gateway" instead of "Single Python file" in README | 1 min |
| 13 | Ship `skills/example.md` template + un-ignore it | 5 min |
| 14 | Add `.env.example` entries for EMAIL_*, DASHBOARD_*, GITHUB_* vars | 5 min |
| 15 | Add LICENSE mention to README | 1 min |

---

## Summary

GreenClaw is a well-architected personal AI bridge. The routing design (prefixes, skills, tasks, schedules) is clean and extensible. The security model is appropriate for a sole-user box on a private network — the code is honest about its limitations. The test suite for the cloud model layer is solid.

**Top 3 risks:**
1. Blog post email path bypasses the restricted-cloud security that the regular email path has (S1)
2. README and code have drifted significantly — routing table, env vars, files, and several claims are stale (D1-D11)
3. No CI pipeline and narrow test coverage — critical parsers and routing paths are untested (T1-T2)

**What's good:**
- Cloud fallback chain with side-effect-aware retry logic (won't re-run tools on model switch)
- Claim-before-execute pattern in github_inbox (prevents double-runs on crash)
- Secret env stripping in github_inbox (broad _TOKEN/_PASSWORD/_SECRET/_KEY suffix matching)
- Atomic file writes (tmp + os.replace) throughout
- Telegram dispatch in worker threads — poll loop never blocks
- Clean task/skill/schedule plugin architecture
- Email task handles malformed messages gracefully (mark-seen-before-parse)
- Test coverage for the cloud model layer is thorough