"""Työkalujen yhteiset apufunktiot."""
import subprocess

from appenv import host_env

SAFE_NAME_CHARS = "-_."


def run(cmd: list[str], timeout: int = 10) -> str:
    """Ajaa komennon ja palauttaa stdoutin tai stderrin."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=host_env(), timeout=timeout)
        return (result.stdout or result.stderr).strip() or "(ei tulostetta)"
    except subprocess.TimeoutExpired:
        return "[virhe] komento aikakatkaistiin"
    except FileNotFoundError:
        return f"[virhe] komentoa '{cmd[0]}' ei löydy järjestelmästä"
    except Exception as e:
        return f"[virhe] {e}"


def is_safe_name(value: str, extra: str = SAFE_NAME_CHARS, max_len: int = 50) -> bool:
    """Sallii vain kirjaimet, numerot ja annetut lisämerkit."""
    return bool(value) and len(value) <= max_len and all(
        c.isalnum() or c in extra for c in value
    )


def limit_lines(text: str, max_lines: int, note: str = "näytetään {n} / {total}") -> str:
    """Rajaa tulosteen rivimäärän ja lisää loppuun huomautuksen."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    lines = lines[:max_lines]
    lines.append("..." + note.format(n=max_lines, total=len(text.split("\n"))))
    return "\n".join(lines)


def truncate_chars(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...(tuloste katkaistu, {len(text)} merkkiä yhteensä)"
