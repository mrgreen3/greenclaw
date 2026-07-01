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


class CloudToolsTests(unittest.TestCase):
    def _names(self, tools):
        return sorted(t["function"]["name"] for t in tools)

    def test_full_tools_include_run_shell_and_delegate(self):
        names = self._names(gc._cloud_tools(allow_shell=True))
        self.assertIn("run_shell", names)
        self.assertIn("delegate_to_cc", names)
        self.assertIn("add_note", names)

    def test_no_shell_withholds_run_shell_and_delegate(self):
        # delegate_to_cc routes to ask_cc() with --dangerously-skip-permissions
        # — the same shell-equivalent capability run_shell grants, just one hop
        # removed. The email From: header isn't a real trust boundary (no
        # SPF/DKIM), so it must be withheld here too, not just run_shell.
        names = self._names(gc._cloud_tools(allow_shell=False))
        self.assertNotIn("run_shell", names)
        self.assertNotIn("delegate_to_cc", names)
        self.assertIn("add_note", names)

    def test_ollama_shape(self):
        tools = gc._cloud_tools(allow_shell=True)
        for t in tools:
            self.assertEqual(t["type"], "function")
            self.assertIn("name", t["function"])
            self.assertIn("parameters", t["function"])


class ConverseCloudTests(unittest.TestCase):
    def setUp(self):
        # Snapshot module attributes so the suite is restored after these tests.
        self._saved = {
            "GC_CLOUD_MODEL": gc.GC_CLOUD_MODEL,
            "GC_CLOUD_FALLBACK": gc.GC_CLOUD_FALLBACK,
            "CLOUD_CHAIN": gc.CLOUD_CHAIN,
            "_ensure_ollama": gc._ensure_ollama,
            "_memory_context": gc._memory_context,
            "call_cloud_model": gc.call_cloud_model,
            "dispatch_tool": gc.dispatch_tool,
            "notify_telegram": gc.notify_telegram,
            "ask_cc": gc.ask_cc,
            "save_history": gc.save_history,
        }
        self._saved_history = dict(gc._history)
        gc.save_history = lambda key: None
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
            item = self._script.pop(0)
            if isinstance(item, gc.CloudCallError):
                raise item
            return item
        gc.call_cloud_model = fake_call

        def fake_dispatch(name, args):
            self.dispatched.append((name, args))
            return "tool-result"
        gc.dispatch_tool = fake_dispatch

        gc.notify_telegram = lambda t: self.notifications.append(t)
        gc.ask_cc = lambda text, chat_id=None: (self.cc_calls.append(text) or "cc-reply")

    def tearDown(self):
        gc.__dict__.update(self._saved)
        gc._history.clear()
        gc._history.update(self._saved_history)

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

    def test_email_path_withholds_run_shell_and_delegate(self):
        # Verify allow_shell=False reaches the tools layer by intercepting call_cloud_model.
        seen_tools = []
        def spy(model, messages, tools):
            seen_tools.append(tools)
            return ("ok", [])
        gc.call_cloud_model = spy
        gc.converse_cloud("hi", allow_shell=False)
        names = sorted(t["function"]["name"] for t in seen_tools[0])
        self.assertNotIn("run_shell", names)
        self.assertNotIn("delegate_to_cc", names)

    def test_no_fallback_after_tool_already_executed(self):
        # A tool ran, THEN the same model attempt failed. Falling back to the
        # next chain model here would replay the request and risk re-running
        # the side-effecting tool (e.g. run_shell/send_email) a second time —
        # the chain must stop instead of cascading to kimi.
        self._script = [
            self._reply("", [{"name": "run_shell", "arguments": {"command": "rm -f x"}}]),
            gc.CloudCallError("http", 500),  # follow-up call fails after the tool ran
        ]
        out = gc.converse_cloud("do the thing", chat_id="5")
        # Two calls to glm (dispatch turn + the failing follow-up), zero to kimi.
        self.assertEqual(self.calls, ["glm-5.2:cloud", "glm-5.2:cloud"])
        self.assertEqual(self.dispatched, [("run_shell", {"command": "rm -f x"})])
        self.assertEqual(out, "cc-reply")  # falls through to CC escalation
        self.assertIn("cloud tier exhausted", self.notifications[0])

    def test_history_saved_on_success(self):
        self._script = [self._reply("reply")]
        gc.converse_cloud("hi", chat_id="7")
        self.assertIn("7", gc._history)
        roles = [m["role"] for m in gc._history["7"]]
        self.assertEqual(roles, ["user", "assistant"])


class NoGeminiReferencesTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "_ensure_ollama": gc._ensure_ollama,
            "_memory_context": gc._memory_context,
            "call_cloud_model": gc.call_cloud_model,
            "notify_telegram": gc.notify_telegram,
            "save_history": gc.save_history,
        }
        self._saved_history = dict(gc._history)
        gc.save_history = lambda key: None

    def tearDown(self):
        gc._ensure_ollama = self._saved["_ensure_ollama"]
        gc._memory_context = self._saved["_memory_context"]
        gc.call_cloud_model = self._saved["call_cloud_model"]
        gc.notify_telegram = self._saved["notify_telegram"]
        gc.save_history = self._saved["save_history"]
        gc._history.clear()
        gc._history.update(self._saved_history)

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
        self.assertNotIn("delegate_to_cc", names)

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
        self.assertNotIn("Gemini", txt)

    def test_version_bumped(self):
        self.assertEqual(gc.__version__, "0.5.1")


if __name__ == "__main__":
    unittest.main()