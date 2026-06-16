NAME = "sysinfo"
TRIGGER = "/sysinfo"
DESCRIPTION = "Server stats: disk, RAM, CPU load, uptime"
SAFE = True

import subprocess


def _run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, timeout=10).strip()
    except Exception as e:  # noqa: BLE001
        return f"[error: {e}]"


def run(args: str) -> str:
    uptime = _run("uptime -p")
    load = _run("uptime | awk -F'load average:' '{print $2}'").strip().lstrip()

    # RAM: total, used, available
    mem = _run("free -h --si | awk 'NR==2{print $2, $3, $7}'")
    try:
        total, used, avail = mem.split()
        ram_line = f"RAM: {used} used / {total} total ({avail} free)"
    except ValueError:
        ram_line = f"RAM: {mem}"

    # Disk: filter only real mount points (skip tmpfs/devtmpfs/overlay)
    df_raw = _run(
        "df -h --output=target,size,used,avail,pcent "
        "| awk 'NR==1 || ($1==\"/\" || $1==\"/home\" || $1==\"/mnt/sata\")'"
    )
    disk_lines = ["Disk:"]
    for line in df_raw.splitlines():
        if line.startswith("Filesystem") or line.startswith("Target"):
            continue
        disk_lines.append(f"  {line}")

    parts = [
        f"⬆ {uptime}  |  load: {load}",
        ram_line,
        "\n".join(disk_lines),
    ]
    return "\n".join(parts)
