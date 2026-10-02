"""Polkusuojaus: estää pääsyn arkaluontoisiin tiedostoihin ja hakemistoihin."""
import fnmatch
import os
from functools import lru_cache
from pathlib import Path

from appenv import app_config_dir, expand_home, real_home
from .errors import AccessDenied

# Estetyt hakemistot – mikä tahansa polku näiden alla on kielletty
BLOCKED_DIRS = [
    "~/.ssh", "~/.gnupg", "~/.aws", "~/.azure", "~/.config/gcloud",
    "~/.kube", "~/.docker", "~/.password-store", "~/.local/share/keyrings",
    "~/.mozilla", "~/.config/google-chrome", "~/.config/chromium",
    "~/.config/evolution", "~/.thunderbird",
    "/etc/sudoers.d", "/etc/ssl/private",
    "/dev",            # /dev/zero, /dev/urandom ym. täyttäisivät muistin
    "/proc/kcore",
]

# Estetyt tiedostot – tarkka polku
BLOCKED_FILES = [
    "~/.netrc", "~/.git-credentials", "~/.bash_history", "~/.zsh_history",
    "~/.python_history", "~/.docker/config.json",
    "/etc/shadow", "/etc/gshadow", "/etc/sudoers",
]

# Estetyt tiedostonimet – osuma mihin tahansa hakemistoon
BLOCKED_FILENAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "authorized_keys", "known_hosts", ".htpasswd",
    "environ",         # /proc/<pid>/environ sisältää prosessien salaisuuksia
}

BLOCKED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")

BLOCKED_PATTERNS = [
    ".env", ".env.*", "*.env",
    "credentials", "credentials.json",
    "*secret*", "*password*",
    "ssh_host_*_key",  # /etc/ssh/ssh_host_*_key
]

# Eivät ole salaisuuksia
ALLOWED_EXCEPTIONS = {".env.example", ".env.sample", ".env.template", ".env.dist"}


def allow_file() -> Path:
    """Käyttäjän sallimislista. Polun voi ohittaa ASK_UBUNTU_ALLOW_FILE-muuttujalla."""
    override = os.environ.get("ASK_UBUNTU_ALLOW_FILE")
    if override:
        return Path(expand_home(override)).expanduser()
    return app_config_dir(create=False) / "allow.txt"


def _resolve(path: str) -> Path:
    """Ratkaisee polun absoluuttiseksi ja seuraa symlinkit."""
    return Path(expand_home(path)).expanduser().resolve()


@lru_cache(maxsize=8)
def _blocked_roots(home: str) -> tuple[tuple[Path, ...], frozenset[Path]]:
    """Ratkaistut estopolut (välimuistissa HOME-kohtaisesti)."""
    return (
        tuple(Path(expand_home(d)).expanduser().resolve() for d in BLOCKED_DIRS),
        frozenset(Path(expand_home(f)).expanduser().resolve() for f in BLOCKED_FILES),
    )


# Sallimislistan välimuisti: (polku, mtime) -> ratkaistut polut
_allow_cache: tuple[tuple[Path, float], tuple[Path, ...]] | None = None


def _allowed_paths() -> tuple[Path, ...]:
    global _allow_cache
    f = allow_file()
    try:
        key = (f, f.stat().st_mtime)
    except OSError:
        return ()
    if _allow_cache and _allow_cache[0] == key:
        return _allow_cache[1]
    paths = []
    try:
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                paths.append(Path(expand_home(line)).expanduser().resolve())
    except Exception:
        return ()
    _allow_cache = (key, tuple(paths))
    return _allow_cache[1]


def _is_under(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def _user_allowed(p: Path) -> bool:
    return any(_is_under(p, a) for a in _allowed_paths())


def _is_blocked(p: Path) -> bool:
    name_lower = p.name.lower()

    if name_lower in ALLOWED_EXCEPTIONS:
        return False

    dirs, files = _blocked_roots(str(real_home()))
    if any(_is_under(p, d) for d in dirs):
        return True
    if p in files:
        return True
    if name_lower in BLOCKED_FILENAMES:
        return True
    if name_lower.endswith(BLOCKED_SUFFIXES):
        return True
    return any(fnmatch.fnmatch(name_lower, pat) for pat in BLOCKED_PATTERNS)


def check_path(path: str) -> Path:
    """Palauttaa ratkaistun polun tai heittää AccessDenied jos polku on estetty."""
    try:
        p = _resolve(path)
    except (OSError, RuntimeError, ValueError) as e:
        raise AccessDenied(f"polkua ei voi ratkaista: {path} ({e})")

    if _user_allowed(p):
        return p
    if _is_blocked(p):
        raise AccessDenied(
            f"pääsy estetty: {path} (arkaluontoinen tiedosto tai hakemisto)"
        )
    return p


def is_blocked(path: str) -> bool:
    """Pehmeä tarkistus hakemistopuun läpikäyntiin. Epäselvä tapaus → True."""
    try:
        p = _resolve(path)
        return False if _user_allowed(p) else _is_blocked(p)
    except Exception:
        return True
