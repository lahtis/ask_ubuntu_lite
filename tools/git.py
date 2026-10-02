"""Git-työkalut."""
import subprocess

import guard
from .registry import tool
from ._common import host_env


def _git(root, *args, timeout: int = 5) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, env=host_env(), timeout=timeout,
    ).stdout.strip()


@tool("git_status", readonly=True, requires=("git",),
      description=(
          "Näyttää git-repon tilan: nykyinen haara, muuttuneet tiedostot, "
          "viimeisimmät commitit. Käytä tätä kun kysytään git-reposta."
      ),
      params={
          "path": "Git-repon polku (oletus nykyinen hakemisto)",
          "show_log": "Näytä myös viimeisimmät commitit (oletus True)",
      })
def git_status(path: str = ".", show_log: bool = True) -> str:
    try:
        root = guard.check_path(path)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"
    if not root.is_dir():
        return f"[virhe] {path} ei ole hakemisto"

    try:
        check = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, env=host_env(), timeout=5)
        if check.returncode != 0:
            return f"[virhe] {path} ei ole git-repositorio"
    except FileNotFoundError:
        return "[virhe] git-komentoa ei löydy järjestelmästä"
    except subprocess.TimeoutExpired:
        return "[virhe] git aikakatkaistiin"

    parts = []
    try:
        branch = _git(root, "branch", "--show-current")
        parts.append(f"Haara: {branch or '(detached HEAD)'}")
        status = _git(root, "status", "--short", "--branch")
        if status:
            parts += ["", "Status:", status]
        if show_log:
            log = _git(root, "log", "--oneline", "-n", "5", "--no-decorate")
            if log:
                parts += ["", "Viimeisimmät commitit:", log]
    except Exception as e:
        parts.append(f"[virhe] {e}")

    return "\n".join(parts) or "(ei git-tietoja)"
