#!/bin/bash
# Build Storyloom Web UI — wheel + PyInstaller portable distribution
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

VERSION=$(python3 -c "from storyloom import __version__; print(__version__)")
OUTPUT_DIR="dist/storyloom-web-v${VERSION}"

echo "=== Storyloom Web UI Build v${VERSION} ==="

# 1. Install build tools
echo "[1/4] Installing build tools..."
pip install --break-system-packages -q build pyinstaller

# 2. pip packages (wheel + sdist)
echo "[2/4] Building pip packages..."
python3 -m build --no-isolation

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
