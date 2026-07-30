import importlib.util
import json
import os
import sys
import time
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))  # greenclaw.py imports shared.py from repo root
spec = importlib.util.spec_from_file_location("greenclaw", _ROOT / "greenclaw.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)

import shared


class ParseFrontMatterTests(unittest.TestCase):
    def test_extracts_meta_and_body(self):
        text = "---\nname: foo\ntrigger: /foo\n---\nbody line 1\nbody line 2"
        meta, body = shared.parse_front_matter(text)
        self.assertEqual(meta, {"name": "foo", "trigger": "/foo"})
        self.assertEqual(body, "body line 1\nbody line 2")

    def test_no_front_matter_returns_empty_meta_and_full_text(self):
        text = "just some text\nno fences here"
        meta, body = shared.parse_front_matter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_unterminated_front_matter_treated_as_absent(self):
        text = "---\nname: foo\nno closing fence"
        meta, body = shared.parse_front_matter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_ignores_lines_without_colon(self):
        text = "---\nname: foo\njust a stray line\ntrigger: /foo\n---\nbody"
        meta, body = shared.parse_front_matter(text)
        self.assertEqual(meta, {"name": "foo", "trigger": "/foo"})

    def test_empty_body(self):
        text = "---\nname: foo\n---\n"
        meta, body = shared.parse_front_matter(text)
        self.assertEqual(meta, {"name": "foo"})
        self.assertEqual(body, "")

    def test_greenclaw_reexports_same_function(self):
        # greenclaw.py imports parse_front_matter from shared — make sure it's
        # actually the same function, not a re-implementation that could drift.
        self.assertIs(gc.parse_front_matter, shared.parse_front_matter)


class ParseDaysTests(unittest.TestCase):
    def test_daily_keyword_is_all_seven_days(self):
        self.assertEqual(gc._parse_days("daily"), set(range(7)))

    def test_star_and_empty_are_all_seven_days(self):
        self.assertEqual(gc._parse_days("*"), set(range(7)))
        self.assertEqual(gc._parse_days(""), set(range(7)))

    def test_range_mon_fri(self):
        self.assertEqual(gc._parse_days("mon-fri"), {0, 1, 2, 3, 4})

    def test_range_single_day(self):
        self.assertEqual(gc._parse_days("wed-wed"), {2})

    def test_comma_list(self):
        self.assertEqual(gc._parse_days("mon,wed,fri"), {0, 2, 4})

    def test_comma_list_with_stray_whitespace(self):
        self.assertEqual(gc._parse_days(" mon , wed "), {0, 2})

    def test_unrecognised_tokens_fall_back_to_all_seven_days(self):
        # No token in "bogus" matches a weekday name, so the comma-list branch
        # collects nothing and the `result or set(range(7))` fallback kicks in.
        self.assertEqual(gc._parse_days("bogus"), set(range(7)))


class MatchSkillTriggerTests(unittest.TestCase):
    def setUp(self):
        self._saved_skills = dict(gc.SKILLS)
        self._saved_triggers = dict(gc._trigger_map)
        gc.SKILLS.clear()
        gc._trigger_map.clear()
        gc.SKILLS["weather"] = {"name": "weather", "trigger": "/weather"}
        gc._trigger_map["/weather"] = "weather"

    def tearDown(self):
        gc.SKILLS.clear()
        gc.SKILLS.update(self._saved_skills)
        gc._trigger_map.clear()
        gc._trigger_map.update(self._saved_triggers)

    def test_matches_known_trigger(self):
        skill = gc.match_skill_trigger("/weather London")
        self.assertEqual(skill["name"], "weather")

    def test_trigger_must_be_first_token(self):
        self.assertIsNone(gc.match_skill_trigger("tell me about /weather"))

    def test_unknown_trigger_returns_none(self):
        self.assertIsNone(gc.match_skill_trigger("/nope"))

    def test_empty_text_returns_none(self):
        self.assertIsNone(gc.match_skill_trigger(""))
        self.assertIsNone(gc.match_skill_trigger("   "))

    def test_trigger_is_case_sensitive_on_lookup_key(self):
        # match_skill_trigger looks up the literal first token — callers
        # (route()) are responsible for lowercasing before calling it.
        self.assertIsNone(gc.match_skill_trigger("/Weather London"))


class HistoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._saved_file = gc.HISTORY_FILE
        self._saved_history = dict(gc._history)
        self._saved_updated = dict(gc._history_updated)
        gc.HISTORY_FILE = str(_HERE / "_tmp_history.json")
        gc._history = {}
        gc._history_updated = {}

    def tearDown(self):
        try:
            os.remove(gc.HISTORY_FILE)
        except OSError:
            pass
        try:
            os.remove(gc.HISTORY_FILE + ".tmp")
        except OSError:
            pass
        gc.HISTORY_FILE = self._saved_file
        gc._history = self._saved_history
        gc._history_updated = self._saved_updated

    def test_save_then_load_round_trips(self):
        gc._history["123"] = [{"role": "user", "content": "hi"}]
        gc._history_updated["123"] = time.time()
        gc.save_history("123")

        gc._history = {}
        gc._history_updated = {}
        gc.load_history()

        self.assertEqual(gc._history["123"], [{"role": "user", "content": "hi"}])

    def test_load_prunes_entries_past_ttl(self):
        stale_ts = time.time() - (gc.HISTORY_TTL_DAYS + 1) * 86400
        fresh_ts = time.time()
        data = {
            "stale": {"messages": [{"role": "user", "content": "old"}], "updated": stale_ts},
            "fresh": {"messages": [{"role": "user", "content": "new"}], "updated": fresh_ts},
        }
        with open(gc.HISTORY_FILE, "w") as f:
            json.dump(data, f)

        gc.load_history()

        self.assertNotIn("stale", gc._history)
        self.assertIn("fresh", gc._history)

    def test_load_missing_file_is_a_noop(self):
        gc.load_history()  # file doesn't exist — must not raise
        self.assertEqual(gc._history, {})


class ParseBlogEmailTests(unittest.TestCase):
    def test_blog_prefix_extracts_title_and_content(self):
        slug, title, content, tags, description = gc.parse_blog_email(
            "blog: My Great Post", "Just the body text."
        )
        self.assertEqual(title, "My Great Post")
        self.assertEqual(content, "Just the body text.")
        self.assertTrue(slug.endswith("my-great-post"))
        self.assertEqual(tags, [])
        self.assertEqual(description, "")

    def test_post_prefix_also_works(self):
        slug, title, content, tags, description = gc.parse_blog_email("post: Another One", "body")
        self.assertEqual(title, "Another One")

    def test_non_blog_subject_returns_all_none(self):
        result = gc.parse_blog_email("just a normal subject", "body")
        self.assertEqual(result, (None, None, None, None, None))

    def test_front_matter_tags_and_description_parsed(self):
        body = "tags: python, cli\ndescription: a quick tool\n\nThe actual content."
        slug, title, content, tags, description = gc.parse_blog_email("blog: Title", body)
        self.assertEqual(tags, ["python", "cli"])
        self.assertEqual(description, "a quick tool")
        self.assertEqual(content, "The actual content.")

    def test_slug_is_lowercase_hyphenated_with_date_prefix(self):
        import re
        slug, *_ = gc.parse_blog_email("blog: Hello, World! Weird $ymbols", "x")
        self.assertRegex(slug, r"^\d{4}-\d{2}-\d{2}-hello-world-weird-ymbols$")


class HandleBlogPostEmailTests(unittest.TestCase):
    """Covers the validation/parsing paths only — create_blog_post (which
    writes files and shells out to git/deploy.sh) is mocked so this stays a
    pure unit test with no filesystem or subprocess side effects."""

    def setUp(self):
        self._saved_create = gc.create_blog_post

    def tearDown(self):
        gc.create_blog_post = self._saved_create

    def test_rejects_non_email_input(self):
        success, message = gc.handle_blog_post_email("not an email at all")
        self.assertFalse(success)
        self.assertIn("Not an email", message)

    def test_rejects_unparseable_subject_line(self):
        success, message = gc.handle_blog_post_email("[garbled header]\nbody")
        self.assertFalse(success)

    def test_rejects_non_blog_subject(self):
        text = "[email subject: just saying hi]\nbody"
        success, message = gc.handle_blog_post_email(text)
        self.assertFalse(success)
        self.assertIn("blog:", message)

    def test_rejects_empty_body(self):
        text = "[email subject: blog: My Post]\n   \n> quoted only"
        success, message = gc.handle_blog_post_email(text)
        self.assertFalse(success)
        self.assertIn("empty", message)

    def test_valid_email_calls_create_blog_post_and_reports_url(self):
        calls = []

        def fake_create(slug, title, content, tags=None, description=""):
            calls.append((slug, title, content))
            return True, "ok", "https://blog.example/posts/x"

        gc.create_blog_post = fake_create
        text = "[email subject: blog: My Post]\nHello there, this is the body."
        success, message = gc.handle_blog_post_email(text)
        self.assertTrue(success)
        self.assertIn("https://blog.example/posts/x", message)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "My Post")


if __name__ == "__main__":
    unittest.main()
