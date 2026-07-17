# User Config Module — Design Spec

> **Date:** 2026-07-17  
> **Status:** Approved  
> **Goal:** Introduce a `UserConfig` module that centralizes user preferences  
> (language, API credentials) and removes `.env`-file coupling, so the same  
> config layer serves CLI development, Web UI, and packaged distributions  
> without per-entry-point duplication.

## §1 Motivation

Today the project has no unified configuration layer:

- Language is hard-coded to `zh-CN` in `dev_main()`.
- API credentials are loaded from a `.env` file via `api_client._find_project_root()`,
  which walks up from `__file__` looking for `.git` — a pattern that does not survive
  packaging.
- There is no persistence for user preferences; every session starts from defaults.

## §2 Design

### 2.1 New module: `src/storyloom/user_config.py`

A single `UserConfig` class that owns a JSON file on disk and exposes typed
properties for every configuration key.

#### Location

The caller provides `app_dir` — the directory where `config.json` lives.
`UserConfig` never computes the path itself.  Each entry point (CLI dev, Web UI,
packaged bootstrap) computes its own `app_dir` and passes it in.

```python
config = UserConfig(app_dir)   # reads <app_dir>/config.json
```

#### `config.json` schema

```json
{
  "version": 1,
  "language": "zh-CN",
  "api_key": "",
  "api_base_url": "https://api.deepseek.com",
  "api_model": "deepseek-v4-pro"
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `version` | int | 1 | Config format version (independent of `SAVE_VERSION`) |
| `language` | str | `"zh-CN"` | Locale code (hyphen-separated, e.g. `zh-CN`, `en`) |
| `api_key` | str | `""` | LLM API key |
| `api_base_url` | str | `"https://api.deepseek.com"` | API endpoint |
| `api_model` | str | `"deepseek-v4-pro"` | Model name |

#### API

```python
class UserConfig:
    def __init__(self, app_dir: str | Path) -> None:
        """Read config.json from app_dir. Create with defaults if missing."""

    def save(self) -> None:
        """Atomically write current values back to config.json."""

    # Properties — read/write, persisted on save()
    language: str
    api_key: str
    api_base_url: str
    api_model: str
```

#### `load()` behaviour

1. `config.json` exists → read, validate `version`, load fields.
   Missing fields are backfilled with defaults and the file is re-saved
   (auto-migration).
2. `config.json` missing → if `config.example.json` exists (dev environment),
   copy it as `config.json` and load. Otherwise create with all defaults and save.
3. Corrupt JSON → log a warning, start from defaults, **do not** auto-delete
   (unlike save files, the user may hand-edit config and want to recover).

#### `save()` behaviour

Atomic write via temp file + `os.replace` (same strategy as `SaveManager`).

### 2.2 Modified module: `src/storyloom/i18n.py`

Add `switch_language(language: str)` — changes active locale without re-init.
All previously loaded translators stay resident in `_translators`.

`init_i18n()` gains an explicit `locale_dir: str` parameter so the caller
controls where `.mo` files are found.

### 2.3 Modified module: `src/storyloom/io/api_client.py`

- Constructor accepts `UserConfig` instead of discovering `.env` internally.
- Priority: `os.environ` > `UserConfig` > default.
- `_find_project_root()` and `_load_dotenv()` are removed.
- `.env` is **no longer read** by the engine.  Developers who prefer a `.env`
  file can still use environment variables (`export $(cat .env | xargs)`).

### 2.4 Modified module: `src/storyloom/core/session.py`

`GameSession.__init__` accepts `api_client: ApiClient` rather than creating
one internally.  The caller wires `UserConfig → ApiClient → GameSession`.

### 2.5 App-directory helper (entry points)

```python
import sys
from pathlib import Path

def _get_app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent       # packaged
    else:
        return Path(__file__).resolve().parents[2]  # dev (src/storyloom/xxx → project root)
```

This lives in each entry point (CLI, Web) — not in `UserConfig`.

### 2.6 File inventory

| File | Action |
|------|--------|
| `src/storyloom/user_config.py` | **New** |
| `config.example.json` | **New** (project root, tracked in git) |
| `.gitignore` | Add `config.json` |
| `src/storyloom/i18n.py` | Add `switch_language()`; `init_i18n` takes `locale_dir` |
| `src/storyloom/io/api_client.py` | Accept `UserConfig`; delete `_find_project_root` / `_load_dotenv` |
| `src/storyloom/core/session.py` | Accept `ApiClient` in constructor |
| `src/storyloom/dev_cli/game_driver.py` | Wire `UserConfig` → entry point |
| `.env.example` | **Delete** (superseded by `config.example.json`) |

## §3 Entry-point call chain (post-implementation)

```
app_dir = _get_app_dir()
locale_dir = app_dir / "locale"

config = UserConfig(app_dir)                         # loads config.json
init_i18n(config.language, locale_dir=str(locale_dir))
api_client = ApiClient(config)
session = GameSession(api_client)
```

All three entry points (CLI dev, Web UI, packaged bootstrap) share this chain.
Only `_get_app_dir()` differs.  `locale_dir` derives from `app_dir` the same
way in every case — in dev it resolves to `<project root>/locale`, in a packaged
build to `<exe dir>/locale`.

## §4 Non-goals

- Per-game configuration (state variables, outline preferences — these belong in save data).
- GUI state persistence (window size, theme, font — handled by the UI layer later).
- Multi-user or server-side configuration.  Storyloom is single-user, single-instance.
- Network-downloadable language packs.  All `.mo` files ship with the install package.

## §5 Impact on existing behaviour

| What | Before | After |
|------|--------|-------|
| Language default | `zh-CN` hardcoded | `zh-CN` from `config.json` |
| API key source | `.env` file near `.git` | `config.json` alongside app |
| `.env` file | Required | Ignored (env vars still work) |
| Dev CLI flow | `dev_main()` does everything inline | `dev_main()` wires config first |

No engine behaviour changes.  All changes are at the wiring / entry-point level.
