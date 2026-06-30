# Cloud Model Fallback Chain — Design Spec

Issue: #35 — Add cloud-model fallback chain + Telegram failure notification.
Refined scope: remove Gemini + its API key; wire `glm-5.2:cloud` as the primary
cloud model managing Telegram `gg` and email routes; add `kimi-k2.7-code:cloud`
as a secondary cloud model; auto-escalate to Claude Code on cloud-tier exhaustion
and notify the user over Telegram.

Date: 2026-06-30

## 1. Goal

Replace the Gemini REST integration with an Ollama-Cloud-backed tier. The cloud
tier serves the routes Gemini served (Telegram `gg`, email, `gg`-exposed skills,
scheduled skill+note jobs) with full tool calling. A two-model fallback chain
keeps the tier available when one cloud model errors, and Claude Code remains the
final backstop, with Telegram notifications on every degradation.

Non-goals: quality/truncation sanity checks, per-model usage-level ordering
research, dashboard display of cloud calls, changing the local-Qwen CC-fallback
path or the `cc` prefix route.

## 2. Architecture

Single-file gateway preserved. All changes live in `greenclaw.py` plus
`.env.example`. No task files change.

Two new units replace `converse_gemini`:

- **`call_cloud_model(model, messages, tools)`** — primitive. One Ollama
  `/api/chat` call (`stream: false`). Returns `(text, tool_calls)` or raises a
  typed `CloudCallError(reason, status)`. Owns the HTTP boundary only.
- **`converse_cloud(text, system_extra=None, chat_id=None, allow_shell=True)`** —
  orchestrator. Owns the chain, the tool-calling loop, the `allow_shell` gate,
  per-chat rolling history, Telegram notify, and CC escalation. Calls
  `call_cloud_model` once per chain step per loop step.

Both reuse existing `_ensure_ollama` and `dispatch_tool`. `call_cloud_model` is
isolated and testable without the chain; `converse_cloud` is the only consumer of
the chain/notify/escalation logic.

## 3. Fallback Chain

```
CLOUD_CHAIN = [GC_CLOUD_MODEL, GC_CLOUD_FALLBACK]
```

Env-overridable; defaults `glm-5.2:cloud`, `kimi-k2.7-code:cloud`.

`converse_cloud` tries the primary for the full tool loop. On a hard failure
(`CloudCallError`) it restarts the loop on the next model in the chain, carrying
the same input/history. On each successful fallback it sends a Telegram
notification: `cloud fallback: <primary> failed → <secondary>`. On full
exhaustion (every model in the chain raised `CloudCallError`) it sends an urgent
notification: `cloud tier exhausted: <chain>` and returns
`ask_cc(text, chat_id=chat_id)` — auto-escalation, no user prompt required.

Failure criteria v1 = hard errors only: connection refused, read timeout, HTTP
5xx, 502, EOF/truncated body, non-2xx status. No content-quality or
truncation-detection check. A model that returns malformed-but-2xx output is
treated as success.

## 4. `call_cloud_model` Primitive

```
POST {OLLAMA_URL}/api/chat
{
  "model": <model>,
  "messages": <messages>,
  "tools": <tools or []>,
  "stream": false,
  "options": {"num_ctx": 40960}
}
```

- httpx client, 120s timeout.
- Non-2xx → `CloudCallError("http", status)`.
- Connection error / read timeout / EOF → `CloudCallError("transport", None)`.
- On 2xx: parse `message.content` and `message.tool_calls`; return
  `(content, tool_calls)`. A 2xx response with no content and no tool calls is a
  valid (empty) reply, not an error.

`num_ctx` raised to 40960 to mitigate the known cloud tool-call parsing/truncation
issue on large contexts.

## 5. Tool Set and Loop

`_cloud_tools(allow_shell)` builds Ollama-format tool definitions
`{"type":"function","function":{"name","description","parameters"}}` from the
existing `TOOLS` list plus `delegate_to_cc`, filtering `run_shell` out when
`allow_shell=False`. This carries the S4 email hardening forward: the email path
calls `converse_cloud(..., allow_shell=False)`.

Loop bound: `CLOUD_MAX_STEPS = 8`. Each iteration: call the current chain model
through `call_cloud_model`; if `tool_calls` present, dispatch each via
`dispatch_tool`, append tool results, continue; if text only, return it. A loop
that hits the step bound returns the last text (or a short note if none), not an
error.

The chain index resets to 0 at the start of each `converse_cloud` call. On
mid-loop `CloudCallError`, the orchestrator restarts the loop from step 0 on the
next chain model, reusing the original input + rolling history (not the partial
in-flight tool transcript, which may be inconsistent).

## 6. `notify_telegram` Helper

Module-level `notify_telegram(text)`:

- Uses `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.
- Best-effort: catches all exceptions, never raises. A notification failure must
  not kill the dispatch thread or mask the original result.
- The existing scheduler `_sched_reply` path is refactored to call
  `notify_telegram` so there is one Telegram-send helper.

## 7. Concurrency Cap

`threading.Semaphore(3)` (`CLOUD_SEMAPHORE`) acquired around each
`call_cloud_model` call. Honors Ollama Cloud's 3-concurrent-model limit: a 4th
concurrent cloud call blocks until a slot frees, instead of triggering a 429 that
would surface as a spurious fallback. The semaphore is held across the single
HTTP call only, not the whole tool loop.

## 8. Removal of Gemini

Delete: `converse_gemini`, `_gemini_tools`, `GEMINI_MODEL`, `GEMINI_MAX_STEPS`,
all `GOOGLE_API_KEY` reads, the Gemini REST call site, the `x-goog-api-key`
header.

Rewire callers to `converse_cloud`:
- `route()`: email detection branch (`text.startswith("[email subject:")`) →
  `converse_cloud(text, chat_id=chat_id, allow_shell=False)`.
- `route()`: `gg ` prefix → `converse_cloud(text, chat_id=chat_id)` (full tools).
- `run_skill`: `exposes=gg` → `converse_cloud`.
- `_run_schedule`: skill+note path → `converse_cloud`.

`converse_local_ondemand` (local Qwen, the CC-fallback path under the default
no-prefix route) is unchanged. `ask_cc` is unchanged apart from being the
escalation target.

`_build_system`: drop "small local model" wording; describe the cloud tier as the
"first-responder model" for the routes it serves, with CC as backstop.

`.env.example`: remove `GOOGLE_API_KEY` (currently absent from the example but
referenced in code — verify and remove any remaining reference); add
`GC_CLOUD_MODEL=glm-5.2:cloud` and `GC_CLOUD_FALLBACK=kimi-k2.7-code:cloud`.

## 9. Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `GC_CLOUD_MODEL` | `glm-5.2:cloud` | primary cloud model |
| `GC_CLOUD_FALLBACK` | `kimi-k2.7-code:cloud` | secondary cloud model |
| `OLLAMA_URL` | `http://localhost:11434` | unchanged |
| `OLLAMA_MODEL` | `qwen3:8b` | unchanged (local Qwen path) |

Removed: `GEMINI_MODEL`, `GOOGLE_API_KEY`.

## 10. Testing

Compile check: `python -m py_compile greenclaw.py`.

Smoke (run on the box, not the laptop — requires box `ollama` signed into Cloud):
- Trivial prompt through `converse_cloud`; expect a plain reply from
  `glm-5.2:cloud`.
- Force fallback: set `GC_CLOUD_MODEL` to a bogus tag; expect
  `CloudCallError` → `kimi-k2.7-code:cloud` serves the reply → Telegram
  `cloud fallback: …` notification.
- Force exhaustion: bogus `GC_CLOUD_MODEL` + bogus `GC_CLOUD_FALLBACK`; expect
  urgent `cloud tier exhausted: …` notification + CC escalation reply.
- Email path: send a trusted email; expect `converse_cloud(allow_shell=False)`
  and no `run_shell` in the tool set.
- Telegram `gg` prefix: expect full tools including `run_shell`.
- Concurrency: not unit-tested; documented as semaphore-protected.

Pre-flight on the box: verify `ollama` is signed into ollama.com and that both
`glm-5.2:cloud` and `kimi-k2.7-code:cloud` resolve in the local registry before
declaring the change shipped.

## 11. Files Touched

- `greenclaw.py` — bulk of the work.
- `.env.example` — drop Gemini key, add `GC_CLOUD_MODEL` / `GC_CLOUD_FALLBACK`.
- `docs/superpowers/specs/2026-06-30-cloud-fallback-chain-design.md` — this spec.

## 12. Rollout

Feature branch + PR (push to default branch is blocked). Merge on the box, pull,
restart the systemd user service, confirm alive — same flow as PR #36.