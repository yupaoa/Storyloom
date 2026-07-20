#!/bin/bash
# Build Storyloom Web UI — wheel + PyInstaller portable distribution
# Run on the target platform (Linux → ELF, Windows → .exe, macOS → Mach-O)
set -e

PYTHON="${PYTHON:-python3}"
# Fallback to 'python' on Windows / if 'python3' not found
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON="python"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

VERSION=$($PYTHON -c "from storyloom import __version__; print(__version__)")
PYI_FLAGS=""
BIN_NAME="storyloom-web"
OUTPUT_DIR="dist/storyloom-web-v${VERSION}"

# Platform-specific binary extension
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)  BIN_NAME="storyloom-web.exe" ;;
    Darwin)                ;;  # macOS: no extension
    Linux)                 ;;  # Linux: no extension
esac

echo "=== Storyloom Web UI Build v${VERSION} ==="

# 1. Install project + build tools (PyInstaller needs deps to discover imports)
echo "[1/6] Installing project + build tools..."
$PYTHON -m pip install -q -e . build pyinstaller wheel 2>/dev/null || \
    $PYTHON -m pip install -q --break-system-packages -e . build pyinstaller wheel

# 2. Compile i18n (.po → .mo)
echo "[2/6] Compiling translations..."
$PYTHON -c "from storyloom.i18n_compile import compile_all; compile_all('locale')"

# 3. pip packages (wheel + sdist)
echo "[3/6] Building pip packages..."
$PYTHON -m build --no-isolation

# 4. PyInstaller single-file executable
echo "[4/6] Building standalone executable..."
$PYTHON -m PyInstaller --onefile $PYI_FLAGS \
    --name "$BIN_NAME" \
    --add-data "locale:locale" \
    --add-data "src/storyloom/web/static:storyloom/web/static" \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    src/storyloom/web/__main__.py

# 5. Assemble release directory
echo "[5/6] Assembling release directory..."
mkdir -p "$OUTPUT_DIR"
cp "dist/$BIN_NAME" "$OUTPUT_DIR/"
cp -r locale "$OUTPUT_DIR/"
cp dist/*.whl dist/*.tar.gz "$OUTPUT_DIR/"

# 6. Create zip for GitHub Release upload
echo "[6/6] Creating release archive..."
ZIP_NAME="storyloom-web-v${VERSION}-$(uname -s)"
$PYTHON -c "import shutil; shutil.make_archive('dist/$ZIP_NAME', 'zip', 'dist', 'storyloom-web-v${VERSION}')"

echo ""
echo "=== Done ==="
echo "Release dir:  $OUTPUT_DIR"
echo "GitHub asset: dist/${ZIP_NAME}.zip"
ls -lh "$OUTPUT_DIR/"
