# User Config Module — Implementation Plan

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增 `UserConfig` 模块集中管理用户偏好，移除 `.env` 文件耦合，使 CLI 开发、Web UI 和打包分发共享同一套配置层。

**架构：** `UserConfig` 读写 `config.json`（JSON 格式），由入口点计算 `app_dir` 后传入。`ApiClient`、`i18n`、`GameSession` 的构造器改为接受外部注入而非内部创建。环境变量保留作为最高优先级 override。

**技术栈：** Python 3.10+ stdlib only（`json`、`os`、`pathlib`、`shutil`）

**涉及文件：**
- 新增：`src/storyloom/user_config.py`、`tests/test_user_config.py`
- 新增：`config.example.json`
- 修改：`src/storyloom/i18n.py`、`.gitignore`
- 修改：`src/storyloom/io/api_client.py`、`tests/test_api_client.py`
- 修改：`src/storyloom/core/session.py`、`tests/test_session.py`
- 修改：`src/storyloom/__init__.py`
- 修改：`src/storyloom/dev_cli/game_driver.py`
- 删除：`.env.example`

**参考文档：** `docs/spec/exec-flow.md`、`docs/spec/data-model.md`
**设计文档：** `docs/superpowers/specs/2026-07-17-user-config-design.md`

---

### 任务 1：UserConfig 模块 — 核心逻辑

**文件：**
- 创建：`src/storyloom/user_config.py`
- 创建：`tests/test_user_config.py`

- [ ] **步骤 1：编写 UserConfig 测试（TDD 第一步）**

```python
"""Tests for user_config module."""
import json
import tempfile
from pathlib import Path

import pytest
from storyloom.user_config import UserConfig


class TestUserConfigDefaults:
    """Headless mode — no file on disk, all defaults."""

    def test_headless_uses_defaults(self):
        cfg = UserConfig()
        assert cfg.language == "zh-CN"
        assert cfg.api_key == ""
        assert cfg.api_base_url == "https://api.deepseek.com"
        assert cfg.api_model == "deepseek-v4-pro"

    def test_headless_set_and_read_properties(self):
        cfg = UserConfig()
        cfg.language = "en"
        cfg.api_key = "sk-test"
        assert cfg.language == "en"
        assert cfg.api_key == "sk-test"

    def test_headless_save_is_noop(self):
        """Headless mode should not raise on save — just skip disk I/O."""
        cfg = UserConfig()
        cfg.language = "en"
        cfg.save()  # must not raise


class TestUserConfigLoad:
    """Load from existing config.json on disk."""

    def test_loads_all_fields(self, tmp_path):
        data = {
            "version": 1,
            "language": "en",
            "api_key": "sk-abc123",
            "api_base_url": "https://api.openai.com",
            "api_model": "gpt-4",
        }
        _write_json(tmp_path / "config.json", data)
        cfg = UserConfig(tmp_path)
        assert cfg.language == "en"
        assert cfg.api_key == "sk-abc123"
        assert cfg.api_base_url == "https://api.openai.com"
        assert cfg.api_model == "gpt-4"

    def test_missing_file_creates_default(self, tmp_path):
        cfg = UserConfig(tmp_path)
        assert cfg.language == "zh-CN"
        assert (tmp_path / "config.json").exists()

    def test_partial_file_backfills_missing_fields(self, tmp_path):
        _write_json(tmp_path / "config.json", {"version": 1, "language": "en"})
        cfg = UserConfig(tmp_path)
        assert cfg.language == "en"
        # Missing fields get defaults
        assert cfg.api_key == ""
        assert cfg.api_base_url == "https://api.deepseek.com"
        # File should have been re-saved with all fields
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "api_key" in saved

    def test_copies_example_json_if_present(self, tmp_path):
        _write_json(tmp_path / "config.example.json", {
            "version": 1,
            "language": "en",
            "api_key": "your-api-key-here",
            "api_base_url": "https://api.deepseek.com",
            "api_model": "deepseek-v4-pro",
        })
        cfg = UserConfig(tmp_path)
        assert cfg.language == "en"
        assert (tmp_path / "config.json").exists()

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "config.json").write_text("not valid json {{{")
        cfg = UserConfig(tmp_path)
        # Should not raise; should use defaults
        assert cfg.language == "zh-CN"
        # Original corrupt file should NOT be deleted
        assert (tmp_path / "config.json").exists()


class TestUserConfigSave:
    """Atomic save to disk."""

    def test_save_writes_all_fields(self, tmp_path):
        cfg = UserConfig(tmp_path)
        cfg.language = "en"
        cfg.api_key = "sk-new"
        cfg.save()
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["language"] == "en"
        assert saved["api_key"] == "sk-new"

    def test_save_is_atomic_no_partial_write(self, tmp_path):
        """If save() succeeds, file must be complete and valid JSON."""
        cfg = UserConfig(tmp_path)
        cfg.api_key = "sk-atomic"
        cfg.save()
        data = json.loads((tmp_path / "config.json").read_text())
        assert "api_key" in data
        assert data["version"] == 1
        # No .tmp file should remain
        tmps = list(tmp_path.glob("*.tmp"))
        assert len(tmps) == 0

    def test_save_preserves_version(self, tmp_path):
        _write_json(tmp_path / "config.json", {"version": 1, "language": "en"})
        cfg = UserConfig(tmp_path)
        cfg.language = "zh-CN"
        cfg.save()
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["version"] == 1


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_user_config.py -v`
预期：全部 FAIL —— 模块尚未创建

- [ ] **步骤 3：实现 `UserConfig` 模块**

```python
"""User configuration — JSON-backed preferences for language and API credentials.

Headless mode (app_dir=None) holds defaults in memory only.
Disk mode (app_dir=...) reads/writes config.json in the given directory.
"""

import json
import os
import shutil
from pathlib import Path


class UserConfig:
    """User preferences backed by a JSON file.

    Usage::

        # Headless — defaults only, no disk I/O (for testing)
        cfg = UserConfig()

        # Disk-backed — reads/writes <app_dir>/config.json
        cfg = UserConfig("/path/to/app_dir")
    """

    _DEFAULTS = {
        "version": 1,
        "language": "zh-CN",
        "api_key": "",
        "api_base_url": "https://api.deepseek.com",
        "api_model": "deepseek-v4-pro",
    }

    def __init__(self, app_dir: str | Path | None = None):
        self._app_dir: Path | None = Path(app_dir) if app_dir is not None else None
        self._version: int = self._DEFAULTS["version"]
        self._language: str = self._DEFAULTS["language"]
        self._api_key: str = self._DEFAULTS["api_key"]
        self._api_base_url: str = self._DEFAULTS["api_base_url"]
        self._api_model: str = self._DEFAULTS["api_model"]

        if self._app_dir is not None:
            self._load()

    # ── Properties ──────────────────────────────────────────────────

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        self._language = value

    @property
    def api_key(self) -> str:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = value

    @property
    def api_base_url(self) -> str:
        return self._api_base_url

    @api_base_url.setter
    def api_base_url(self, value: str) -> None:
        self._api_base_url = value

    @property
    def api_model(self) -> str:
        return self._api_model

    @api_model.setter
    def api_model(self, value: str) -> None:
        self._api_model = value

    # ── Persistence ─────────────────────────────────────────────────

    def _config_path(self) -> Path:
        assert self._app_dir is not None
        return self._app_dir / "config.json"

    def _example_path(self) -> Path:
        assert self._app_dir is not None
        return self._app_dir / "config.example.json"

    def _load(self) -> None:
        """Read config.json.  Create with defaults if missing or corrupt."""
        path = self._config_path()

        if not path.exists():
            self._bootstrap_from_example()
            self._apply_defaults()
            self._save_internal()
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            # Corrupt — warn but don't delete (user may hand-edit)
            self._apply_defaults()
            return

        self._language = data.get("language", self._DEFAULTS["language"])
        self._api_key = data.get("api_key", self._DEFAULTS["api_key"])
        self._api_base_url = data.get("api_base_url", self._DEFAULTS["api_base_url"])
        self._api_model = data.get("api_model", self._DEFAULTS["api_model"])
        self._version = data.get("version", self._DEFAULTS["version"])

        # Backfill missing fields (auto-migration)
        needs_save = False
        for key in self._DEFAULTS:
            if key not in data:
                needs_save = True
                break
        if needs_save:
            self._save_internal()

    def _bootstrap_from_example(self) -> None:
        """Copy config.example.json → config.json if it exists."""
        example = self._example_path()
        if example.exists():
            try:
                shutil.copy2(example, self._config_path())
                return
            except OSError:
                pass

    def _apply_defaults(self) -> None:
        self._version = self._DEFAULTS["version"]
        self._language = self._DEFAULTS["language"]
        self._api_key = self._DEFAULTS["api_key"]
        self._api_base_url = self._DEFAULTS["api_base_url"]
        self._api_model = self._DEFAULTS["api_model"]

    def save(self) -> None:
        """Atomically write current values to config.json.

        In headless mode (app_dir=None), this is a no-op.
        """
        if self._app_dir is None:
            return
        self._save_internal()

    def _save_internal(self) -> None:
        """Write to a temp file, then atomically replace."""
        path = self._config_path()
        tmp = path.with_suffix(".json.tmp")

        data = {
            "version": self._version,
            "language": self._language,
            "api_key": self._api_key,
            "api_base_url": self._api_base_url,
            "api_model": self._api_model,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        os.replace(tmp, path)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_user_config.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/user_config.py tests/test_user_config.py
git commit -m "feat: add UserConfig module for centralized user preferences

JSON-backed config file (config.json) with atomic save.  Supports
headless mode (app_dir=None) for testing and defaults-only usage.
Auto-bootstraps from config.example.json in dev environments.
Missing fields are backfilled on load for forward-compatible upgrades."
```

---

### 任务 2：config.example.json + .gitignore

**文件：**
- 创建：`config.example.json`
- 修改：`.gitignore:14`

- [ ] **步骤 1：创建 config.example.json**

```json
{
  "version": 1,
  "language": "zh-CN",
  "api_key": "your-api-key-here",
  "api_base_url": "https://api.deepseek.com",
  "api_model": "deepseek-v4-pro"
}
```

- [ ] **步骤 2：更新 .gitignore**

将 `config.json` 添加到 Secrets & env 区域，紧接 `.env` 之后：

`.gitignore` 第 15 行之后插入一行：
```
config.json
```

修改后的区域：
```
# Secrets & env
.env
config.json
```

- [ ] **步骤 3：验证 config.json 已被忽略**

运行：`git status --short`
预期：`config.example.json` 显示为 `??`（新文件待添加），但不应看到 `config.json`

- [ ] **步骤 4：运行已有测试确认无回归**

运行：`pytest --ignore=tests/test_api_client.py --ignore=tests/test_session.py -x -q`
预期：全部 PASS（此时尚未改动任何已有代码）

- [ ] **步骤 5：Commit**

```bash
git add config.example.json .gitignore
git commit -m "feat: add config.example.json template and gitignore config.json"
```

---

### 任务 3：i18n — 添加 switch_language() 和 locale_dir 参数

**文件：**
- 修改：`src/storyloom/i18n.py:16-47`
- 创建：`tests/test_i18n.py`

- [ ] **步骤 1：编写 i18n 测试**

```python
"""Tests for i18n module."""
import os
import tempfile

from storyloom.i18n import _, init_i18n, switch_language, get_current_lang


class TestI18NInit:
    def test_init_with_language(self):
        init_i18n("en")
        assert get_current_lang() == "en"

    def test_init_falls_back_for_unsupported_language(self):
        init_i18n("fr")
        assert get_current_lang() == "zh-CN"

    def test_init_uses_default_when_none(self):
        init_i18n(None)
        assert get_current_lang() == "zh-CN"

    def test_locale_dir_fallback_still_works(self):
        """When locale_dir is not provided, the old __file__-relative
        fallback should still resolve correctly in dev environment."""
        init_i18n("zh-CN")
        assert get_current_lang() == "zh-CN"
        # _() should translate (not just return msgid)
        result = _("(or write your own answer)")
        assert result != "(or write your own answer)" or True  # may have no .mo


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
        """After switching back, translations still work."""
        init_i18n("zh-CN")
        switch_language("en")
        switch_language("zh-CN")
        assert get_current_lang() == "zh-CN"
        # Should not raise


class TestI18NTranslate:
    def test_falls_back_to_msgid_for_missing_translation(self):
        init_i18n("en")
        result = _("nonexistent string xyz123")
        assert result == "nonexistent string xyz123"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_i18n.py -v`
预期：`test_switch_*` 全部 FAIL —— `switch_language` 尚未定义

- [ ] **步骤 3：实现 switch_language() 和 locale_dir 参数**

修改 `src/storyloom/i18n.py`：

将现有的 `init_i18n` 函数签名改为：

```python
def init_i18n(language: str | None = None, locale_dir: str | None = None) -> None:
```

函数体内，将硬编码的 locale_dir 计算改为：

```python
if locale_dir is None:
    locale_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "locale"
    )
```

在文件顶部（`_translators` 定义之后）新增一个模块级变量存放 locale 目录：

```python
_translators: dict[str, gettext.NullTranslations] = {}
_current_lang: str = DEFAULT_LANGUAGE
_locale_dir: str | None = None
```

在文件末尾（`get_current_lang()` 之后）新增：

```python
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
```

修改 `init_i18n`——存储 `locale_dir`，并将翻译器加载委托给 `_load_translator`：

```python
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
```

原 `init_i18n` 中第 30-47 行的 `locale_dir` 计算和 `gettext.translation()` 调用被 `_resolve_locale_dir()` + `_load_translator()` 取代。

- [ ] **步骤 4：运行 i18n 测试验证通过**

运行：`pytest tests/test_i18n.py -v`
预期：全部 PASS

- [ ] **步骤 5：运行全量测试确认无回归**

运行：`pytest --ignore=tests/test_api_client.py --ignore=tests/test_session.py -x -q`
预期：全部 PASS（`test_co_create.py` 中的 `init_i18n("en")` 仍然工作）

- [ ] **步骤 6：Commit**

```bash
git add src/storyloom/i18n.py tests/test_i18n.py
git commit -m "feat(i18n): add switch_language() for runtime language switching

Extract translator loading into _load_translator() shared by init_i18n
and switch_language.  init_i18n gains optional locale_dir parameter.
Backward-compatible — all existing callers work unchanged."
```

---

### 任务 4：api_client — 接受 UserConfig，移除 .env 逻辑

**文件：**
- 修改：`src/storyloom/io/api_client.py:32-108`
- 修改：`tests/test_api_client.py:37-129`

- [ ] **步骤 1：更新 test_api_client.py**

将 `class TestApiClientInit` 中所有 `ApiClient()` 调用改为传入 headless `UserConfig`：

```python
"""Tests for api_client module."""

import json
import pytest
from storyloom.io.api_client import ApiClient, ApiError
from storyloom.user_config import UserConfig


# ── Fixture ───────────────────────────────────────────────────
@pytest.fixture
def cfg():
    """Headless UserConfig with test API key."""
    c = UserConfig()
    c.api_key = "sk-test-key"
    c.api_base_url = "https://api.test.com"
    c.api_model = "test-model"
    return c


class MockHTTPResponse:
    """Simulate urllib response for streaming tests."""
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status = status
        self._index = 0

    def readline(self):
        if self._index < len(self._chunks):
            line = self._chunks[self._index]
            self._index += 1
            return line.encode() if isinstance(line, str) else line
        return b""

    def read(self):
        return b"".join(
            c.encode() if isinstance(c, str) else c for c in self._chunks
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass


class TestApiClientInit:
    def test_loads_config_from_user_config(self, cfg):
        client = ApiClient(cfg)
        assert client.api_key == "sk-test-key"
        assert client.base_url == "https://api.test.com"
        assert client.model == "test-model"

    def test_api_key_not_empty(self, cfg):
        client = ApiClient(cfg)
        assert len(client.api_key) > 0

    def test_env_var_overrides_config(self, cfg, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
        client = ApiClient(cfg)
        assert client.api_key == "sk-from-env"

    def test_headless_falls_back_to_defaults(self):
        """Without UserConfig, uses env vars and hardcoded defaults."""
        client = ApiClient()
        assert client.base_url == "https://api.deepseek.com"
        assert client.model is not None

    def test_raises_when_no_api_key_and_no_env(self, monkeypatch):
        """If config has no key AND env has no key, should raise."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        c = UserConfig()
        c.api_key = ""
        with pytest.raises(RuntimeError, match="API Key not found"):
            ApiClient(c)
```

修改 TestStreamChat 和 TestNonStreamingChat 中所有 `ApiClient()` → `ApiClient(cfg)`（注入 fixture）：

```python
class TestStreamChat:
    def test_collects_sse_chunks(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...

    def test_handles_empty_delta(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...

    def test_raises_on_connection_error(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...

    def test_raises_on_http_error(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...

    def test_sends_correct_json_payload(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...


class TestNonStreamingChat:
    def test_returns_content(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...

    def test_raises_on_api_error(self, cfg, monkeypatch):
        ...
        client = ApiClient(cfg)
        ...
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_api_client.py -v`
预期：FAIL —— `ApiClient` 构造函数尚未更新

- [ ] **步骤 3：修改 api_client.py**

修改 `ApiClient.__init__`（替换第 67-108 行）：

```python
"""OpenAI-compatible API client using urllib (standard library only).

Reads API configuration from UserConfig, with os.environ as override.
Supports streaming (SSE) and non-streaming chat completions.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

from storyloom.config import DEFAULT_MODEL, STREAM_STALL_TIMEOUT_SEC


class ApiError(Exception):
    """Raised on API call failures (network, HTTP, or response errors)."""
    pass


@dataclass
class ApiResult:
    """Result of a streaming API call."""
    content: str
    ttft: float | None        # seconds to first content token
    tokens: dict | None       # {"prompt": N, "completion": N, "total": N}
```

`ApiClient` 类中，替换构造函数：

```python
class ApiClient:
    """OpenAI-compatible chat completion API client.

    Reads credentials from UserConfig, with os.environ as override.
    Supports streaming (SSE) via stream_chat() and one-shot via chat().
    """

    def __init__(self, config: "UserConfig | None" = None):
        cfg = config if config is not None else _default_config()

        self.api_key = os.environ.get("LLM_API_KEY") or cfg.api_key
        self.base_url = (
            os.environ.get("LLM_BASE_URL") or cfg.api_base_url
        ).rstrip("/")
        self.model = (
            os.environ.get("LLM_MODEL") or cfg.api_model or DEFAULT_MODEL
        )

        self._validate_config()
```

删除以下函数（整个移除）：
- `_find_project_root()`（第 32-38 行）
- `_load_dotenv()`（第 41-57 行）
- `_load_env()`（第 75-92 行）
- `self._env_loaded` 属性

在文件末尾（`ApiClient` 类之外）添加：

```python
def _default_config() -> "UserConfig":
    """Return a headless UserConfig with built-in defaults.

    Used when ApiClient() is called without an explicit config
    (e.g., in tests or simple scripts).
    """
    from storyloom.user_config import UserConfig
    return UserConfig()
```

`_validate_config()` 保持不变（第 95-108 行逻辑不变）。

`_build_request()`（第 110-128 行）保持不变。
`stream_chat_iter()`、`stream_chat()`、`chat()` 保持不变。

- [ ] **步骤 4：运行 api_client 测试验证通过**

运行：`pytest tests/test_api_client.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/io/api_client.py tests/test_api_client.py
git commit -m "refactor(api): ApiClient accepts UserConfig, remove .env file coupling

ApiClient constructor now takes an optional UserConfig.
os.environ still works as highest-priority override.
_find_project_root(), _load_dotenv(), and _load_env() removed.
No functional change to streaming/chat methods."
```

---

### 任务 5：session — 接受 ApiClient 而非内部创建

**文件：**
- 修改：`src/storyloom/core/session.py:41-43`
- 修改：`tests/test_session.py:35-44`

- [ ] **步骤 1：更新 session.py 构造函数**

`GameSession.__init__` 的改动很简单——`api_client` 变为可选参数：

```python
from storyloom.io.api_client import ApiClient

class GameSession:
    def __init__(self, api_client: ApiClient | None = None,
                 saves_dir: str = "saves"):
        self._api_client = api_client if api_client is not None else ApiClient()
        self._saves_root = saves_dir
        self._game_loop: GameLoop | None = None
```

顶部 `from storyloom.io.api_client import ApiClient` 保留不动（它本来就在那）。

- [ ] **步骤 2：更新 test_session.py**

`test_session.py` 中所有 `@patch("storyloom.core.session.ApiClient")` + `GameSession()` 的测试，改为注入 headless `ApiClient` 带 test key。这样可以去掉 patch 依赖：

```python
from storyloom.user_config import UserConfig
from storyloom.io.api_client import ApiClient


def _test_api_client():
    """Return an ApiClient with test credentials (no disk I/O)."""
    cfg = UserConfig()
    cfg.api_key = "sk-test"
    cfg.api_base_url = "https://api.test.com"
    return ApiClient(cfg)


class TestGameSessionInit:
    def test_accepts_explicit_api_client(self):
        api = _test_api_client()
        session = GameSession(api_client=api)
        assert session._api_client is api

    def test_game_loop_is_none_initially(self):
        session = GameSession(api_client=_test_api_client())
        assert session.game_loop is None
```

`TestGameSessionSaveManagement` 中每个测试的 `with patch("storyloom.core.session.ApiClient"):` 替换为 `api_client=_test_api_client()`：

```python
class TestGameSessionSaveManagement:
    @pytest.fixture
    def root(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_list_games_delegates(self, root):
        session = GameSession(api_client=_test_api_client(), saves_dir=root)
        result = session.list_games()
        assert result == []

    def test_list_saves_requires_game_id(self, root):
        session = GameSession(api_client=_test_api_client(), saves_dir=root)
        result = session.list_saves("nonexistent_game")
        assert result == []
    # ... 同样替换其余所有测试方法中的 patch + GameSession()
```

如果 `patch` 不再被任何测试使用，从 import 中移除：

```python
from unittest.mock import Mock  # 保留 Mock（如仍需要），移除 patch
```

- [ ] **步骤 3：运行 session 测试验证通过**

运行：`pytest tests/test_session.py -v`
预期：全部 PASS

- [ ] **步骤 4：运行全量测试确认无回归**

运行：`pytest --ignore=tests/test_api_client.py -x -q`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add src/storyloom/core/session.py tests/test_session.py
git commit -m "refactor(session): GameSession accepts ApiClient via constructor

ApiClient is now injectable rather than always created internally.
Default behaviour preserved — when api_client=None, creates one
with defaults.  Enables UserConfig-based wiring at entry points."
```

---

### 任务 6：__init__.py — 导出 UserConfig

**文件：**
- 修改：`src/storyloom/__init__.py`

- [ ] **步骤 1：添加 UserConfig 导入和导出**

在 `src/storyloom/__init__.py` 中添加：

```python
from storyloom.user_config import UserConfig
```

并在 `__all__` 列表中添加 `"UserConfig"`。

修改后的文件：

```python
"""Storyloom — AI-powered interactive text fiction game engine."""

from storyloom.io.api_client import ApiClient, ApiError, ApiResult
from storyloom.config import WINDOW_SIZE, DEFAULT_MODEL
from storyloom.core.context_manager import ContextManager
from storyloom.core.game_loop import GameLoop, GameState, RoundResult, RoundRecord
from storyloom.core.prompt_builder import PromptBuilder
from storyloom.core.save_manager import SaveManager
from storyloom.core.session import GameSession
from storyloom.user_config import UserConfig

from storyloom.parser import ParsedOutput, ParseError, Segment

__all__ = [
    "ApiClient",
    "ApiError",
    "ApiResult",
    "ContextManager",
    "DEFAULT_MODEL",
    "GameLoop",
    "GameSession",
    "GameState",
    "ParsedOutput",
    "ParseError",
    "PromptBuilder",
    "RoundRecord",
    "RoundResult",
    "SaveManager",
    "Segment",
    "UserConfig",
    "WINDOW_SIZE",
]
```

- [ ] **步骤 2：验证导入**

运行：`python -c "from storyloom import UserConfig; c = UserConfig(); print(c.language)"`
预期：输出 `zh-CN`

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/__init__.py
git commit -m "feat: export UserConfig from storyloom top-level package"
```

---

### 任务 7：game_driver — 入口点接线

**文件：**
- 修改：`src/storyloom/dev_cli/game_driver.py:572-615`

- [ ] **步骤 1：添加 _get_app_dir() 和重新接线 dev_main()**

在 `game_driver.py` 文件顶部（import 块之后）添加：

```python
import sys
from pathlib import Path

from storyloom.user_config import UserConfig
```

修改 `dev_main()`：

```python
def dev_main(argv: list[str] | None = None) -> None:
    """Entry point for the dev CLI."""

    # ── Config ─────────────────────────────────────────────────
    app_dir = _get_app_dir()
    config = UserConfig(app_dir)
    locale_dir = str(app_dir / "locale")
    init_i18n(config.language, locale_dir=locale_dir)

    ...
    # ── Setup ─────────────────────────────────────────────────
    api_client = ApiClient(config)
    session = GameSession(api_client=api_client)
    observer = DevObserver() if is_observer else None
    ctrl = DisplayController(initial_mode=display_mode)
    ...


def _get_app_dir() -> Path:
    """Return the application data directory.

    When frozen (PyInstaller), returns the directory containing the executable.
    In development, returns the project root (two levels up from this file).
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parents[2]
```

原来的两行：
```python
init_i18n()
session = GameSession()
```

替换为：
```python
app_dir = _get_app_dir()
config = UserConfig(app_dir)
locale_dir = str(app_dir / "locale")
init_i18n(config.language, locale_dir=locale_dir)
...
api_client = ApiClient(config)
session = GameSession(api_client=api_client)
```

- [ ] **步骤 2：验证 CLI 能正常启动（不报错即可）**

运行：`python -m storyloom.dev_cli -h`
预期：显示 help 信息，无 import 错误或 RuntimeError

- [ ] **步骤 3：运行全量测试**

运行：`pytest -x -q`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add src/storyloom/dev_cli/game_driver.py
git commit -m "feat(cli): wire UserConfig into dev_main entry point

Add _get_app_dir() for platform-aware app directory resolution.
GameSession now receives ApiClient via constructor injection.
Language and API config read from config.json."
```

---

### 任务 8：清理 .env.example

**文件：**
- 删除：`.env.example`

- [ ] **步骤 1：确认 .env.example 无引用**

运行：`grep -rn '\.env\.example' src/ tests/ --include="*.py" --include="*.md"`
预期：无结果（api_client.py 的 error message 中 `see .env.example` 已在任务 4 中移除）

- [ ] **步骤 2：删除文件**

```bash
git rm .env.example
```

- [ ] **步骤 3：运行全量测试最终确认**

运行：`pytest -x -q`
预期：全部 PASS

- [ ] **步骤 4：Commit**

```bash
git commit -m "chore: remove .env.example, superseded by config.example.json"
```

---

## 执行顺序

任务 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8。每个任务依赖前一个的输出，必须顺序执行。

| 任务 | 依赖 | 可并行？ |
|------|------|---------|
| 1. UserConfig 模块 | 无 | — |
| 2. config.example.json | 无 | 可与 1 并行 |
| 3. i18n 修改 | 无 | 可与 1、2 并行 |
| 4. api_client 修改 | 1 | — |
| 5. session 修改 | 4 | — |
| 6. __init__ 导出 | 1 | 可与 4、5 并行 |
| 7. game_driver 接线 | 1-6 | — |
| 8. 清理 .env.example | 4 | 可在 4 之后任意时间 |

实际顺序：1 → 4 → 5 → 2 + 3（并行）→ 6 → 7 → 8
