"""
Language handling for ASK Ubuntu Mini.

Language priority:
    1. Explicit language from config.toml
    2. Operating system locale

SHL provides the canonical ISO 639-3 language identity.
"""

import locale
import logging
from typing import Optional

from shl.language_parser import LanguageParser


logger = logging.getLogger(__name__)


class LanguageInfo:
    """Resolved language information for ASK Ubuntu Mini."""

    def __init__(
        self,
        iso639_3: str,
        name: Optional[str],
        bcp47: Optional[str],
        source: str,
    ) -> None:
        self.iso639_3 = iso639_3
        self.name = name
        self.bcp47 = bcp47
        self.source = source


def get_os_locale() -> Optional[str]:
    """Return the operating system locale."""
    try:
        language, _ = locale.getlocale()
    except ValueError:
        return None

    return language


def resolve_language(config_language: Optional[str] = None) -> LanguageInfo:
    """
    Resolve the application language.

    Explicit configuration takes precedence over the OS locale.
    SHL resolves the final language identity to ISO 639-3.
    """
    source = "config"

    language = config_language

    if not language:
        language = get_os_locale()
        source = "os"

    if not language:
        language = "en"
        source = "default"

    parser = LanguageParser()
    parsed = parser.parse(language)

    logger.info(
        "Language resolved: %s (%s) from %s",
        parsed.iso639_3,
        parsed.name,
        source,
    )

    return LanguageInfo(
        iso639_3=parsed.iso639_3,
        name=parsed.name,
        bcp47=parsed.bcp47,
        source=source,
    )
