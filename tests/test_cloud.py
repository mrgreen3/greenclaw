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


if __name__ == "__main__":
    unittest.main()