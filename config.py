"""Konfiguraation lataus.

Prioriteetti (korkeimmasta matalimpaan):
  1. Ympäristömuuttuja (esim. OLLAMA_URLS)
  2. ASK_CONFIG-tiedosto (polku ympäristömuuttujassa)
  3. config.toml konfiguraatiohakemistoista (appenv.config_search_dirs():
     snapissa SNAP_USER_COMMON/config, sitten ~/.config/ask-ubuntu-mini)
  4. ./config.toml VAIN jos ASK_ALLOW_LOCAL_CONFIG=1
     (muuten satunnaisen hakemistoon jätetyn config.toml:n lataaminen
     voisi vaihtaa mm. Ollama-palvelimen)
  5. Sisäänrakennetut oletukset

System prompt:
  Ensisijaisesti ladataan system_prompts/-kansiosta (samoista hakemistoista):
    - core.toml      ydinprompti (sama kaikille kielille)
    - {lang}.toml    kielikohtainen lisäys (esim. fi.toml)
  Jos kansiota ei ole, käytetään config.toml:n system_prompt-kenttää.

Ollama-palvelimet:
  Käytä `ollama_urls`-listaa. Ensimmäinen elossa oleva valitaan.
  Vanha `ollama_url` (yksittäinen) tuetaan edelleen. Myös /api/chat-pääte
  siivotaan automaattisesti pois.

Ollama health check:
  Health check käyttää Ollaman /api/version-endpointia.
  Health checkin cache, timeout ja URL-kohtainen backoff ovat
  konfiguroitavissa config.toml-tiedostossa.
"""
import logging
import os
import re
import shutil
import tomllib
from pathlib import Path

import appenv
from language import resolve_language

logger = logging.getLogger(__name__)

# ─── Polut ───────────────────────────────────────────────────

SYSTEM_PROMPTS_DIR = appenv.app_config_dir(create=False) / "system_prompts"

# ─── Sisäänrakennetut oletukset ──────────────────────────────

DEFAULTS = {
    "ollama_urls": ["http://localhost:11434"],
    "ollama_health_cache_ttl": 30,
    "ollama_health_timeout": 1.5,
    "ollama_health_backoff": [2, 4, 8, 16, 30, 60],
    "ollama_chat_timeout": 120,
    "model": "llama3.1:8b",
    "temperature": 0.2,
    "num_ctx": 8192,
    "num_predict": 300,
    "repeat_penalty": 1.3,
    "repeat_last_n": 256,
    "stop": [
        "```json",
        "```JSON",
        "Here's how",
        "Here is how",
        "here's how",
        "here is how",
    ],
    "max_iterations": 5,
    "lang_code": "en",
    "m_translation_enabled": True,
    "system_prompt": (
        "You are a Linux command-line assistant. "
        "Respond in the SAME LANGUAGE as the user's question. "
        "Be brief and technically accurate. "
        "\n"
        "RULES:\n"
        "- Use tools whenever the question is about this machine's state.\n"
        "- NEVER suggest commands for the user to run. Run them yourself.\n"
        "- NEVER mention tool names in your answer.\n"
        "- Answer ONLY the question asked, in one or two sentences.\n"
    ),
}

# Ympäristömuuttujien nimet kutakin avainta varten
ENV_MAP = {
    "ollama_urls": "OLLAMA_URLS",
    "ollama_url": "OLLAMA_URL",
    "ollama_health_cache_ttl": "OLLAMA_HEALTH_CACHE_TTL",
    "ollama_health_timeout": "OLLAMA_HEALTH_TIMEOUT",
    "ollama_health_backoff": "OLLAMA_HEALTH_BACKOFF",
    "ollama_chat_timeout": "OLLAMA_CHAT_TIMEOUT",
    "model": "OLLAMA_MODEL",
    "system_prompt": "ASK_SYSTEM_PROMPT",
    "lang_code": "ASK_LANG",
    "m_translation_enabled": "ASK_MT_ENABLED",
    "num_predict": "ASK_NUM_PREDICT",
    "repeat_penalty": "ASK_REPEAT_PENALTY",
    "repeat_last_n": "ASK_REPEAT_LAST_N",
}


def _config_paths() -> list[Path]:
    """Hakupolut järjestyksessä (lasketaan kutsuhetkellä)."""
    paths = [d / "config.toml" for d in appenv.config_search_dirs()]
    if os.environ.get("ASK_ALLOW_LOCAL_CONFIG") == "1":
        paths.append(Path("./config.toml"))
    return paths

def _default_config_text() -> str:
    """Return the default user configuration file contents."""
    return """# ASK Ubuntu Mini – konfiguraatio
# Sijainti: ~/.config/ask-ubuntu-mini/config.toml

# Ollama-palvelimet. Ensimmäinen elossa oleva valitaan.
# HUOM: anna vain perus-URL (http://host:port), EI /api/chat-polkua.
ollama_urls = [
    "http://192.168.1.103:11434",
    "http://localhost:11434",
]

# Oletusmalli
model = "llama3.1:8b"

# Generoinnin lämpötila (0.0 = deterministinen, 1.0 = luova)
temperature = 0.2

# Kontekstin pituus tokeneina
num_ctx = 8192
num_predict = 300
repeat_penalty = 1.3
repeat_last_n = 256

# Maksimimäärä peräkkäisiä työkalukutsuja ennen keskeytystä
max_iterations = 5

# Käyttöliittymän kieli (eng, fin, sve, ...)
# lang_code = "fin"

m_translation_enabled = "true"

# Stop-sekvenssit: generaation katkaisu näihin merkkijonoihin
stop = [
    "```json",
    "```JSON",
    "Here's how",
    "Here is how",
    "here's how",
    "here is how",
    "However, to provide",
    "However, to answer",
    "To provide a JSON",
    "Based on the given functions",
    "based on the given functions",
]

# HUOM: system_prompt on nyt ~/.config/ask-ubuntu-mini/system_prompts/-kansiossa:
#   - core.toml      ydinprompti (sama kaikille kielille)
#   - fi.toml        kielikohtainen lisäys
# config.toml:n system_prompt on vain fallback, jos kansiota ei ole.

config_version = 1
ollama_health_cache_ttl = 30
ollama_health_timeout = 1.5
ollama_health_backoff = [2, 4, 8, 16, 30, 60]
ollama_chat_timeout = 120
"""


def _ensure_default_config() -> Path | None:
    """Create the user configuration file when it does not exist."""
    config_dir = appenv.app_config_dir(create=True)
    config_path = config_dir / "config.toml"

    if config_path.exists():
        return config_path

    try:
        config_path.write_text(
            _default_config_text(),
            encoding="utf-8",
        )
        logger.info("Created default config at %s", config_path)
        return config_path
    except OSError as e:
        logger.warning(
            "Could not create default config at %s: %s",
            config_path,
            e,
        )
        return None

# ─── Kielikoodin siistiminen ─────────────────────────────────

_LANG_RE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?")


def normalize_lang(code) -> str:
    """Palauttaa kelvollisen kielikoodin tai 'en'.

    Koodista muodostetaan tiedostonimiä (fi.toml, fi.json), joten vain
    muotoa 'fi' / 'en-US' / 'pt_BR' hyväksytään (ei polkuja, ei '..').
    """
    code = str(code or "").strip()
    if _LANG_RE.fullmatch(code):
        return code.replace("_", "-")
    if code:
        logger.warning("Invalid language code %r, using 'en'", code)
    return "en"


# ─── System prompt -lataus ───────────────────────────────────

def _find_prompt_file(name: str) -> Path | None:
    for d in appenv.config_search_dirs():
        f = d / "system_prompts" / name
        if f.exists():
            return f
    return None




def _default_language_prompt(
    language: str,
    language_name: str | None,
) -> str:
    """Return the default language-specific system prompt."""
    display_name = language_name or language

    return f'''# ASK Ubuntu Mini language addition.
# Language: {display_name}
# ISO 639-3: {language}
#
# This file is appended AFTER core.toml.
# Keep this file short.

language = "{language}"

append = """
LANGUAGE RULE (CRITICAL):
- The user's language is {display_name}.
- You MUST respond in {display_name}.
- Even if the user asks in English, respond in {display_name}.
- Even if the system prompt is in English, respond in {display_name}.
- Do NOT mix languages. Every word of your response must be {display_name}.
"""
'''


def _ensure_system_prompts(
    language: str,
    language_name: str | None,
) -> None:
    """Copy bundled system prompts to the user configuration directory."""
    source_dir = Path(__file__).parent / "system_prompts"
    config_dir = appenv.app_config_dir(create=True)
    prompt_dir = config_dir / "system_prompts"

    try:
        prompt_dir.mkdir(parents=True, exist_ok=True)

        # Core prompt is always the bundled English base.
        core_source = source_dir / "core.toml"
        core_target = prompt_dir / "core.toml"

        if not core_target.exists():
            shutil.copy2(core_source, core_target)
            logger.info(
                "Created core system prompt: %s",
                core_target,
            )

        # Create only the selected language prompt.
        language_file = prompt_dir / f"{language}.toml"

        if not language_file.exists():
            language_file.write_text(
                _default_language_prompt(language, language_name),
                encoding="utf-8",
            )
            logger.info(
                "Created default language prompt: %s",
                language_file,
            )

    except OSError as e:
        logger.warning(
            "Could not initialize system prompts in %s: %s",
            prompt_dir,
            e,
        )

def _load_system_prompt(lang_code: str) -> str:
    """Lataa ja yhdistä system prompt.

    Prioriteetti:
        1. system_prompts/core.toml + system_prompts/{lang}.toml
        2. config.toml:n system_prompt-kenttä
        3. DEFAULTS:n system_prompt
    """
    core_file = _find_prompt_file("core.toml")
    if core_file is None:
        return get("system_prompt")

    try:
        with open(core_file, "rb") as f:
            core_data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning("Failed to load %s: %s", core_file, e)
        return get("system_prompt")

    prompt = str(core_data.get("prompt", "")).strip()
    if not prompt:
        logger.warning("%s has empty 'prompt' key", core_file)
        return get("system_prompt")

    lang_file = _find_prompt_file(f"{lang_code}.toml")

    if lang_file is not None:
        try:
            with open(lang_file, "rb") as f:
                lang_data = tomllib.load(f)
            append = str(lang_data.get("append", "")).strip()
            if append:
                prompt = prompt + "\n\n" + append
                logger.debug("Loaded language addition from %s", lang_file)
        except (OSError, tomllib.TOMLDecodeError) as e:
            logger.warning("Failed to load %s: %s", lang_file, e)

    return prompt

# ─── System prompt hot reload ────────────────────────────────

_system_prompt_cache: str | None = None
_system_prompt_mtimes: tuple[float | None, float | None] | None = None


def _prompt_mtime(path: Path | None) -> float | None:
    """Return a prompt file modification time."""
    if path is None:
        return None

    try:
        return path.stat().st_mtime
    except OSError:
        return None


def get_system_prompt() -> str:
    """Return the current system prompt, reloading it when files change."""
    global _system_prompt_cache
    global _system_prompt_mtimes

    core_file = _find_prompt_file("core.toml")
    lang_file = _find_prompt_file(f"{LANG_CODE}.toml")

    mtimes = (
        _prompt_mtime(core_file),
        _prompt_mtime(lang_file),
    )

    if (
        _system_prompt_cache is not None
        and _system_prompt_mtimes == mtimes
    ):
        return _system_prompt_cache

    prompt = _load_system_prompt(LANG_CODE)

    if prompt != _system_prompt_cache:
        logger.info("System prompt reloaded")

    _system_prompt_cache = prompt
    _system_prompt_mtimes = mtimes

    return prompt



# ─── Lataus ──────────────────────────────────────────────────

def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        logger.debug("Loaded config from %s", path)
        return data
    except Exception as e:
        logger.warning("Failed to load config from %s: %s", path, e)
        return {}


def _find_config() -> tuple[dict, Path | None]:
    """Etsii ja lataa konfiguraation. Palauttaa (data, polku)."""
    custom = os.environ.get("ASK_CONFIG")
    if custom:
        p = Path(appenv.expand_home(custom)).expanduser()
        return _load_toml(p), p

    for p in _config_paths():
        if p.exists():
            return _load_toml(p), p

    # Create the normal user configuration when no config exists.
    default_path = _ensure_default_config()
    if default_path is not None:
        return _load_toml(default_path), default_path

    return {}, None


# ─── Config-migraatiot ───────────────────────────────────────

CONFIG_VERSION = 1

# Jokainen numeroitu lohko sisältää kyseisessä versiossa
# lisätyt uudet asetukset.
_MIGRATION_DEFAULTS = {
    1: {
        "ollama_health_cache_ttl": 30,
        "ollama_health_timeout": 1.5,
        "ollama_health_backoff": [2, 4, 8, 16, 30, 60],
        "ollama_chat_timeout": 120,
    },
}


def _config_version(data: dict) -> int:
    """Return the stored configuration version.

    Configurations without a version are treated as version 0.
    Invalid versions are left untouched rather than guessing.
    """
    value = data.get("config_version", 0)

    if value == 0:
        return 0

    if isinstance(value, bool):
        raise ValueError("config_version must be an integer")

    try:
        version = int(value)
    except (ValueError, TypeError) as e:
        raise ValueError("config_version must be an integer") from e

    if version < 0:
        raise ValueError("config_version cannot be negative")

    return version


def _toml_value(value) -> str:
    """Format a small set of values used by config migrations."""
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"

    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    raise TypeError(f"Unsupported TOML value type: {type(value).__name__}")


def _migration_lines(
    data: dict,
    from_version: int,
    to_version: int,
) -> list[str]:
    """Return missing configuration lines required by a migration."""
    lines = []

    for version in range(from_version + 1, to_version + 1):
        defaults = _MIGRATION_DEFAULTS.get(version, {})

        for key, value in defaults.items():
            if key not in data:
                lines.append(f"{key} = {_toml_value(value)}")

    return lines


def _write_config_atomically(path: Path, content: str) -> None:
    """Write configuration without replacing the original until complete."""
    temp = path.with_name(f".{path.name}.tmp")

    try:
        with open(temp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp, path)

    except Exception:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


def _migrate_config(data: dict, path: Path | None) -> dict:
    """Migrate an existing config file to the current version.

    The original file is backed up before any migration is written.
    If migration fails, the original remains untouched.
    """
    if path is None or not path.exists():
        return data

    try:
        version = _config_version(data)
    except ValueError as e:
        logger.warning("Invalid config version in %s: %s", path, e)
        return data

    if version > CONFIG_VERSION:
        logger.warning(
            "Config %s uses newer version %s; current version is %s. "
            "Configuration was not modified.",
            path,
            version,
            CONFIG_VERSION,
        )
        return data

    if version == CONFIG_VERSION:
        return data

    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()

        lines = _migration_lines(data, version, CONFIG_VERSION)

        lines.insert(0, f"config_version = {CONFIG_VERSION}")

        migrated = original.rstrip() + "\n\n" + "\n".join(lines) + "\n"

        backup = path.with_name(path.name + ".bak")

        if backup.exists():
            backup.unlink()

        with open(backup, "wb") as backup_file, open(path, "rb") as original_file:
            # Byte-for-byte backup before modifying the original.
            backup_file.write(original_file.read())
            backup_file.flush()
            os.fsync(backup_file.fileno())

        _write_config_atomically(path, migrated)

        migrated_data = tomllib.loads(migrated)

        logger.info(
            "Migrated config %s from version %s to version %s",
            path,
            version,
            CONFIG_VERSION,
        )

        return migrated_data

    except Exception as e:
        logger.error(
            "Config migration failed for %s: %s. "
            "Original was not replaced.",
            path,
            e,
        )
        return data


_file_config, _loaded_path = _find_config()
_file_config = _migrate_config(_file_config, _loaded_path)


def _env_list(name: str) -> list[str] | None:
    value = os.environ.get(name)
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def _env_int_list(name: str) -> list[int] | None:
    """Parse a comma-separated list of non-negative integers."""
    value = os.environ.get(name)
    if not value:
        return None

    try:
        items = [int(v.strip()) for v in value.split(",") if v.strip()]
    except (ValueError, TypeError):
        logger.warning(
            "Invalid integer list in %s=%r, using default",
            name,
            value,
        )
        return None

    if not items or any(v < 0 for v in items):
        logger.warning(
            "Invalid integer list in %s=%r, using default",
            name,
            value,
        )
        return None

    return items


def _file_int_list(key: str) -> list[int] | None:
    """Read a non-negative integer list from file configuration."""
    value = _file_config.get(key)

    if not isinstance(value, list) or not value:
        return None

    try:
        items = [int(v) for v in value]
    except (ValueError, TypeError):
        return None

    if any(v < 0 for v in items):
        return None

    return items


def _strip_api_suffix(url: str) -> str:
    """Poistaa /api/*-päätteen URL:sta (core.py lisää polun itse)."""
    url = url.rstrip("/")
    for suffix in ("/api/chat", "/api/generate", "/api/tags", "/api/embed"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


def _resolve_ollama_urls() -> list[str]:
    """Ratkaisee Ollama-URL-listat prioriteettijärjestyksessä."""
    env_urls = _env_list("OLLAMA_URLS")
    if env_urls:
        return [_strip_api_suffix(u) for u in env_urls]

    env_single = os.environ.get("OLLAMA_URL")
    if env_single:
        return [_strip_api_suffix(env_single)]

    if "ollama_urls" in _file_config:
        value = _file_config["ollama_urls"]
        if isinstance(value, str):
            return [_strip_api_suffix(value)]
        if isinstance(value, list) and value:
            return [_strip_api_suffix(str(v)) for v in value]

    if "ollama_url" in _file_config:
        return [_strip_api_suffix(str(_file_config["ollama_url"]))]

    return list(DEFAULTS["ollama_urls"])


def _to_bool(value) -> bool:
    """Muuntaa true/false/1/0/yes/no/on/off-arvot boolean-tyypiksi."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


_INT_KEYS = {
    "num_ctx",
    "num_predict",
    "repeat_last_n",
    "max_iterations",
}

_FLOAT_KEYS = {
    "temperature",
    "repeat_penalty",
    "ollama_health_cache_ttl",
    "ollama_health_timeout",
    "ollama_chat_timeout",
}


def _coerce_type(key: str, value):
    """Muuntaa arvon oikeaan tyyppiin. Virheellinen arvo → oletus + varoitus
    (aiemmin raaka merkkijono kaatoi käynnistyksen myöhemmin int()-kutsuun)."""
    caster = int if key in _INT_KEYS else float if key in _FLOAT_KEYS else None
    if caster is None:
        return value
    try:
        return caster(value)
    except (ValueError, TypeError):
        logger.warning(
            "Invalid value %r for '%s', using default",
            value,
            key,
        )
        return DEFAULTS[key]


def get(key: str):
    """Hakee asetuksen: env > tiedosto > oletus."""
    if key == "ollama_urls":
        return _resolve_ollama_urls()

    if key == "ollama_health_backoff":
        env_name = ENV_MAP.get(key)

        # Ympäristömuuttuja
        if env_name:
            env_value = _env_int_list(env_name)
            if env_value is not None:
                return env_value

        # TOML
        file_value = _file_int_list(key)
        if file_value is not None:
            return file_value

        # Oletus
        return list(DEFAULTS[key])

    env_name = ENV_MAP.get(key)

    if env_name and env_name in os.environ:
        value = os.environ[env_name]
        return (
            _to_bool(value)
            if key == "m_translation_enabled"
            else _coerce_type(key, value)
        )

    if key in _file_config:
        value = _file_config[key]
        return (
            _to_bool(value)
            if key == "m_translation_enabled"
            else _coerce_type(key, value)
        )

    if key in DEFAULTS:
        return DEFAULTS[key]

    raise KeyError(f"tuntematon asetus: {key}")


# ─── Julkiset vakiot ─────────────────────────────────────────

OLLAMA_URLS = get("ollama_urls")
OLLAMA_HEALTH_CACHE_TTL = float(get("ollama_health_cache_ttl"))
OLLAMA_HEALTH_TIMEOUT = float(get("ollama_health_timeout"))
OLLAMA_HEALTH_BACKOFF = tuple(get("ollama_health_backoff"))
OLLAMA_CHAT_TIMEOUT = float(get("ollama_chat_timeout"))

DEFAULT_MODEL = get("model")
TEMPERATURE = float(get("temperature"))
NUM_CTX = int(get("num_ctx"))
NUM_PREDICT = int(get("num_predict"))
REPEAT_PENALTY = float(get("repeat_penalty"))
REPEAT_LAST_N = int(get("repeat_last_n"))
STOP = list(get("stop") or [])
MAX_ITERATIONS = max(1, min(20, int(get("max_iterations"))))

# ─── Kielen ratkaisu ─────────────────────────────────────────

_config_language = os.environ.get("ASK_LANG")

if _config_language is None and "lang_code" in _file_config:
    _config_language = _file_config["lang_code"]

if _config_language is not None:
    LANGUAGE = resolve_language(_config_language)
else:
    LANGUAGE = resolve_language()

LANG_CODE = LANGUAGE.iso639_3

_ensure_system_prompts(
    LANG_CODE,
    LANGUAGE.name,
)

SYSTEM_PROMPT = get_system_prompt()

# Missä config ladattiin (debug-tarkoituksiin)
LOADED_FROM = _loaded_path

# Vanha nimi taaksepäin yhteensopivuudelle (ensimmäinen URL)
OLLAMA_URL = OLLAMA_URLS[0] if OLLAMA_URLS else DEFAULTS["ollama_urls"][0]
