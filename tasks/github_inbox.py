#!/usr/bin/env python3
"""
greenclaw github_inbox watcher
------------------------------
Polls a private GitHub "bridge" repo for command issues labelled `gc-cmd`,
hands each one to Claude Code, and posts the result back as an issue comment.

Design notes:
  * stdlib only (urllib) -- no pip deps.
  * author-allowlisted: only acts on issues opened by ALLOWED_AUTHOR.
  * claim-before-execute: issue marked processed *before* CC runs, so a crash
    never double-runs a side-effecting task.
  * auto-creates the gc-cmd label on first run if missing.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---- config -----------------------------------------------------------------
OWNER          = "mrgreen3"
REPO           = "greenclaw-bridge"
CMD_LABEL      = "gc-cmd"

ALLOWED_AUTHOR = "mrgreen3"          # only this user's issues are executed

STATE_DIR  = Path.home() / ".local/share/greenclaw"
STATE_FILE = STATE_DIR / "github_inbox.json"

TOKEN_ENV  = "GREENCLAW_GH_TOKEN"    # fine-grained PAT, scoped to this repo only
                                     # Permissions: Issues read+write, nothing else.

CC_WORKDIR = str(Path.home() / "greenclaw")
CC_TIMEOUT = 600

POLL_SECONDS = 60
API = "https://api.github.com"
INBOX_ACTIVE_FLAG = Path.home() / ".local/share/greenclaw/inbox_active"

NAME = "github_inbox"
# -----------------------------------------------------------------------------


def _token():
    tok = os.environ.get(TOKEN_ENV)
    if not tok:
        f = STATE_DIR / "gh_token"
        if f.exists():
            tok = f.read_text().strip()
            if f.stat().st_mode & 0o077:
                print(f"[github_inbox] warning: {f} is group/world-readable (chmod 600)")
    if not tok:
        sys.exit(f"No token: set ${TOKEN_ENV} or write {STATE_DIR/'gh_token'} (chmod 600)")
    return tok


def _request(method, path, payload=None):
    url = path if path.startswith("http") else f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "greenclaw-github-inbox")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {method} {url} -> {e.code}: {e.read().decode()[:300]}")


def ensure_label():
    """Create gc-cmd label if it doesn't exist. Called once on startup."""
    try:
        _request("GET", f"/repos/{OWNER}/{REPO}/labels/{CMD_LABEL}")
    except RuntimeError as e:
        if "404" in str(e):
            _request("POST", f"/repos/{OWNER}/{REPO}/labels", {
                "name": CMD_LABEL,
                "color": "0075ca",
                "description": "Command for Greenclaw / Claude Code"
            })
            print(f"Created label: {CMD_LABEL}")
        else:
            raise


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"processed": []}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Cap the processed list — closed issues don't reappear in list_commands,
    # so old entries are dead weight. Keep the 500 most recent.
    if isinstance(state.get("processed"), list):
        state["processed"] = sorted(state["processed"])[-500:]
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def list_commands():
    issues = _request(
        "GET",
        f"/repos/{OWNER}/{REPO}/issues"
        f"?labels={CMD_LABEL}&state=open&sort=created&direction=asc&per_page=20",
    )
    return [i for i in issues if "pull_request" not in i]


def comment(n, body):
    _request("POST", f"/repos/{OWNER}/{REPO}/issues/{n}/comments", {"body": body})


def close_issue(n):
    _request("PATCH", f"/repos/{OWNER}/{REPO}/issues/{n}", {"state": "closed"})


def dispatch_to_cc(command: str) -> str:
    """
    Hand the command to Claude Code as a task prompt.

    SECURITY: `command` is remote input. Passed to CC as a *prompt*, never to a
    shell. The real guard is ALLOWED_AUTHOR + private repo + scoped PAT.

    Env: ANTHROPIC_API_KEY is stripped so OAuth-authed CC never falls back to
    the metered API path (mirrors greenclaw.ask_cc). --dangerously-skip-permissions
    matches ask_cc so issue tasks can actually read/write files and run agents.

    SEAM: swap this function's body if you prefer to route into an existing
    Greenclaw dispatch path. Everything else stays the same.
    """
    cc_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = subprocess.run(
        ["claude", "-p", command, "--dangerously-skip-permissions"],
        capture_output=True, text=True, timeout=CC_TIMEOUT, cwd=CC_WORKDIR, env=cc_env,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "").strip() or f"claude exited {proc.returncode}")
    return (proc.stdout or "").strip() or "(no output)"


def run_once():
    """One poll cycle. Safe to call from the Greenclaw scheduler thread."""
    state = load_state()
    processed = set(state["processed"])

    for issue in list_commands():
        n = issue["number"]
        if n in processed:
            continue

        author = issue["user"]["login"]
        if author != ALLOWED_AUTHOR:
            comment(n, f"Ignored: issues from `{author}` are not authorised.")
            close_issue(n)
            processed.add(n)
            state["processed"] = sorted(processed)
            save_state(state)
            continue

        # claim before executing
        processed.add(n)
        state["processed"] = sorted(processed)
        save_state(state)

        task = f"{issue['title']}\n\n{issue.get('body') or ''}".strip()
        try:
            result = dispatch_to_cc(task)
            comment(n, f"✅ Done.\n\n```\n{result[:60000]}\n```")
            close_issue(n)
        except Exception as e:
            comment(n, f"❌ Failed: {e}")
            close_issue(n)


def start(on_message):
    """Always-on GitHub bridge watcher. Polls for gc-cmd issues only when
    the inbox_active flag file exists. When flag is absent, sleeps cheaply
    (no GitHub calls). Automatically removes the flag after draining all issues.

    on_message callback is unused; this task is pure polling."""

    ensure_label_called = False

    while True:
        if not INBOX_ACTIVE_FLAG.exists():
            time.sleep(30)
            continue

        if not ensure_label_called:
            ensure_label()
            ensure_label_called = True

        try:
            run_once()
        except Exception as e:
            print(f"[github_inbox] poll error: {e}", file=sys.stderr)

        try:
            state = load_state()
            processed = set(state["processed"])
            remaining = [i for i in list_commands() if i["number"] not in processed]

            if not remaining:
                print("[github_inbox] all issues processed — deactivating inbox")
                INBOX_ACTIVE_FLAG.unlink(missing_ok=True)
                ensure_label_called = False
        except Exception as e:
            print(f"[github_inbox] could not check remaining issues: {e}", file=sys.stderr)

        time.sleep(POLL_SECONDS)
