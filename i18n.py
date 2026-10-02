"""UI localization using the SHL library.

The language code is read from ask-ubuntu's own config file
(config.toml -> lang_code). Translations are stored in
<config dir>/locales/{lang}.json (see appenv.app_config_dir).

Usage:
    from i18n import L
    print(L("Ask Ubuntu Mini"))
    print(L("Calling tool: {}").format(name))
"""
import json
import os
import re
import threading
from collections import Counter
from pathlib import Path

import appenv
import config

# SHL library
from shl import (
    LanguageValidator,
    setup_logging,
    get_logger,
    translate_text,
)
from shl.engine.translation.cache import TranslationCache
from shl.engine.translation.exceptions import (
    TranslationError,
    LanguageNotSupportedError,
)

# Logging
_level = "DEBUG" if os.environ.get("ASK_DEBUG") == "1" else "WARNING"
setup_logging(console_level=_level)
logger = get_logger(__name__)

# Translation storage location (primary, writable)
LOCALES_DIR = appenv.app_config_dir(create=False) / "locales"
try:
    LOCALES_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    logger.warning("Cannot create %s (%s); translations won't be saved", LOCALES_DIR, e)

# Source language (UI texts are written in English)
SOURCE_LANG = "en"
FALLBACK_LANG = "en"

_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")


def _same_placeholders(source: str, translated: str) -> bool:
    """Käännöksen {}-paikkamerkit pitää olla samat kuin lähdetekstissä.

    Muuten kutsuja .format(...) voisi kaatua (KeyError/IndexError) tai
    jättää arvon pois.
    """
    return (Counter(_PLACEHOLDER_RE.findall(source))
            == Counter(_PLACEHOLDER_RE.findall(translated)))


class UILocalization:
    """Thin wrapper around SHL for the ask-ubuntu project."""

    def __init__(self, target_language: str = "eng"):
        self.source_language = SOURCE_LANG
        self.fallback_language = FALLBACK_LANG
        # Kielikoodista tulee tiedostonimi → siistitään ennen käyttöä
        self.target_language = config.normalize_lang(target_language or FALLBACK_LANG)

        self._lock = threading.RLock()
        self._cache = TranslationCache(ttl=3600)
        self._validator = LanguageValidator(
            base_language=self.fallback_language,
            use_lite=True,
        )
        self._translations: dict[str, str] = {}
        self._failed: set[str] = set()

        # Validointi ENNEN tiedoston lukua
        if not self._validator.is_valid(self.target_language):
            logger.warning(
                "Unknown language code '%s', using fallback '%s'",
                self.target_language, self.fallback_language,
            )
            self.target_language = self.fallback_language

        self._load_translations()

    def _locale_file(self) -> Path:
        return LOCALES_DIR / f"{self.target_language}.json"

    def _candidate_files(self) -> list[Path]:
        """Ensisijainen tiedosto + vanhat sijainnit (~/.config/ask-ubuntu-mini)."""
        name = f"{self.target_language}.json"
        files = [self._locale_file()]
        for d in appenv.config_search_dirs():
            f = d / "locales" / name
            if f not in files:
                files.append(f)
        return files

    def _load_translations(self):
        for f in self._candidate_files():
            if not f.exists():
                continue
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load translations from %s: %s", f, e)
                continue
            if isinstance(data, dict):
                self._translations = {
                    k: v for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, str)
                    and v.strip() and _same_placeholders(k, v)
                }
                return
        self._translations = {}

    def _save_translations(self):
        """Atomista kirjoitus: kaatuminen kesken ei riko JSON-tiedostoa."""
        f = self._locale_file()
        tmp = f.with_name(f.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(self._translations, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, f)
        except OSError as e:
            logger.error("Failed to save translations: %s", e)

    def _translate(self, text: str) -> str:
        cached = self._cache.get(text, self.source_language, self.target_language)
        if cached:
            return cached

        result = translate_text(
            text=text,
            target_lang=self.target_language,
            source_lang=self.source_language,
            placeholder_pattern=r"\{[^}]*\}|\[[^\]]*\]",
            raise_on_language_not_supported=True,
        )

        if result:
            self._cache.set(text, result, self.source_language, self.target_language)
        return result or text

    def _mark_failed(self, text: str) -> str:
        with self._lock:
            self._failed.add(text)
        return text

    def L(self, text: str) -> str:
        """Translate UI text. Returns the original if translation fails."""
        if not text:
            return text

        if self.target_language == self.source_language:
            return text

        with self._lock:
            existing = self._translations.get(text)
            if existing and existing.strip():
                return existing
            if text in self._failed:
                return text

        if not config.get("m_translation_enabled"):
            return self._mark_failed(text)

        try:
            translated = self._translate(text)   # hidas: ei lukon sisällä
        except LanguageNotSupportedError:
            return self._mark_failed(text)
        except TranslationError as e:
            logger.error("Translation failed: %s", e)
            return self._mark_failed(text)
        except Exception as e:
            logger.error("Unexpected translation error: %s", e)
            return self._mark_failed(text)

        if not translated or translated == text:
            return self._mark_failed(text)

        if not _same_placeholders(text, translated):
            logger.warning("Rejected translation with altered placeholders: %r", text)
            return self._mark_failed(text)

        with self._lock:
            self._translations[text] = translated
            self._save_translations()
        return translated


# ─── Global instance ─────────────────────────────────────────

_loc = UILocalization(target_language=config.LANG_CODE)


def L(text: str) -> str:
    """Short wrapper: translates text to the user's language."""
    return _loc.L(text)


def get_language() -> str:
    return _loc.target_language


def get_stats() -> dict:
    """Return statistics (for debugging)."""
    return {
        "language": _loc.target_language,
        "source": _loc.source_language,
        "translations": len(_loc._translations),
        "failed": len(_loc._failed),
        "locales_dir": str(LOCALES_DIR),
    }
