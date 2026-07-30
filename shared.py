"""Constants and pure helpers shared between greenclaw.py and tasks/dashboard.py.

Kept separate and free of import-time side effects so dashboard.py can pull in
path constants and parse_front_matter without loading greenclaw.py itself
(which loads skills/tasks/schedules and reads .env at import time).
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

CC_LOG_FILE = os.path.expanduser("~/greenclaw/cc_calls.jsonl")
MEMORY_DIR = os.path.expanduser("~/.claude/projects/-home-mrgreen/memory")
NOTES_FILE = os.path.expanduser("~/notes.md")
SCHEDULES_DIR = os.path.join(_HERE, "schedules")
SCHEDULE_STATE_FILE = os.path.expanduser("~/.local/share/greenclaw/schedule.json")
TASKS_DIR = os.path.join(_HERE, "tasks")
MEMORY_SIZE_THRESHOLD = 50_000  # bytes — trigger CC compaction when exceeded


def parse_front_matter(text):
    """Split a skill/schedule file into (metadata dict, body). Front matter is
    a --- fenced block of trivial key: value lines at the top. Returns ({}, text)
    if absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body = "\n".join(lines[i + 1:]).strip()
            return meta, body
        if ":" in lines[i]:
            k, v = lines[i].split(":", 1)
            meta[k.strip()] = v.strip()
    return {}, text  # unterminated front matter -> treat as no metadata
