"""Internationalization support via gettext.

Provides module-level _() function for UI string translation.
Call init_i18n() once at startup.  Use switch_language() for
runtime language changes.
"""

import gettext
import os

from storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

_translators: dict[str, gettext.NullTranslations] = {}
_current_lang: str = DEFAULT_LANGUAGE
_locale_dir: str | None = None


def init_i18n(language: str | None = None, locale_dir: str | None = None) -> None:
    """Initialize gettext for the given language.

    Must be called once at startup, before any _() calls.
    After calling, _() is available globally for all modules.

    Args:
        language: Language code (zh-CN, en). Falls back to DEFAULT_LANGUAGE.
        locale_dir: Path to the locale/ directory.  If None, uses the
                    __file__-relative fallback (dev environment).
    """
    global _current_lang, _locale_dir
    _locale_dir = locale_dir
    _current_lang = language or DEFAULT_LANGUAGE
    if _current_lang not in SUPPORTED_LANGUAGES:
        _current_lang = DEFAULT_LANGUAGE

    _load_translator(_current_lang)


def switch_language(language: str) -> None:
    """Switch active language at runtime without re-init.

    Uses the same locale directory set during ``init_i18n()``.
    Translators are lazy-loaded — first call to ``_()`` after a switch
    loads the new language if not already cached.

    Args:
        language: Language code (zh-CN, en).  If unsupported, the
                  current language is left unchanged.
    """
    global _current_lang
    if language not in SUPPORTED_LANGUAGES:
        return
    if language == _current_lang:
        return

    _current_lang = language

    if language not in _translators:
        _load_translator(language)


def get_current_lang() -> str:
    """Return the currently active language code."""
    return _current_lang


def _(message: str) -> str:
    """Mark string for translation.

    Args:
        message: English source string (msgid).

    Returns:
        Translated string in the current language, or the original
        if no translation is available.
    """
    trans = _translators.get(_current_lang)
    if trans is None:
        return message
    return trans.gettext(message)


# ── Internal helpers ──────────────────────────────────────────────


def _resolve_locale_dir() -> str:
    """Return the locale directory.

    Uses the explicitly-set directory from ``init_i18n()`` if provided;
    otherwise falls back to the __file__-relative path (dev environment).
    """
    global _locale_dir
    if _locale_dir is not None:
        return _locale_dir
    return os.path.join(os.path.dirname(__file__), "..", "..", "locale")


def _load_translator(language: str) -> None:
    """Load gettext translator for *language* into ``_translators``."""
    locale_lang = language.replace("-", "_")
    try:
        trans = gettext.translation(
            "storyloom", _resolve_locale_dir(),
            languages=[locale_lang, "en"],
            fallback=True,
        )
    except FileNotFoundError:
        trans = gettext.NullTranslations()
    _translators[language] = trans
