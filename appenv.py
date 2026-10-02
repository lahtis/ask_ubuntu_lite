"""Shared environment/path helpers for Ask Ubuntu (snap-aware).

Tärkeä snap-ero: snapin sisällä $HOME osoittaa kansioon SNAP_USER_DATA
(~/snap/<nimi>/<rev>), ei oikeaan kotihakemistoon. Oikea koti on
$SNAP_REAL_HOME. Siksi "~"-polut pitää ratkaista expand_home()-funktiolla.
"""
import os
import pwd
import shutil
from pathlib import Path
from typing import Mapping, Optional

APP_SNAP_NAME_PREFIX = "ask-ubuntu-mini"
APP_DIRNAME = "ask-ubuntu-mini"

# Snapin omat kirjastopolut eivät saa vuotaa isäntäjärjestelmän komentoihin
_STRIP_IN_SNAP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME",
                  "PYTHONPATH", "PYTHONUSERBASE")
_FALLBACK_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    # HUOM: "env or os.environ" korvaisi tyhjän dictin oikealla ympäristöllä
    return os.environ if env is None else env


def in_ask_ubuntu_snap(env: Optional[Mapping[str, str]] = None) -> bool:
    """True vain Ask Ubuntun snapin sisällä."""
    e = _env(env)
    snap = e.get("SNAP", "")
    snap_name = e.get("SNAP_NAME", "")
    return bool(
        snap and (snap_name.startswith(APP_SNAP_NAME_PREFIX)
                  or f"/{APP_SNAP_NAME_PREFIX}/" in snap)
    )


def _snap_path(var: str, env) -> Optional[Path]:
    e = _env(env)
    if not in_ask_ubuntu_snap(e):
        return None
    val = e.get(var)
    return Path(val) if val else None


def snap_root(env=None) -> Optional[Path]:
    return _snap_path("SNAP", env)


def snap_user_common(env=None) -> Optional[Path]:
    """Käyttäjäkohtainen, revisiosta riippumaton (ei kopioida päivityksessä)."""
    return _snap_path("SNAP_USER_COMMON", env)


def snap_user_data(env=None) -> Optional[Path]:
    """Käyttäjäkohtainen, revisiokohtainen (kopioidaan päivityksessä)."""
    return _snap_path("SNAP_USER_DATA", env)


def real_home(env: Optional[Mapping[str, str]] = None) -> Path:
    """Käyttäjän oikea kotihakemisto, myös snapin sisällä."""
    e = _env(env)
    if in_ask_ubuntu_snap(e):
        rh = e.get("SNAP_REAL_HOME")
        if rh:
            return Path(rh)
        try:
            return Path(pwd.getpwuid(os.getuid()).pw_dir)
        except KeyError:
            pass
    home = e.get("HOME")
    return Path(home) if home else Path.home()


def expand_home(path, env: Optional[Mapping[str, str]] = None) -> str:
    """Korvaa alun '~' oikealla kotihakemistolla (snap-tietoisesti)."""
    s = str(path)
    if s == "~":
        return str(real_home(env))
    if s.startswith("~/"):
        return str(real_home(env) / s[2:])
    return s


def _app_dir(kind: str, env, create: bool) -> Path:
    base = snap_user_common(env)
    if base:
        d = base / kind
    else:
        xdg = ".cache" if kind == "cache" else ".config"
        d = real_home(env) / xdg / APP_DIRNAME
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def app_cache_dir(env=None, create: bool = True) -> Path:
    return _app_dir("cache", env, create)


def app_config_dir(env=None, create: bool = True) -> Path:
    """Konfiguraatio SNAP_USER_COMMON-alle: käyttäjän muokkaama allow.txt
    ei häviä tai monistu revisioiden välillä."""
    return _app_dir("config", env, create)

def config_search_dirs(env=None) -> list[Path]:
    """Return application configuration directories in search order.

    In the snap, persistent snap configuration is searched first, followed
    by the user's real home configuration directory. Outside the snap,
    only the normal application configuration directory is returned.
    """
    e = _env(env)
    dirs = []

    snap_config = snap_user_common(e)
    if snap_config:
        dirs.append(snap_config / "config")
        dirs.append(real_home(e) / ".config" / APP_DIRNAME)
    else:
        dirs.append(app_config_dir(e, create=False))

    # Remove duplicates while preserving search order.
    result = []
    seen = set()

    for directory in dirs:
        directory = Path(directory)
        key = str(directory)
        if key not in seen:
            seen.add(key)
            result.append(directory)

    return result


def host_env(extra: Optional[Mapping[str, str]] = None,
             env: Optional[Mapping[str, str]] = None) -> dict:
    """Ympäristö isäntäjärjestelmän komentojen ajoon (subprocess)."""
    e = dict(_env(env))
    if in_ask_ubuntu_snap(e):
        for k in _STRIP_IN_SNAP:
            e.pop(k, None)
        root = e.get("SNAP", "")
        parts = [p for p in e.get("PATH", "").split(os.pathsep)
                 if p and not (root and p.startswith(root))]
        e["PATH"] = os.pathsep.join(parts) or _FALLBACK_PATH
        e["HOME"] = str(real_home(e))
    if extra:
        e.update(extra)
    return e


def which_host(binary: str) -> Optional[str]:
    """Löytyykö komento isäntäjärjestelmän PATH:sta?"""
    return shutil.which(binary, path=host_env().get("PATH"))

def socket_path(env: Optional[Mapping[str, str]] = None) -> Path:
    """Return the Unix socket path used by the Ask Ubuntu daemon."""
    base = snap_user_common(env)
    if base:
        base.mkdir(parents=True, exist_ok=True)
        return base / "ask.sock"

    path = app_cache_dir(env, create=True) / "ask.sock"
    return path
