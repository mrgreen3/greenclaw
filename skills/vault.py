NAME = "vault"
TRIGGER = "/vault"
DESCRIPTION = "Read, search or write notes in the greenbrain vault"
SAFE = True

import os
import subprocess
from datetime import datetime

VAULT_DIR = os.path.expanduser("~/greenbrain")
GREENCLAW_DIR = os.path.join(VAULT_DIR, "greenclaw")


def write_note(topic: str, content: str) -> str:
    """Write or append to a vault note. Called by save_memory() in greenclaw.py."""
    os.makedirs(GREENCLAW_DIR, exist_ok=True)
    slug = topic.lower().replace(" ", "-").replace("/", "-")
    path = os.path.join(GREENCLAW_DIR, f"{slug}.md")
    timestamp = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(path):
        with open(path, "a") as f:
            f.write(f"\n---\n*{timestamp}*\n\n{content.strip()}\n")
        action = "updated"
    else:
        with open(path, "w") as f:
            f.write(f"# {topic}\n\n*{timestamp}*\n\n{content.strip()}\n")
        action = "created"
    _git_commit(f"{action}: {slug}")
    return f"vault: {action} greenclaw/{slug}.md"


def _git_commit(msg: str):
    try:
        subprocess.run(["git", "-C", VAULT_DIR, "add", "-A"], timeout=10, capture_output=True)
        subprocess.run(["git", "-C", VAULT_DIR, "commit", "-m", msg],
                       timeout=10, capture_output=True)
        subprocess.run(["git", "-C", VAULT_DIR, "push"],
                       timeout=30, capture_output=True)
    except Exception:  # noqa: BLE001
        pass  # vault write succeeded even if git fails


def search_vault(query: str) -> str:
    try:
        result = subprocess.run(
            ["grep", "-ril", query, VAULT_DIR],
            capture_output=True, text=True, timeout=10,
        )
        files = [f for f in result.stdout.strip().splitlines() if not f.endswith(".git")]
        if not files:
            return f"Nothing found for '{query}'"
        lines = [f"Found in {len(files)} note(s):"]
        for f in files:
            rel = os.path.relpath(f, VAULT_DIR)
            lines.append(f"  {rel}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"[vault] search error: {e}"


def read_note(topic: str) -> str:
    slug = topic.lower().replace(" ", "-").replace("/", "-")
    path = os.path.join(GREENCLAW_DIR, f"{slug}.md")
    if not os.path.exists(path):
        return f"No note found for '{topic}'"
    with open(path) as f:
        return f.read().strip()


def run(args: str) -> str:
    args = args.strip()
    if not args:
        # List all notes
        if not os.path.isdir(GREENCLAW_DIR):
            return "Vault is empty."
        notes = [f[:-3] for f in os.listdir(GREENCLAW_DIR) if f.endswith(".md") and f != "README.md"]
        if not notes:
            return "No notes yet."
        return "Notes:\n" + "\n".join(f"  {n}" for n in sorted(notes))
    if args.startswith("search "):
        return search_vault(args[7:].strip())
    if args.startswith("read "):
        return read_note(args[5:].strip())
    # Default: treat as a quick note — "topic: content" or just content
    if ":" in args:
        topic, content = args.split(":", 1)
        return write_note(topic.strip(), content.strip())
    return write_note("inbox", args)
