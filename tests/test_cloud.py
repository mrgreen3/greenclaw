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