"""Tiedostotyökalut: luku, listaus, haku nimellä ja sisällöllä, luonti."""
import fnmatch
import os
import subprocess

import guard
from .registry import tool
from ._common import host_env
from ._common import run, limit_lines

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


@tool("read_file", readonly=True,
      description="Lukee tekstitiedoston sisällön",
      params={"path": "Tiedoston absoluuttinen tai suhteellinen polku",
              "max_lines": "Maksimimäärä rivejä (oletus 100)"})
def read_file(path: str, max_lines: int = 100) -> str:
    try:
        p = guard.check_path(path)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"

    if not p.exists():
        return f"[virhe] tiedostoa ei löytynyt: {path}"
    if p.is_dir():
        return f"[virhe] {path} on hakemisto – käytä list_dir-työkalua"
    if not p.is_file():
        return f"[virhe] {path} ei ole tavallinen tiedosto"

    try:
        with open(p, "r", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
        return "".join(lines) or "(tyhjä tiedosto)"
    except Exception as e:
        return f"[virhe] {e}"


@tool("list_dir", readonly=True,
      description="Listaa hakemiston sisällön",
      params={"path": "Hakemiston polku (oletus nykyinen hakemisto)"})
def list_dir(path: str = ".") -> str:
    try:
        p = guard.check_path(path)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"

    if not p.is_dir():
        return (f"[virhe] '{path}' ei ole hakemisto. "
                f"Jos tarkoitit nykyistä hakemistoa, käytä path='.'")
    try:
        visible = [e for e in sorted(os.listdir(p))
                   if not guard.is_blocked(os.path.join(p, e))]
        return "\n".join(visible) or "(tyhjä hakemisto)"
    except Exception as e:
        return f"[virhe] {e}"


@tool("search_files", readonly=True,
      description="Etsii tiedostoja nimen perusteella hakemistopuusta",
      params={"pattern": "Etsittävä kuvio (esim. '*.py' tai 'core')",
              "path": "Hakemiston juuri (oletus nykyinen hakemisto)"})
def search_files(pattern: str, path: str = ".") -> str:
    try:
        root_path = guard.check_path(path)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"

    if not root_path.is_dir():
        return f"[virhe] {path} ei ole hakemisto"

    pat = pattern.lower()
    matches = []
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs
                   if d not in _SKIP_DIRS and not d.startswith(".")
                   and not guard.is_blocked(os.path.join(root, d))]
        for f in files:
            full = os.path.join(root, f)
            if guard.is_blocked(full):
                continue
            if fnmatch.fnmatch(f.lower(), pat) or pat in f.lower():
                matches.append(full)
                if len(matches) >= 50:
                    matches.append("...(lisää tuloksia rajoitettu)")
                    return ("Löytyi yli 50 tiedostoa (näytetään 50):\n"
                            + "\n".join(matches))

    if not matches:
        return "(ei tuloksia)"
    return f"Löytyi {len(matches)} tiedostoa:\n" + "\n".join(matches)


@tool("grep_files", readonly=True, requires=("grep",),
      description=(
          "Etsii merkkijonoa tai regex-kuviota tiedostojen sisällöstä. "
          "Käyttää grep-komentoa rekursiivisesti. Hyödyllinen kun "
          "etsitään koodia, konfiguraatioita tai tekstiä tiedostoista."
      ),
      params={
          "pattern": "Etsittävä merkkijono tai regex, esim. 'TODO' tai 'def main'",
          "path": "Hakemiston juuri (oletus nykyinen hakemisto)",
          "file_glob": "Tiedostopääte-rajoitus, esim. '*.py' (valinnainen)",
      })
def grep_files(pattern: str, path: str = ".", file_glob: str = "") -> str:
    if not pattern or len(pattern) > 200:
        return "[virhe] virheellinen haku-kuvio"
    if len(path) > 500:
        return "[virhe] polku liian pitkä"

    try:
        root = guard.check_path(path)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"
    if not root.is_dir():
        return f"[virhe] {path} ei ole hakemisto"

    cmd = ["grep", "-rnI", "--color=never",
           "--include", file_glob or "*"]
    for d in (".git", "node_modules", "__pycache__", ".venv", "venv",
              ".tox", "dist", "build"):
        cmd.append(f"--exclude-dir={d}")
    # -e estää sen, että '-'-alkuinen kuvio tulkitaan optioksi
    cmd += ["-e", pattern, "--", str(root)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=host_env(), timeout=15)
    except subprocess.TimeoutExpired:
        return "[virhe] grep aikakatkaistiin (15 s)"
    except FileNotFoundError:
        return "[virhe] grep-komentoa ei löydy järjestelmästä"
    except Exception as e:
        return f"[virhe] {e}"

    output = result.stdout.strip()
    if not output:
        return f"(ei osumia kuviolle '{pattern}')"

    # Muoto "path:rivinumero:sisältö" – suodata estetyt polut pois
    filtered = [
        line for line in output.split("\n")
        if not guard.is_blocked(line.split(":", 2)[0])
    ]
    if not filtered:
        return f"(ei osumia kuviolle '{pattern}' sallituissa tiedostoissa)"

    return limit_lines("\n".join(filtered), 100,
                       note="näytetään ensimmäiset {n} osumaa")


@tool("create_file", readonly=False,
      description="Luo tyhjä tiedosto (touch)",
      params={"path": "Luotavan tiedoston polku"})
def create_file(path: str) -> str:
    try:
        p = guard.check_path(path)
    except guard.AccessDenied as e:
        return f"[estetty] {e}"
    return run(["touch", str(p)])
