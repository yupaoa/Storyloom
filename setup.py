"""Build hook — compile .po → .mo during ``pip install``.

Users never need ``msgfmt`` or any manual step.  Everything happens
automatically inside the build phase.
"""

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.develop import develop as _develop
from setuptools.command.editable_wheel import editable_wheel as _editable_wheel


def _compile_mo_files() -> None:
    """Compile all .po files under the project ``locale/`` directory
    and generate the frontend JS translation dictionary."""
    project_root = Path(__file__).resolve().parent
    src = project_root / "src"

    # Load i18n_compile directly (avoids storyloom.__init__ → httpx import
    # chain, which fails in isolated build environments like editable_wheel).
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "storyloom.i18n_compile",
        str(src / "storyloom" / "i18n_compile.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    compile_all = mod.compile_all
    generate_js_dict = mod.generate_js_dict

    locale_dir = project_root / "locale"
    if locale_dir.is_dir():
        compiled = compile_all(str(locale_dir))
        if compiled:
            print(f"[i18n] compiled {len(compiled)} .mo file(s)")

    # Generate frontend T dictionary from .po files
    js_out = project_root / "src" / "storyloom" / "web" / "static" / "js" / "i18n-dict.js"
    generate_js_dict(str(locale_dir), str(js_out))
    print(f"[i18n] generated {js_out}")


class build_py(_build_py):
    """Custom build_py — compiles gettext catalogs + frontend JS dict."""

    def run(self) -> None:
        _compile_mo_files()
        super().run()


class develop(_develop):
    """Custom develop — same hook for editable installs (legacy path)."""

    def run(self) -> None:
        _compile_mo_files()
        super().run()


class editable_wheel(_editable_wheel):
    """Custom editable_wheel — PEP 660 editable installs (pip install -e)."""

    def run(self) -> None:
        _compile_mo_files()
        super().run()


setup(cmdclass={
    "build_py": build_py,
    "develop": develop,
    "editable_wheel": editable_wheel,
})
