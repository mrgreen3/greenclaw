NAME = "check_updates"
TRIGGER = "/updates"
DESCRIPTION = "Check for pending Arch Linux package updates (read-only)"
SAFE = True

import subprocess


def run(args: str) -> str:
    try:
        result = subprocess.run(
            ["checkupdates"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return _pacman_fallback()
    except subprocess.TimeoutExpired:
        return "[updates] timed out"
    except Exception as e:  # noqa: BLE001
        return f"[updates] {e}"

    # exit 0 = updates available, exit 2 = no updates, anything else = error
    if result.returncode == 2 or (result.returncode != 0 and not result.stdout.strip()):
        return "System is up to date."

    lines = result.stdout.strip().splitlines()
    count = len(lines)
    summary = f"{count} update{'s' if count != 1 else ''} available:\n"
    summary += "\n".join(f"  {l}" for l in lines)
    return summary


def _pacman_fallback() -> str:
    """Use pacman -Qu when checkupdates (pacman-contrib) isn't installed."""
    try:
        result = subprocess.run(
            ["pacman", "-Qu"],
            capture_output=True, text=True, timeout=30,
        )
        lines = result.stdout.strip().splitlines()
        if not lines:
            return "System is up to date. (pacman -Qu, local db only)"
        count = len(lines)
        summary = f"{count} update{'s' if count != 1 else ''} available (local db — run pacman -Sy for fresh data):\n"
        summary += "\n".join(f"  {l}" for l in lines)
        return summary
    except Exception as e:  # noqa: BLE001
        return f"[updates] {e}"
