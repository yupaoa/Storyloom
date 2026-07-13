"""Build hook — compile .po → .mo during ``pip install``.

Users never need ``msgfmt`` or any manual step.  Everything happens
automatically inside the build phase.
"""

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


def _compile_mo_files() -> None:
    """Compile all .po files under the project ``locale/`` directory."""
    project_root = Path(__file__).resolve().parent
    src = project_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from storyloom.i18n_compile import compile_all

    locale_dir = project_root / "locale"
    if locale_dir.is_dir():
        compiled = compile_all(str(locale_dir))
        if compiled:
            print(f"[i18n] compiled {len(compiled)} .mo file(s)")


class build_py(_build_py):
    """build_py subclass that compiles gettext catalogs first."""

    def run(self) -> None:
        _compile_mo_files()
        super().run()


setup(cmdclass={"build_py": build_py})
