"""Internationalization support via gettext.

Provides module-level _() function for UI string translation.
Call init_i18n() once at startup.
"""

import gettext
import os

from storyloom.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

_translators: dict[str, gettext.NullTranslations] = {}
_current_lang: str = DEFAULT_LANGUAGE


def init_i18n(language: str | None = None) -> None:
    """Initialize gettext for the given language.

    Must be called once at startup, before any _() calls.
    After calling, _() is available globally for all modules.

    Args:
        language: Language code (zh-CN, en). Falls back to DEFAULT_LANGUAGE.
    """
    global _current_lang
    _current_lang = language or DEFAULT_LANGUAGE
    if _current_lang not in SUPPORTED_LANGUAGES:
        _current_lang = DEFAULT_LANGUAGE

    locale_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "locale"
    )

    # gettext uses underscore-separated locale names (zh_CN).
    # Normalize from our hyphen-separated codes (zh-CN).
    locale_lang = _current_lang.replace("-", "_")

    try:
        trans = gettext.translation(
            "storyloom", locale_dir,
            languages=[locale_lang, "en"],
            fallback=True,
        )
    except FileNotFoundError:
        trans = gettext.NullTranslations()

    _translators[_current_lang] = trans


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
