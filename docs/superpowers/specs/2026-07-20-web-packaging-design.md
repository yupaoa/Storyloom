# Web UI Packaging Design

> 2026-07-20 | Status: Draft | Author: Slev

## Overview

Package Storyloom Web UI for distribution, excluding dev-cli.
Two distribution formats for two user groups:

| Format | Target User | Artifact |
|--------|-------------|----------|
| pip wheel | Developers with Python 3.10+ | `.whl`, `.tar.gz` |
| Standalone binary | End users (no Python required) | Single executable via PyInstaller |

Distribution channel: **GitHub Releases**. Build: **manual local** (migrate to CI later).

## §1 pip Package

### pyproject.toml changes

```toml
[project]
dependencies = [
    "httpx>=0.28.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
]
# web optional-deps group REMOVED (promoted to main deps)

[project.scripts]
storyloom-web = "storyloom.web.server:main"

[tool.setuptools.package-data]
storyloom = ["web/static/**/*"]
```

- `console_scripts` entry point so `pip install` produces a `storyloom-web` command.
- Static files included via `package_data`. No locale in the wheel — pip is the developer channel; locale ships alongside the PyInstaller bundle.

### MANIFEST.in (new)

```
graft src/storyloom/web/static
```

## §2 PyInstaller Portable Layout

### Distribution directory structure

```
storyloom-web-v0.1.0/
├── storyloom-web          # Single-file executable
├── locale/                # i18n translations
│   └── zh_CN/LC_MESSAGES/
│       ├── storyloom.po
│       └── storyloom.mo
├── saves/                 # Auto-created on first run
├── storyloom-0.1.0-py3-none-any.whl   # pip package alongside
└── storyloom-0.1.0.tar.gz
```

### PyInstaller flags

- `--onefile` — single binary
- `--add-data "locale:locale"` — locale next to exe at runtime
- `--add-data "src/storyloom/web/static:storyloom/web/static"` — static files in bundle
- `--hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto` — uvicorn's implicit imports (uvloop, httptools, etc.)

## §3 Build Script

`scripts/build.sh` — one command to produce all artifacts:

```bash
#!/bin/bash
set -e
VERSION=$(python -c "from storyloom import __version__; print(__version__)")
OUTPUT_DIR="dist/storyloom-web-v${VERSION}"

pip install build pyinstaller
python -m build
pyinstaller --onefile \
    --name storyloom-web \
    --add-data "locale:locale" \
    --add-data "src/storyloom/web/static:storyloom/web/static" \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    src/storyloom/web/__main__.py

mkdir -p "$OUTPUT_DIR"
cp dist/storyloom-web "$OUTPUT_DIR/"
cp -r locale "$OUTPUT_DIR/"
cp dist/*.whl dist/*.tar.gz "$OUTPUT_DIR/"
echo "Done → $OUTPUT_DIR"
```

## §4 i18n Path Adaptation

Modify `src/storyloom/i18n.py` to detect runtime environment:

```python
def _get_locale_dir() -> Path:
    if getattr(sys, 'frozen', False):
        # PyInstaller: locale/ next to exe
        return Path(sys.executable).parent / "locale"
    else:
        # Dev / pip: locale/ in repo root
        return Path(__file__).resolve().parents[3] / "locale"
```

## §5 Misc

### 5.1 UserConfig path discovery

Existing `UserConfig` priority chain `env > cwd/config.json > ~/.config/storyloom/config.json`
already covers the portable layout — user drops `config.json` next to the executable.

### 5.2 Version attribute

Add to `src/storyloom/__init__.py`:
```python
__version__ = "0.1.0"
```

### 5.3 Post-build smoke test

1. `./dist/storyloom-web --help` — exits cleanly (uvicorn arg parsing)
2. Start server, `curl http://localhost:8000/health` → `{"status": "ok"}`
3. `curl http://localhost:8000/` → serves `index.html` with correct `Content-Type`

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | dependencies promoted, `[project.scripts]`, `[tool.setuptools.package-data]` |
| `MANIFEST.in` | New — include static files |
| `src/storyloom/__init__.py` | Add `__version__` |
| `src/storyloom/i18n.py` | `_get_locale_dir()` — PyInstaller-aware path |
| `scripts/build.sh` | New — one-shot build script |
