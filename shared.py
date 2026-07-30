"""Constants and pure helpers shared between greenclaw.py and tasks/dashboard.py.

Kept separate and free of import-time side effects so dashboard.py can pull in
path constants and parse_front_matter without loading greenclaw.py itself
(which loads skills/tasks/schedules and reads .env at import time).
"""
import os
import smtplib

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


def send_smtp(smtp_host, smtp_port, email_addr, email_pass, to_addr, msg):
    """Send a prebuilt email.message via SMTP. Port 465 = SMTPS (implicit TLS);
    anything else = SMTP + STARTTLS. Returns an error string, or None on success."""
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
                smtp.login(email_addr, email_pass)
                smtp.sendmail(email_addr, to_addr, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(email_addr, email_pass)
                smtp.sendmail(email_addr, to_addr, msg.as_string())
    except Exception as e:  # noqa: BLE001
        return f"[email send error] {e}"
    return None
