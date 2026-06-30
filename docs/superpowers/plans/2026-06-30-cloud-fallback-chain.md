# Cloud Model Fallback Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Gemini REST integration with an Ollama-Cloud tier (`glm-5.2:cloud` → `kimi-k2.7-code:cloud`) that owns the `gg`/email/skill/schedule routes, auto-escalates to Claude Code on exhaustion, and notifies the user over Telegram on every degradation.

**Architecture:** Two new units in `greenclaw.py`: a `call_cloud_model(model, messages, tools)` primitive (one Ollama `/api/chat` call, raises typed `CloudCallError`), and a `converse_cloud` orchestrator that owns the chain, the tool loop, the `allow_shell` gate, per-chat history, Telegram notify, and CC escalation. A module-level `notify_telegram` helper consolidates Telegram sends. All Gemini code/vars/keys are deleted; callers are rewired to `converse_cloud`.

**Tech Stack:** Python 3.11+, httpx, stdlib `unittest` (no new deps), Ollama daemon with Cloud sign-in, Claude Code CLI.

## Global Constraints

- Single-file gateway preserved — all logic stays in `greenclaw.py` unless noted.
- No new pip dependencies. Tests use stdlib `unittest` only.
- `allow_shell=False` on the email path carries the S4 hardening forward — never regress it.
- `ANTHROPIC_API_KEY` stays stripped from CC subprocess env (existing `ask_cc` behaviour).
- Env-overridable chain: `GC_CLOUD_MODEL` (default `glm-5.2:cloud`), `GC_CLOUD_FALLBACK` (default `kimi-k2.7-code:cloud`).
- Failure criteria v1 = hard errors only (connection/timeout/5xx/502/EOF/non-2xx). No content-quality check.
- `CLOUD_MAX_STEPS = 8`; `CLOUD_SEMAPHORE = threading.Semaphore(3)` around each `/api/chat` call.
- Commit messages end with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Push to default branch is blocked — work on a feature branch off `main`, open a PR.
- Secrets live in `.env` (gitignored). Never read or print `.env` values. The engineer edits secrets themselves.
- Builds and smoke tests run on the box (the Lenovo M920q), not the laptop. The laptop is for editing/git only.

---

## File Structure

- **`greenclaw.py`** (modify) — the gateway. Add `CloudCallError`, `call_cloud_model`, `_cloud_tools`, `_cloud_tool_loop`, `converse_cloud`, `notify_telegram`, `CLOUD_*` constants; delete `converse_gemini`, `_gemini_tools`, `GEMINI_*`, all `GOOGLE_API_KEY` reads; rewire `route()`, `run_skill()`, `_run_schedule()`; tweak `_build_system()` and the module docstring; refactor `_sched_reply` onto `notify_telegram`.
- **`tests/test_cloud.py`** (create) — stdlib `unittest` suite for the new units. Monkeypatches module globals (`greenclaw.httpx`, `greenclaw.call_cloud_model`, `greenclaw.dispatch_tool`, `greenclaw.ask_cc`, `greenclaw.notify_telegram`, `greenclaw._ensure_ollama`) so no real Ollama/CC/Telegram is needed.
- **`.env.example`** (modify) — add `GC_CLOUD_MODEL` / `GC_CLOUD_FALLBACK`; Gemini key is already absent, confirm no reference remains.
- **`README.md`** (modify) — replace the Google AI Studio prereq + `GOOGLE_API_KEY` line with the Ollama Cloud prereq + new env vars.
- **`static/cheat.md`** (modify) — `gg` line describes the cloud tier, not Gemini.

No task files (`tasks/*.py`) change.

---

### Task 1: `notify_telegram` helper + consolidate scheduler send

**Files:**
- Modify: `greenclaw.py` (add `notify_telegram` near the top-level helpers, after `send_email`; refactor `_sched_reply` inside `start_tasks`)
- Test: `tests/test_cloud.py` (create)

**Interfaces:**
- Consumes: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` env vars; `httpx`.
- Produces: `notify_telegram(text: str) -> None` — best-effort Telegram send, 4000-char chunking, never raises. Used by Task 4 and the scheduler.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cloud.py`:

```python
import importlib.util
import os
import sys
import unittest
from pathlib import Path

# Load greenclaw.py as a module without importing it as a package.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
spec = importlib.util.spec_from_file_location("greenclaw", _ROOT / "greenclaw.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class NotifyTelegramTests(unittest.TestCase):
    def setUp(self):
        self._posts = []
        def fake_post(url, json=None, timeout=None, **kw):
            self._posts.append({"url": url, "json": json})
            return FakeResponse(200, {"ok": True})
        gc.httpx.post = fake_post
        os.environ["TELEGRAM_BOT_TOKEN"] = "tok"
        os.environ["TELEGRAM_CHAT_ID"] = "123"

    def test_sends_chunked_message(self):
        text = "x" * 5000  # spans two 4000-char chunks
        gc.notify_telegram(text)
        self.assertEqual(len(self._posts), 2)
        self.assertEqual(self._posts[0]["json"]["chat_id"], "123")
        self.assertTrue(self._posts[0]["json"]["text"])
        self.assertTrue(self._posts[1]["json"]["text"])

    def test_never_raises_on_http_error(self):
        def boom(url, json=None, timeout=None, **kw):
            raise RuntimeError("network down")
        gc.httpx.post = boom
        # Must not raise.
        gc.notify_telegram("hello")

    def test_noop_without_credentials(self):
        del os.environ["TELEGRAM_BOT_TOKEN"]
        gc.notify_telegram("hello")
        self.assertEqual(self._posts, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cloud -v`
Expected: FAIL with `AttributeError: module 'greenclaw' has no attribute 'notify_telegram'` (or import error).

- [ ] **Step 3: Write minimal implementation**

In `greenclaw.py`, add this function immediately after the `send_email` function (after the `# END SCHEDULER` block is fine, but placing it right after `send_email` keeps the email/notify utilities together — pick the spot after `send_email`'s final line):

```python
def notify_telegram(text):
    """Best-effort Telegram send to the owner's chat. Chunks to 4000 chars.
    Never raises — a notification failure must not kill the dispatch thread
    or mask the result it was reporting on."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        for i in range(0, len(text), 4000):
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[i:i + 4000]},
                timeout=30,
            )
    except Exception as e:  # noqa: BLE001
        print(f"[notify] telegram send error: {e}")
```

Then refactor `_sched_reply` inside `start_tasks` to delegate. Replace the existing `_sched_reply` definition:

```python
        def _sched_reply(text):
            try:
                for i in range(0, len(text), 4000):
                    httpx.post(
                        f"https://api.telegram.org/bot{_tg_token}/sendMessage",
                        json={"chat_id": _tg_chat, "text": text[i:i + 4000]},
                        timeout=30,
                    )
            except Exception as e:  # noqa: BLE001
                print(f"[scheduler] telegram send error: {e}")
```

with:

```python
        def _sched_reply(text):
            notify_telegram(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cloud.NotifyTelegramTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add greenclaw.py tests/test_cloud.py
git commit -m "Add notify_telegram helper, consolidate scheduler send

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `CloudCallError` + `call_cloud_model` primitive

**Files:**
- Modify: `greenclaw.py` (add `CloudCallError` class and `call_cloud_model` function; add `CLOUD_SEMAPHORE` constant)
- Test: `tests/test_cloud.py` (append a test class)

**Interfaces:**
- Consumes: `OLLAMA_URL`, `httpx`, `CLOUD_SEMAPHORE`.
- Produces:
  - `class CloudCallError(Exception)` — `.__init__(self, reason: str, status=None)`; stores `.reason` and `.status`.
  - `call_cloud_model(model: str, messages: list, tools: list) -> tuple[str, list]` — one Ollama `/api/chat` call. Returns `(content_text, tool_calls)` where `tool_calls` is a list of `{"name": str, "arguments": dict}` (normalized from Ollama's `{"function": {...}}` shape). Raises `CloudCallError("http", status)` on non-2xx, `CloudCallError("transport", None)` on connection/timeout/EOF.
  - `CLOUD_SEMAPHORE = threading.Semaphore(3)` — module-level.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cloud.py` (before the `if __name__` guard):

```python
class CallCloudModelTests(unittest.TestCase):
    def setUp(self):
        self._posts = []
        def fake_post(url, json=None, timeout=None, **kw):
            self._posts.append({"url": url, "json": json})
            resp = self._next_response
            self._next_response = FakeResponse(200, {"message": {"content": "", "tool_calls": []}})
            if isinstance(resp, Exception):
                raise resp
            return resp
        gc.httpx.post = fake_post
        self._next_response = FakeResponse(200, {"message": {"content": "", "tool_calls": []}})

    def _ollama_reply(self, content="", tool_calls=None):
        return FakeResponse(200, {"message": {"content": content, "tool_calls": tool_calls or []}})

    def test_returns_text_and_normalized_tool_calls(self):
        self._next_response = self._ollama_reply(
            content="hello",
            tool_calls=[{"function": {"name": "run_shell", "arguments": {"command": "ls"}}}],
        )
        content, tcs = gc.call_cloud_model("glm-5.2:cloud", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(content, "hello")
        self.assertEqual(tcs, [{"name": "run_shell", "arguments": {"command": "ls"}}])

    def test_empty_2xx_is_valid_empty_reply(self):
        self._next_response = self._ollama_reply(content="", tool_calls=[])
        content, tcs = gc.call_cloud_model("m", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(content, "")
        self.assertEqual(tcs, [])

    def test_non_2xx_raises_http_error(self):
        self._next_response = FakeResponse(502, {})
        with self.assertRaises(gc.CloudCallError) as cm:
            gc.call_cloud_model("m", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(cm.exception.reason, "http")
        self.assertEqual(cm.exception.status, 502)

    def test_connection_error_raises_transport(self):
        self._next_response = RuntimeError("connection refused")
        with self.assertRaises(gc.CloudCallError) as cm:
            gc.call_cloud_model("m", [{"role": "user", "content": "hi"}], [])
        self.assertEqual(cm.exception.reason, "transport")

    def test_sends_num_ctx_options(self):
        self._next_response = self._ollama_reply(content="ok")
        gc.call_cloud_model("m", [{"role": "user", "content": "hi"}], [])
        payload = self._posts[0]["json"]
        self.assertEqual(payload["model"], "m")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["num_ctx"], 40960)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cloud.CallCloudModelTests -v`
Expected: FAIL with `AttributeError: module 'greenclaw' has no attribute 'call_cloud_model'` / `CloudCallError`.

- [ ] **Step 3: Write minimal implementation**

In `greenclaw.py`, add the constant near the other Ollama constants (after `OLLAMA_IDLE_TIMEOUT`):

```python
CLOUD_SEMAPHORE = threading.Semaphore(3)  # Ollama Cloud: 3 concurrent models
```

Add the class and primitive after `_ensure_ollama` (before `converse_local_ondemand`):

```python
class CloudCallError(Exception):
    """Hard failure from a cloud model call (transport or non-2xx)."""
    def __init__(self, reason, status=None):
        super().__init__(f"{reason}:{status}")
        self.reason = reason
        self.status = status


def call_cloud_model(model, messages, tools):
    """One Ollama /api/chat call to a cloud model. Returns (content, tool_calls).

    tool_calls are normalized to [{"name": str, "arguments": dict}].
    Raises CloudCallError("http", status) on non-2xx, CloudCallError("transport")
    on connection/timeout/EOF. A 2xx reply with no content and no tool calls is
    a valid empty reply, not an error. num_ctx is raised to mitigate the known
    cloud tool-call parsing/truncation issue on large contexts.
    """
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": {"num_ctx": 40960},
    }
    try:
        with CLOUD_SEMAPHORE:
            r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
    except Exception as e:  # noqa: BLE001
        raise CloudCallError("transport", None) from e
    if r.status_code < 200 or r.status_code >= 300:
        raise CloudCallError("http", r.status_code)
    try:
        msg = r.json().get("message", {})
    except Exception as e:  # noqa: BLE001
        raise CloudCallError("transport", None) from e
    content = (msg.get("content") or "").strip()
    raw_calls = msg.get("tool_calls") or []
    tool_calls = []
    for tc in raw_calls:
        fn = tc.get("function") or tc
        tool_calls.append({"name": fn.get("name", ""), "arguments": fn.get("arguments") or {}})
    return content, tool_calls
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cloud.CallCloudModelTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add greenclaw.py tests/test_cloud.py
git commit -m "Add call_cloud_model primitive + CloudCallError

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `_cloud_tools(allow_shell)` builder

**Files:**
- Modify: `greenclaw.py` (add `_cloud_tools`)
- Test: `tests/test_cloud.py` (append)

**Interfaces:**
- Consumes: `TOOLS` list, `dispatch_tool` (not directly, but the tool names must match what `dispatch_tool` accepts).
- Produces: `_cloud_tools(allow_shell: bool = True) -> list` — Ollama-format tool definitions `{"type":"function","function":{"name","description","parameters"}}` from `TOOLS` plus `delegate_to_cc`, with `run_shell` withheld when `allow_shell=False`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cloud.py`:

```python
class CloudToolsTests(unittest.TestCase):
    def _names(self, tools):
        return sorted(t["function"]["name"] for t in tools)

    def test_full_tools_include_run_shell_and_delegate(self):
        names = self._names(gc._cloud_tools(allow_shell=True))
        self.assertIn("run_shell", names)
        self.assertIn("delegate_to_cc", names)
        self.assertIn("add_note", names)

    def test_no_shell_withholds_run_shell_only(self):
        names = self._names(gc._cloud_tools(allow_shell=False))
        self.assertNotIn("run_shell", names)
        self.assertIn("delegate_to_cc", names)
        self.assertIn("add_note", names)

    def test_ollama_shape(self):
        tools = gc._cloud_tools(allow_shell=True)
        for t in tools:
            self.assertEqual(t["type"], "function")
            self.assertIn("name", t["function"])
            self.assertIn("parameters", t["function"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cloud.CloudToolsTests -v`
Expected: FAIL with `AttributeError: module 'greenclaw' has no attribute '_cloud_tools'`.

- [ ] **Step 3: Write minimal implementation**

In `greenclaw.py`, add after `call_cloud_model`:

```python
def _cloud_tools(allow_shell=True):
    """Build Ollama-format tool definitions from TOOLS plus delegate_to_cc.

    When allow_shell is False (the email path, where message bodies are
    untrusted remote input), run_shell is withheld so a crafted body can't
    steer the cloud model into running shell directly. delegate_to_cc stays —
    the sender gate in tasks/email.py is the primary trust boundary there.
    """
    tools = [t for t in TOOLS if not (t["name"] == "run_shell" and not allow_shell)]
    out = [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]
    out.append({
        "type": "function",
        "function": {
            "name": "delegate_to_cc",
            "description": (
                "Delegate to Claude Code when you cannot handle a task yourself — "
                "e.g. checking email/Gmail, searching the web, or anything requiring "
                "external access you don't have. Returns Claude Code's reply."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The task or question to send to Claude Code."}},
                "required": ["query"],
            },
        },
    })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cloud.CloudToolsTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add greenclaw.py tests/test_cloud.py
git commit -m "Add _cloud_tools builder with allow_shell gate

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `_cloud_tool_loop` + `converse_cloud` orchestrator

**Files:**
- Modify: `greenclaw.py` (add `CLOUD_CHAIN`, `CLOUD_MAX_STEPS`, `GC_CLOUD_MODEL`, `GC_CLOUD_FALLBACK` constants; add `_cloud_tool_loop` and `converse_cloud`)
- Test: `tests/test_cloud.py` (append)

**Interfaces:**
- Consumes: `call_cloud_model`, `_cloud_tools`, `dispatch_tool`, `_ensure_ollama`, `notify_telegram`, `ask_cc`, `SYSTEM`, `_memory_context`, `_history`, `_history_lock`, `save_history`, `HISTORY_MAX_TURNS`, `_tz_stamp`.
- Produces: `converse_cloud(text, system_extra=None, chat_id=None, allow_shell=True) -> str` — the cloud tier entry point. Drop-in replacement for `converse_gemini` at every call site.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cloud.py`:

```python
class ConverseCloudTests(unittest.TestCase):
    def setUp(self):
        # Default chain for tests.
        gc.GC_CLOUD_MODEL = "glm-5.2:cloud"
        gc.GC_CLOUD_FALLBACK = "kimi-k2.7-code:cloud"
        gc.CLOUD_CHAIN = [gc.GC_CLOUD_MODEL, gc.GC_CLOUD_FALLBACK]
        gc._ensure_ollama = lambda: None
        gc._memory_context = ""
        gc._history.clear()

        self.calls = []       # model call sequence
        self.dispatched = []  # tool dispatches
        self.notifications = []
        self.cc_calls = []

        def fake_call(model, messages, tools):
            self.calls.append(model)
            return self._script.pop(0)
        gc.call_cloud_model = fake_call

        def fake_dispatch(name, args):
            self.dispatched.append((name, args))
            return "tool-result"
        gc.dispatch_tool = fake_dispatch

        gc.notify_telegram = lambda t: self.notifications.append(t)
        gc.ask_cc = lambda text, chat_id=None: (self.cc_calls.append(text) or "cc-reply")

    def _reply(self, content, tool_calls=None):
        return (content, tool_calls or [])

    def test_primary_serves_plain_reply(self):
        self._script = [self._reply("hello from glm")]
        out = gc.converse_cloud("hi", chat_id="42")
        self.assertEqual(out, "hello from glm")
        self.assertEqual(self.calls, ["glm-5.2:cloud"])
        self.assertEqual(self.notifications, [])
        self.assertEqual(self.cc_calls, [])

    def test_falls_back_to_secondary_and_notifies(self):
        self._script = [
            gc.CloudCallError("http", 502),     # primary fails
            self._reply("hello from kimi"),      # secondary serves
        ]
        out = gc.converse_cloud("hi")
        self.assertEqual(out, "hello from kimi")
        self.assertEqual(self.calls, ["glm-5.2:cloud", "kimi-k2.7-code:cloud"])
        self.assertEqual(len(self.notifications), 1)
        self.assertIn("cloud fallback", self.notifications[0])
        self.assertIn("glm-5.2:cloud", self.notifications[0])
        self.assertIn("kimi-k2.7-code:cloud", self.notifications[0])

    def test_exhaustion_escalates_to_cc_and_notifies_urgent(self):
        self._script = [
            gc.CloudCallError("transport", None),
            gc.CloudCallError("http", 500),
        ]
        out = gc.converse_cloud("hi", chat_id="9")
        self.assertEqual(out, "cc-reply")
        self.assertEqual(len(self.notifications), 1)
        self.assertIn("cloud tier exhausted", self.notifications[0])
        self.assertEqual(self.cc_calls, ["hi"])

    def test_tool_loop_dispatches_then_returns_text(self):
        self._script = [
            self._reply("", [{"name": "run_shell", "arguments": {"command": "ls"}}]),
            self._reply("done", []),
        ]
        out = gc.converse_cloud("list files", chat_id="1")
        self.assertEqual(out, "done")
        self.assertEqual(self.dispatched, [("run_shell", {"command": "ls"})])

    def test_email_path_withholds_run_shell(self):
        # Verify allow_shell=False reaches the tools layer by intercepting call_cloud_model.
        seen_tools = []
        def spy(model, messages, tools):
            seen_tools.append(tools)
            return ("ok", [])
        gc.call_cloud_model = spy
        gc.converse_cloud("hi", allow_shell=False)
        names = sorted(t["function"]["name"] for t in seen_tools[0])
        self.assertNotIn("run_shell", names)

    def test_history_saved_on_success(self):
        self._script = [self._reply("reply")]
        gc.converse_cloud("hi", chat_id="7")
        self.assertIn("7", gc._history)
        roles = [m["role"] for m in gc._history["7"]]
        self.assertEqual(roles, ["user", "assistant"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cloud.ConverseCloudTests -v`
Expected: FAIL with `AttributeError: module 'greenclaw' has no attribute 'converse_cloud'` / `CLOUD_CHAIN`.

- [ ] **Step 3: Write minimal implementation**

In `greenclaw.py`, add constants near the Ollama constants (after `OLLAMA_MODEL`):

```python
GC_CLOUD_MODEL = os.environ.get("GC_CLOUD_MODEL", "glm-5.2:cloud")
GC_CLOUD_FALLBACK = os.environ.get("GC_CLOUD_FALLBACK", "kimi-k2.7-code:cloud")
CLOUD_CHAIN = [GC_CLOUD_MODEL, GC_CLOUD_FALLBACK]
CLOUD_MAX_STEPS = 8
```

Add the loop helper and orchestrator after `_cloud_tools`:

```python
def _cloud_tool_loop(model, messages, tools):
    """Run the tool-calling loop for one model. Returns the final reply text.

    Works on a copy of `messages` so a mid-loop failure leaves the caller's
    transcript clean for a retry on the next chain model. Raises CloudCallError
    on any hard failure from call_cloud_model. Bounded by CLOUD_MAX_STEPS.
    """
    msgs = list(messages)
    text_parts = []
    for _ in range(CLOUD_MAX_STEPS):
        content, tool_calls = call_cloud_model(model, msgs, tools)
        if content:
            text_parts.append(content)
        if not tool_calls:
            break
        msgs.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("arguments") or {}
            preview = args.get("command") or args.get("query") or args.get("text") or ""
            print(f"  [c:{name}] {preview[:120]}")
            result = dispatch_tool(name, args)
            msgs.append({"role": "tool", "name": name, "content": str(result)})
    return "\n".join(p for p in text_parts if p.strip()) or "(no reply)"


def converse_cloud(text, system_extra=None, chat_id=None, allow_shell=True):
    """Route to the cloud tier (Ollama :cloud models) with a tool-calling loop,
    a two-model fallback chain, Telegram notify-on-fallback, and CC escalation
    on exhaustion.

    system_extra: optional skill body appended to SYSTEM for this run only.
    chat_id: if provided, rolling history is loaded before and saved after.
    allow_shell: when False, run_shell is withheld from the tool set (email path
        — untrusted remote input). delegate_to_cc stays.
    """
    try:
        _ensure_ollama()
    except Exception as e:  # noqa: BLE001
        return f"[cloud] could not start ollama: {e}"

    mem_block = f"\n\n--- long-term memory ---\n{_memory_context}" if _memory_context else ""
    system = SYSTEM + mem_block
    if system_extra:
        system = f"{system}\n\n--- skill ---\n{system_extra}"

    with _history_lock:
        stored = list(_history.get(str(chat_id), [])) if chat_id is not None else []
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in stored]
    messages.append({"role": "user", "content": f"[{_tz_stamp()}]\n{text}"})

    tools = _cloud_tools(allow_shell)

    for idx, model in enumerate(CLOUD_CHAIN):
        try:
            reply = _cloud_tool_loop(model, messages, tools)
        except CloudCallError as e:
            print(f"[cloud] {model} failed: {e.reason} ({e.status})")
            if idx < len(CLOUD_CHAIN) - 1:
                notify_telegram(f"cloud fallback: {model} failed → {CLOUD_CHAIN[idx + 1]}")
                continue
            break
        # Success — save history and return.
        if chat_id is not None:
            key = str(chat_id)
            with _history_lock:
                existing = _history.get(key, [])
                merged = existing + [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                ]
                _history[key] = merged[-(HISTORY_MAX_TURNS * 2):]
                _history_updated[key] = time.time()
            save_history(key)
        return reply

    # Chain exhausted — urgent notify + auto-escalate to Claude Code.
    notify_telegram(f"cloud tier exhausted: {' → '.join(CLOUD_CHAIN)}")
    return ask_cc(text, chat_id=chat_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cloud.ConverseCloudTests -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add greenclaw.py tests/test_cloud.py
git commit -m "Add converse_cloud orchestrator with fallback chain + CC escalation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Rewire callers + delete Gemini

**Files:**
- Modify: `greenclaw.py` (rewire `route()`, `run_skill()`, `_run_schedule()`; delete `converse_gemini`, `_gemini_tools`, `GEMINI_MODEL`, `GEMINI_MAX_STEPS`, all `GOOGLE_API_KEY` reads; tweak `_build_system()` wording; fix the module docstring and `run_terminal()` banner)
- Test: `tests/test_cloud.py` (append a grep-style sanity test)

**Interfaces:**
- Consumes: `converse_cloud` (from Task 4).
- Produces: a gateway with no Gemini references and all former Gemini call sites routed through `converse_cloud`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cloud.py`:

```python
class NoGeminiReferencesTests(unittest.TestCase):
    def test_no_gemini_symbols_in_source(self):
        src = (_ROOT / "greenclaw.py").read_text()
        for needle in ["converse_gemini", "_gemini_tools", "GEMINI_MODEL",
                        "GEMINI_MAX_STEPS", "GOOGLE_API_KEY", "generativelanguage.googleapis.com"]:
            self.assertNotIn(needle, src, f"found leftover Gemini ref: {needle}")

    def test_route_email_uses_cloud_without_shell(self):
        gc._ensure_ollama = lambda: None
        gc._memory_context = ""
        gc._history.clear()
        gc.notify_telegram = lambda t: None
        seen = {}
        def spy(model, messages, tools):
            seen["tools"] = tools
            return ("email ok", [])
        gc.call_cloud_model = spy
        out = gc.route("[email subject: hi]\nplease summarize", chat_id="3")
        self.assertEqual(out, "email ok")
        names = sorted(t["function"]["name"] for t in seen["tools"])
        self.assertNotIn("run_shell", names)

    def test_route_gg_uses_cloud_with_shell(self):
        gc._ensure_ollama = lambda: None
        gc._memory_context = ""
        gc._history.clear()
        gc.notify_telegram = lambda t: None
        seen = {}
        def spy(model, messages, tools):
            seen["tools"] = tools
            return ("gg ok", [])
        gc.call_cloud_model = spy
        out = gc.route("gg do thing", chat_id="3")
        self.assertEqual(out, "gg ok")
        names = sorted(t["function"]["name"] for t in seen["tools"])
        self.assertIn("run_shell", names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cloud.NoGeminiReferencesTests -v`
Expected: FAIL — `converse_gemini` etc. still present; `route` still calls `converse_gemini`.

- [ ] **Step 3: Write minimal implementation**

Make these edits in `greenclaw.py`:

**(a) Module docstring (top of file):** replace the Gemini lines:
```
  gg <prompt>            -> Gemini 2.5 Flash (force)
```
with:
```
  gg <prompt>            -> cloud model (glm-5.2:cloud, force)
```

**(b) Delete the Gemini constants block (lines ~44-46):**
```python
# Gemini channel: Google AI Studio REST API.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_STEPS = 8
```
Remove entirely. (The `CLOUD_*` constants from Task 4 live near the Ollama constants.)

**(c) `_build_system`:** replace the sentence:
```
"You are a small local model: handle simple things yourself and be honest about your limits. "
```
with:
```
"You are the first-responder cloud model: handle simple things yourself and be honest about your limits. "
```
Leave the rest of `_build_system` unchanged.

**(d) Delete `_gemini_tools` and `converse_gemini` entirely** (the two functions). They are superseded by `_cloud_tools` / `converse_cloud`.

**(e) `converse_local_ondemand` docstring:** replace `converse_gemini` with `converse_cloud`:
```
    Loads/saves per-chat rolling history like ask_cc and converse_cloud."""
```

**(f) `_run_schedule`:** replace the `converse_gemini` call:
```python
            return converse_gemini("Run this skill now.", system_extra=augmented_body)
```
with:
```python
            return converse_cloud("Run this skill now.", system_extra=augmented_body)
```

**(g) `run_skill`:** replace:
```python
    if skill.get("exposes") == "gg":
        return converse_gemini(prompt)
    return ask_cc(prompt)
```
with:
```python
    if skill.get("exposes") == "gg":
        return converse_cloud(prompt)
    return ask_cc(prompt)
```

**(h) `route` docstring + body:** update the docstring's `gg` mention from "Gemini 2.5 Flash" to "the cloud model". Replace the two `converse_gemini` calls:

```python
    if text_lower.startswith("gg "):
        return converse_gemini(prefix_text[3:].strip(), chat_id=chat_id)
```
→
```python
    if text_lower.startswith("gg "):
        return converse_cloud(prefix_text[3:].strip(), chat_id=chat_id)
```

and the email branch:
```python
    if is_email:
        # Email bodies are untrusted remote input — withhold run_shell from the
        # tool set. delegate_to_cc stays (the owner emailing in wants CC reach);
        # the sender gate in tasks/email.py is the primary trust boundary.
        return converse_gemini(text, chat_id=chat_id, allow_shell=False)
```
→
```python
    if is_email:
        # Email bodies are untrusted remote input — withhold run_shell from the
        # tool set. delegate_to_cc stays (the owner emailing in wants CC reach);
        # the sender gate in tasks/email.py is the primary trust boundary.
        return converse_cloud(text, chat_id=chat_id, allow_shell=False)
```

**(i) `run_terminal` banner:** replace:
```python
    print("router ready — Gemini handles messages and calls Claude Code when needed. "
          "Prefix `cc ` to force Claude Code, `gg ` to force Gemini. Ctrl-D to quit.\n")
```
with:
```python
    print("router ready — the cloud model handles messages and calls Claude Code when needed. "
          "Prefix `cc ` to force Claude Code, `gg ` to force the cloud model. Ctrl-D to quit.\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cloud -v`
Expected: PASS — all classes, including `NoGeminiReferencesTests` (3 tests). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add greenclaw.py tests/test_cloud.py
git commit -m "Remove Gemini, rewire gg/email/skill/schedule to converse_cloud

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `.env.example`, `static/cheat.md`, `README.md`, version bump

**Files:**
- Modify: `.env.example`, `static/cheat.md`, `README.md`, `greenclaw.py` (`__version__`)

**Interfaces:**
- Consumes: the new env var names from Task 4.
- Produces: docs and example env consistent with the cloud tier; `__version__ = "0.5.0"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cloud.py`:

```python
class DocsAndVersionTests(unittest.TestCase):
    def test_env_example_has_cloud_vars_no_gemini(self):
        txt = (_ROOT / ".env.example").read_text()
        self.assertIn("GC_CLOUD_MODEL=", txt)
        self.assertIn("GC_CLOUD_FALLBACK=", txt)
        self.assertNotIn("GOOGLE_API_KEY", txt)

    def test_cheat_sheet_no_gemini(self):
        txt = (_ROOT / "static" / "cheat.md").read_text()
        self.assertNotIn("Gemini", txt)

    def test_readme_no_gemini_key(self):
        txt = (_ROOT / "README.md").read_text()
        self.assertNotIn("GOOGLE_API_KEY", txt)
        self.assertIn("GC_CLOUD_MODEL", txt)

    def test_version_bumped(self):
        self.assertEqual(gc.__version__, "0.5.0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cloud.DocsAndVersionTests -v`
Expected: FAIL — env example lacks `GC_CLOUD_*`, cheat sheet mentions Gemini, README has `GOOGLE_API_KEY`, version still `0.4.1`.

- [ ] **Step 3: Write minimal implementation**

**`.env.example`** — after the `TELEGRAM_CHAT_ID=` block, add:
```
# Cloud tier (Ollama Cloud — sign in with `ollama` to ollama.com first)
GC_CLOUD_MODEL=glm-5.2:cloud
GC_CLOUD_FALLBACK=kimi-k2.7-code:cloud
```
Confirm no `GOOGLE_API_KEY` line is present (it is not in the current example). Leave `OLLAMA_MODEL` unset here (the local-Qwen path keeps its code default).

**`static/cheat.md`** — replace:
```
  gg <prompt>   force Gemini 2.5 Flash (free tier, tool loop)
```
with:
```
  gg <prompt>   force cloud model (glm-5.2:cloud, tool loop)
```

**`README.md`** — at line ~152 replace:
```
- A Google AI Studio API key (free — [aistudio.google.com](https://aistudio.google.com))
```
with:
```
- Ollama installed and signed into Cloud (`ollama` → sign in to ollama.com); `glm-5.2:cloud` and `kimi-k2.7-code:cloud` resolvable
```
At line ~171 replace:
```
GOOGLE_API_KEY=...     # Google AI Studio key for Gemini
```
with:
```
GC_CLOUD_MODEL=glm-5.2:cloud       # primary cloud model
GC_CLOUD_FALLBACK=kimi-k2.7-code:cloud  # secondary; auto-escalates to CC if both fail
```

**`greenclaw.py`** — bump:
```python
__version__ = "0.5.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_cloud.DocsAndVersionTests -v`
Expected: PASS (4 tests). Then run the whole suite: `python -m unittest tests.test_cloud -v` — all green.

- [ ] **Step 5: Commit**

```bash
git add .env.example static/cheat.md README.md greenclaw.py tests/test_cloud.py
git commit -m "Update docs/env for cloud tier; bump to 0.5.0

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Compile check + box smoke test + PR

**Files:** none (verification + rollout).

**Interfaces:** consumes all prior tasks.

- [ ] **Step 1: Compile check on the laptop**

Run: `python -m py_compile greenclaw.py && python -m unittest tests.test_cloud -v`
Expected: no compile error; full test suite green.

- [ ] **Step 2: Push the feature branch and open a PR**

Run:
```bash
git checkout main && git pull
git checkout -b cloud-fallback-chain
# (the prior commits were made on whichever branch — if they're on main locally,
#  move them: cherry-pick or reset as needed so they land on cloud-fallback-chain
#  and main is clean. Inspect with `git log --oneline -8` first.)
git push -u origin cloud-fallback-chain
gh pr create --title "Cloud fallback chain (issue #35)" \
  --body "Replace Gemini with Ollama-Cloud tier: glm-5.2:cloud → kimi-k2.7-code:cloud → CC. Telegram notify on fallback; urgent notify + auto-escalate on exhaustion. Removes Gemini + GOOGLE_API_KEY. Closes #35." \
  --base main
```
Expected: PR URL returned. Push to `main` directly is blocked — do not attempt.

- [ ] **Step 3: Pre-flight on the box (SSH from laptop)**

Run on the box (the Lenovo M920q):
```bash
ssh mrgreen@192.168.1.64 'cd ~/greenclaw && git fetch && git checkout cloud-fallback-chain && git pull'
ssh mrgreen@192.168.1.64 'ollama list | grep -E "glm-5.2:cloud|kimi-k2.7-code:cloud"'
```
Expected: both cloud tags listed. If either is missing, run `ollama pull <tag>` on the box. If `ollama` is not signed into Cloud, the engineer must sign in interactively (`ollama` → follow the Cloud sign-in prompt) — flag this to the user, do not attempt to auth yourself.

- [ ] **Step 4: Smoke test on the box**

Run on the box:
```bash
ssh mrgreen@192.168.1.64 'cd ~/greenclaw && python -m py_compile greenclaw.py && python -m unittest tests.test_cloud -v'
```
Expected: suite green.

Then a live fallback probe (forces `CloudCallError` → secondary → notify):
```bash
ssh mrgreen@192.168.1.64 'cd ~/greenclaw && GC_CLOUD_MODEL=bogus:cloud python -c "
import greenclaw as g
g.load_env()
print(g.converse_cloud(\"say hi in one word\"))
"'
```
Expected: reply served by `kimi-k2.7-code:cloud`; a `cloud fallback:` Telegram notification lands on the owner's chat.

Then an exhaustion probe (both bogus → CC escalation):
```bash
ssh mrgreen@192.168.1.64 'cd ~/greenclaw && GC_CLOUD_MODEL=bogus:cloud GC_CLOUD_FALLBACK=bogus2:cloud python -c "
import greenclaw as g
g.load_env()
print(g.converse_cloud(\"say hi in one word\"))
"'
```
Expected: `cloud tier exhausted:` Telegram notification + a Claude Code reply.

- [ ] **Step 5: Merge, deploy, confirm alive**

Merge the PR on GitHub (`gh pr merge cloud-fallback-chain --merge` or via the web). Then on the box:
```bash
ssh mrgreen@192.168.1.64 'cd ~/greenclaw && git checkout main && git pull'
ssh mrgreen@192.168.1.64 'systemctl --user restart greenclaw.service && sleep 2 && systemctl --user is-active greenclaw.service'
```
Expected: `active`. Report the deploy + a one-line audit note of what changed to the user.

- [ ] **Step 6: Commit final state if any merge artefacts**

If the merge left the local branch ahead, sync:
```bash
git checkout main && git pull
```
Expected: clean working tree on `main`.

---

## Self-Review

**Spec coverage:**
- §1 goal → Tasks 4-5 (cloud tier replaces Gemini across all its routes).
- §2 architecture (primitive + orchestrator) → Tasks 2 + 4.
- §3 fallback chain + notify + escalation → Task 4 (`converse_cloud`).
- §4 `call_cloud_model` primitive (num_ctx 40960, 120s, typed errors) → Task 2.
- §5 tool set + loop + `allow_shell` carry-forward + mid-loop restart on clean transcript → Tasks 3 + 4.
- §6 `notify_telegram` helper + `_sched_reply` refactor → Task 1.
- §7 concurrency cap (Semaphore 3) → Task 2 constant + used in Task 4's `call_cloud_model`.
- §8 Gemini removal + rewire + `_build_system` wording → Task 5.
- §9 env vars → Task 4 (constants) + Task 6 (`.env.example`/README).
- §10 testing (compile + box smoke + pre-flight Cloud sign-in) → Task 7.
- §11 files touched → matches File Structure.
- §12 rollout (feature branch + PR + box deploy) → Task 7.

**Placeholder scan:** none — every code/test step has full content.

**Type consistency:** `CloudCallError(reason, status)` used identically in Tasks 2 and 4. `call_cloud_model -> (str, list[{"name","arguments"}])` matches between Task 2 (producer), Task 4 (consumer via `_cloud_tool_loop`), and the Task 4/5 tests' mocked returns. `_cloud_tools` shape `{"type":"function","function":{...}}` matches Task 3 tests and the Task 4/5 `allow_shell` spies. `converse_cloud(text, system_extra=None, chat_id=None, allow_shell=True)` matches the `converse_gemini` signature at every rewired call site (Task 5). `notify_telegram(text)` matches Task 1 and Task 4. `CLOUD_CHAIN`, `GC_CLOUD_MODEL`, `GC_CLOUD_FALLBACK`, `CLOUD_MAX_STEPS`, `CLOUD_SEMAPHORE` named consistently across Tasks 2/4/6.

No issues found.