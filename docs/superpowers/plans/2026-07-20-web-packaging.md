# Web UI Packaging 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 Storyloom Web UI 构建 pip wheel + PyInstaller 便携可执行文件两种分发格式。

**架构：** 修改 pyproject.toml 提升 web 依赖、添加 console_scripts 入口点；新增 MANIFEST.in 包含静态文件；修改 i18n.py 支持 PyInstaller 运行时路径探测；新增 scripts/build.sh 一键构建。

**技术栈：** setuptools, build, PyInstaller, bash

---

### 任务 1：提升 web 依赖 + 添加 console_scripts 入口点

**文件：**
- 修改：`pyproject.toml`

- [ ] **步骤 1：修改 pyproject.toml**

将 web 可选依赖提升为主依赖，添加 `[project.scripts]` 入口点，添加 `[tool.setuptools.package-data]`：

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "storyloom"
version = "0.1.0"
description = "AI-powered interactive text fiction game engine"
requires-python = ">=3.10"
dependencies = [
    "httpx>=0.28.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
]

[project.scripts]
storyloom-web = "storyloom.web.server:main"

[tool.setuptools.package-data]
storyloom = ["web/static/**/*"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "--ignore=tests/prompt_lab"
```

- [ ] **步骤 2：验证 pip install 可解析**

```bash
pip install -e .
```

预期：安装成功，无报错。

- [ ] **步骤 3：验证 console_scripts 入口点**

```bash
which storyloom-web
storyloom-web --help
```

预期：`storyloom-web` 在 PATH 中，`--help` 显示 uvicorn 参数（由 uvicorn.run 的参数解析输出）。

- [ ] **步骤 4：Commit**

```bash
git add pyproject.toml
git commit -m "feat(packaging): promote web deps, add storyloom-web console_scripts entry point"
```

---

### 任务 2：创建 MANIFEST.in

**文件：**
- 创建：`MANIFEST.in`

- [ ] **步骤 1：创建 MANIFEST.in**

```
graft src/storyloom/web/static
```

- [ ] **步骤 2：验证 sdist 包含静态文件**

```bash
python -m build --sdist
tar -tzf dist/storyloom-0.1.0.tar.gz | grep "web/static"
```

预期：输出列出 `src/storyloom/web/static/index.html`、`src/storyloom/web/static/css/main.css`、`src/storyloom/web/static/js/*.js` 等文件。

- [ ] **步骤 3：验证 wheel 包含静态文件**

```bash
python -m build --wheel
unzip -l dist/storyloom-0.1.0-py3-none-any.whl | grep "web/static"
```

预期：输出列出所有静态文件。

- [ ] **步骤 4：Commit**

```bash
git add MANIFEST.in
git commit -m "feat(packaging): add MANIFEST.in with static file inclusion"
```

---

### 任务 3：添加 `__version__`

**文件：**
- 修改：`src/storyloom/__init__.py`

- [ ] **步骤 1：在 `__init__.py` 中添加 `__version__`**

在现有 `from storyloom.parser ...` 导入语句之后、`__all__` 之前插入：

```python
__version__ = "0.1.0"
```

- [ ] **步骤 2：验证版本号可导入**

```bash
python -c "from storyloom import __version__; print(__version__)"
```

预期：输出 `0.1.0`。

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/__init__.py
git commit -m "feat(packaging): add __version__ to storyloom package"
```

---

### 任务 4：i18n 路径适配 PyInstaller

**文件：**
- 修改：`src/storyloom/i18n.py:85-94`

- [ ] **步骤 1：修改 `_resolve_locale_dir()` 函数**

将现有的 `_resolve_locale_dir()` 替换为 `_get_locale_dir()`，加入 `sys.frozen` 检测：

```python
import sys
from pathlib import Path


def _get_locale_dir() -> Path:
    """Return the locale directory.

    Uses the explicitly-set directory from ``init_i18n()`` if provided;
    otherwise detects based on runtime environment (dev / PyInstaller).
    """
    global _locale_dir
    if _locale_dir is not None:
        return Path(_locale_dir)
    if getattr(sys, 'frozen', False):
        # PyInstaller: locale/ next to the executable
        return Path(sys.executable).parent / "locale"
    else:
        # Dev / pip: locale/ under repo root
        return Path(__file__).resolve().parents[3] / "locale"
```

同时更新 `_load_translator()` 中的调用——将 `_resolve_locale_dir()` 替换为 `str(_get_locale_dir())`：

```python
def _load_translator(language: str) -> None:
    """Load gettext translator for *language* into ``_translators``."""
    locale_lang = language.replace("-", "_")
    try:
        trans = gettext.translation(
            "storyloom", str(_get_locale_dir()),
            languages=[locale_lang, "en"],
            fallback=True,
        )
    except FileNotFoundError:
        trans = gettext.NullTranslations()
    _translators[language] = trans
```

- [ ] **步骤 2：运行现有测试确认没有破坏 i18n**

```bash
pytest tests/ -v --ignore=tests/test_api_client.py -k "i18n" 2>/dev/null || pytest tests/ -v --ignore=tests/test_api_client.py
```

预期：所有测试通过。

- [ ] **步骤 3：Commit**

```bash
git add src/storyloom/i18n.py
git commit -m "feat(packaging): add PyInstaller-aware locale path detection"
```

---

### 任务 5：创建构建脚本

**文件：**
- 创建：`scripts/build.sh`

- [ ] **步骤 1：创建 `scripts/build.sh`**

```bash
#!/bin/bash
# Build Storyloom Web UI — wheel + PyInstaller portable distribution
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

VERSION=$(python -c "from storyloom import __version__; print(__version__)")
OUTPUT_DIR="dist/storyloom-web-v${VERSION}"

echo "=== Storyloom Web UI Build v${VERSION} ==="

# 1. Install build tools
echo "[1/4] Installing build tools..."
pip install -q build pyinstaller

# 2. pip packages (wheel + sdist)
echo "[2/4] Building pip packages..."
python -m build

# 3. PyInstaller single-file executable
echo "[3/4] Building standalone executable..."
pyinstaller --onefile \
    --name storyloom-web \
    --add-data "locale:locale" \
    --add-data "src/storyloom/web/static:storyloom/web/static" \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    src/storyloom/web/__main__.py

# 4. Assemble release directory
echo "[4/4] Assembling release directory..."
mkdir -p "$OUTPUT_DIR"
cp dist/storyloom-web "$OUTPUT_DIR/"
cp -r locale "$OUTPUT_DIR/"
cp dist/*.whl dist/*.tar.gz "$OUTPUT_DIR/"

echo ""
echo "=== Done ==="
echo "Release: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR/"
```

- [ ] **步骤 2：设置可执行权限**

```bash
chmod +x scripts/build.sh
```

- [ ] **步骤 3：运行构建脚本**

```bash
./scripts/build.sh
```

预期：脚本成功完成，`dist/storyloom-web-v0.1.0/` 目录包含：
- `storyloom-web`（二进制）
- `locale/`（翻译文件）
- `storyloom-0.1.0-py3-none-any.whl`
- `storyloom-0.1.0.tar.gz`

- [ ] **步骤 4：Commit**

```bash
git add scripts/build.sh
git commit -m "feat(packaging): add build script for wheel + PyInstaller"
```

---

### 任务 6：冒烟测试

**文件：** 无代码变更，纯验证。

- [ ] **步骤 1：可执行文件基本启动测试**

```bash
./dist/storyloom-web --help 2>&1 | head -5
```

预期：输出 uvicorn 帮助信息（host/port 等参数），无崩溃。

- [ ] **步骤 2：服务启动 + health check**

在后台启动服务：

```bash
./dist/storyloom-web &
SERVER_PID=$!
sleep 3
curl -s http://localhost:8000/health
```

预期：`{"status":"ok"}`

- [ ] **步骤 3：静态文件服务验证**

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}" http://localhost:8000/
```

预期：`200 text/html; charset=utf-8`（或类似）。

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/static/css/main.css
```

预期：`200`。

- [ ] **步骤 4：停止测试服务器**

```bash
kill $SERVER_PID 2>/dev/null
```

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 对应任务 |
|----------|---------|
| §1 pip Package (pyproject.toml) | 任务 1 |
| §1 MANIFEST.in | 任务 2 |
| §2 PyInstaller 便携布局 | 任务 5（构建脚本实现） |
| §3 Build Script | 任务 5 |
| §4 i18n Path Adaptation | 任务 4 |
| §5.1 UserConfig (无需改动) | — |
| §5.2 `__version__` | 任务 3 |
| §5.3 Post-build smoke test | 任务 6 |

所有规格章节已覆盖。

### 2. 占位符扫描

无 "TODO"、"待定"、空步骤。每个步骤都有实际代码或命令。

### 3. 类型一致性

- `_get_locale_dir()` 返回 `Path`，调用处 `str(_get_locale_dir())` — 一致。
- `__version__ = "0.1.0"` 字符串 — 构建脚本用字符串比较，一致。
- `storyloom-web` 入口点调用 `main()` — `main()` 签名无参数，一致。
