import importlib.util
import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))  # greenclaw.py imports shared.py from repo root
spec = importlib.util.spec_from_file_location("greenclaw", _ROOT / "greenclaw.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)


class StaticCommandRoutingTests(unittest.TestCase):
    """route() short-circuits on these before ever reaching CC/cloud — no
    network, no subprocess, safe to call directly."""

    def test_version_with_and_without_slash(self):
        expected = f"greenclaw {gc.__version__}"
        self.assertEqual(gc.route("/version"), expected)
        self.assertEqual(gc.route("version"), expected)

    def test_model_reports_primary_and_fallback(self):
        result = gc.route("/model")
        self.assertIn(gc.GC_CLOUD_MODEL, result)
        self.assertIn(gc.GC_CLOUD_FALLBACK, result)
        self.assertEqual(gc.route("model"), result)

    def test_cheat_returns_the_cheat_sheet(self):
        result = gc.route("/cheat")
        self.assertIn("Prefixes:", result)
        self.assertEqual(gc.route("cheat"), result)

    def test_memory_stats(self):
        # Just needs to return a string without raising, regardless of
        # whether a memory dir exists on the machine running the tests.
        result = gc.route("/memory")
        self.assertIsInstance(result, str)
        self.assertEqual(gc.route("memory stats"), result)


class InboxToggleRoutingTests(unittest.TestCase):
    def setUp(self):
        self._saved_flag = gc.INBOX_ACTIVE_FLAG
        # Redirect off the real ~/.local/share/greenclaw/inbox_active file —
        # the live service reads that path too.
        gc.INBOX_ACTIVE_FLAG = str(_HERE / "_tmp_inbox_active")

    def tearDown(self):
        try:
            os.remove(gc.INBOX_ACTIVE_FLAG)
        except OSError:
            pass
        gc.INBOX_ACTIVE_FLAG = self._saved_flag

    def test_inbox_on_creates_flag_file(self):
        result = gc.route("/inbox on")
        self.assertIn("active", result)
        self.assertTrue(os.path.exists(gc.INBOX_ACTIVE_FLAG))

    def test_inbox_off_removes_flag_file(self):
        open(gc.INBOX_ACTIVE_FLAG, "a").close()
        result = gc.route("/inbox off")
        self.assertIn("off", result)
        self.assertFalse(os.path.exists(gc.INBOX_ACTIVE_FLAG))

    def test_inbox_off_when_already_off_does_not_raise(self):
        result = gc.route("/inbox off")
        self.assertIn("off", result)


class RegreenRoutingTests(unittest.TestCase):
    """route("/regreen") schedules a real `systemctl restart` via a 1.5s
    Timer. Both are faked here so the test suite can never actually restart
    the live greenclaw.service."""

    def test_regreen_schedules_restart_without_running_it_for_real(self):
        calls = []

        def fake_run(*a, **kw):
            calls.append(a)

        class ImmediateTimer:
            """Runs the callback synchronously instead of after 1.5s, so the
            test doesn't sleep and doesn't leave a background thread dangling
            past the test."""
            def __init__(self, interval, fn):
                self._fn = fn

            def start(self):
                self._fn()

        orig_run, orig_timer = gc.subprocess.run, gc.threading.Timer
        gc.subprocess.run, gc.threading.Timer = fake_run, ImmediateTimer
        try:
            result = gc.route("/regreen")
        finally:
            gc.subprocess.run, gc.threading.Timer = orig_run, orig_timer

        self.assertEqual(result, "restarting…")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["systemctl", "--user", "restart", "greenclaw.service"])


class RememberRoutingTests(unittest.TestCase):
    """save_memory() itself may shell out to git (skills/vault.py, if
    present) — that's out of scope here. This only checks that route()
    strips the "remember " prefix correctly and dispatches to it."""

    def test_remember_strips_prefix_and_calls_save_memory(self):
        calls = []
        orig = gc.save_memory
        gc.save_memory = lambda fact: calls.append(fact) or "saved"
        try:
            result = gc.route("remember buy milk tomorrow")
        finally:
            gc.save_memory = orig
        self.assertEqual(calls, ["buy milk tomorrow"])
        self.assertEqual(result, "saved")


if __name__ == "__main__":
    unittest.main()
