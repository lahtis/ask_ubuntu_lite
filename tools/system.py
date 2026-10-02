"""Järjestelmätyökalut: levy, muisti, uptime, palvelut ja run_command."""
import subprocess

import guard
from .registry import tool
from ._common import host_env
from ._common import run, truncate_chars


@tool("check_disk", readonly=True,
      description="Näyttää levytilan pysyville levyjärjestelmille")
def check_disk() -> str:
    return run(["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs"])


@tool("check_memory", readonly=True, description="Näyttää muistin käytön")
def check_memory() -> str:
    return run(["free", "-h"])


@tool("check_uptime", readonly=True, description="Näyttää uptime-tiedot")
def check_uptime() -> str:
    return run(["uptime"])


@tool("list_services", readonly=True, description="Listaa systemd-palvelut")
def list_services() -> str:
    return run(["systemctl", "list-units", "--type=service", "--no-pager"])


@tool("run_command", readonly=True,
      description=(
          "Ajaa hyväksytyn järjestelmäkomennon ja palauttaa tulosteen. "
          "Sallitut komennot: ls, cat, head, tail, file, stat, df, free, "
          "uptime, nproc, hostname, whoami, date, ps, ss, ip, systemctl, "
          "journalctl. Ei putkia, ei uudelleenohjauksia, ei sudo:a."
      ),
      params={"command": (
          "Kokonainen komento argumentteineen, esim. "
          "'systemctl status ssh' tai 'journalctl -n 20 -u ssh'"
      )})
def run_command(command: str) -> str:
    try:
        tokens = guard.parse_and_validate(command)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"

    try:
        result = subprocess.run(tokens, capture_output=True, text=True, env=host_env(), timeout=10)
    except subprocess.TimeoutExpired:
        return "[virhe] komento aikakatkaistiin (10 s)"
    except FileNotFoundError:
        return f"[virhe] komentoa '{tokens[0]}' ei löydy järjestelmästä"
    except Exception as e:
        return f"[virhe] {e}"

    output = (result.stdout or result.stderr or "").strip()
    return truncate_chars(output) if output else "(ei tulostetta)"
