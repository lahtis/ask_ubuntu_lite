"""Testiympäristö: eristetty HOME, ei proxyja, shl-stubi jos kirjastoa ei ole."""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

# Projektin juuri importpolkuun
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Eristetty koti: config/i18n luovat hakemistoja importissa
os.environ["HOME"] = tempfile.mkdtemp(prefix="askhome-")
for k in list(os.environ):
    if k.startswith("SNAP") or k in ("OLLAMA_URL", "OLLAMA_URLS", "ASK_CONFIG",
                                      "ASK_LANG", "ASK_MT_ENABLED", "ASK_SOCKET"):
        os.environ.pop(k)
# Paikalliset testipalvelimet eivät saa kulkea proxyn kautta
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

try:
    import shl  # noqa: F401
except ImportError:
    def _mod(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    shl = _mod("shl")

    class LanguageValidator:
        def __init__(self, base_language="en", use_lite=True): pass
        def is_valid(self, code): return True

    shl.LanguageValidator = LanguageValidator
    shl.setup_logging = lambda **kw: None
    shl.get_logger = logging.getLogger
    shl.translate_text = lambda **kw: kw["text"]
    _mod("shl.engine")
    _mod("shl.engine.translation")
    cache = _mod("shl.engine.translation.cache")

    class TranslationCache:
        def __init__(self, ttl=3600): self._d = {}
        def get(self, text, src, dst): return self._d.get((text, src, dst))
        def set(self, text, result, src, dst): self._d[(text, src, dst)] = result

    cache.TranslationCache = TranslationCache
    exc = _mod("shl.engine.translation.exceptions")

    class TranslationError(Exception): pass
    class LanguageNotSupportedError(TranslationError): pass

    exc.TranslationError = TranslationError
    exc.LanguageNotSupportedError = LanguageNotSupportedError
