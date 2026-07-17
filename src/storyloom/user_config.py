"""User configuration — JSON-backed preferences for language and API credentials.

Headless mode (app_dir=None) holds defaults in memory only.
Disk mode (app_dir=...) reads/writes config.json in the given directory.

Usage::

    # Headless — defaults only, no disk I/O (for testing)
    cfg = UserConfig()

    # Disk-backed — reads/writes <app_dir>/config.json
    cfg = UserConfig("/path/to/app_dir")
"""

import json
import os
import shutil
from pathlib import Path


class UserConfig:
    """User preferences backed by a JSON file."""

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
            # If bootstrap copied the example, read it below.
            # If not, create from defaults.

        if not path.exists():
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
