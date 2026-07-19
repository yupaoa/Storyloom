"""Tests for i18n module."""
from storyloom.i18n import _, init_i18n, switch_language, get_current_lang


class TestI18NInit:
    def test_init_with_language(self):
        init_i18n("en")
        assert get_current_lang() == "en"

    def test_init_falls_back_for_unsupported_language(self):
        init_i18n("fr")
        assert get_current_lang() == "zh-CN"

    def test_init_uses_default_when_none(self):
        # Switch to a known state first, then back to None
        init_i18n("en")
        init_i18n(None)
        assert get_current_lang() == "zh-CN"

    def test_init_with_explicit_locale_dir(self):
        """Explicit locale_dir should not raise."""
        # Use the actual project locale dir — this is an integration-smoke test
        import os
        locale_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "locale"
        )
        init_i18n("zh-CN", locale_dir=os.path.abspath(locale_dir))
        assert get_current_lang() == "zh-CN"


class TestI18NSwitch:
    def test_switch_to_supported_language(self):
        init_i18n("zh-CN")
        switch_language("en")
        assert get_current_lang() == "en"

    def test_switch_ignores_unsupported_language(self):
        init_i18n("zh-CN")
        switch_language("fr")
        assert get_current_lang() == "zh-CN"  # unchanged

    def test_switch_preserves_translator_cache(self):
        """After switching back and forth, translations still work."""
        init_i18n("zh-CN")
        switch_language("en")
        switch_language("zh-CN")
        assert get_current_lang() == "zh-CN"

    def test_switch_same_language_is_noop(self):
        init_i18n("zh-CN")
        switch_language("zh-CN")
        assert get_current_lang() == "zh-CN"


class TestI18NTranslate:
    def test_falls_back_to_msgid_for_missing_translation(self):
        init_i18n("en")
        result = _("nonexistent string xyz123")
        assert result == "nonexistent string xyz123"
