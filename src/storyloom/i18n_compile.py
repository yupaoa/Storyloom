"""Pure-Python .po → .mo compiler.  Zero dependencies beyond stdlib.

Used by the build step so that ``pip install`` automatically compiles
gettext translations — users never need to install ``msgfmt`` or run
anything by hand.

Reference: GNU gettext .mo binary format (little-endian).
"""

import struct
from pathlib import Path

_MAGIC = 0x950412DE


def compile_po_file(po_path: str, mo_path: str) -> None:
    """Compile a single .po file to a .mo binary catalog."""
    entries = _parse_po(po_path)
    _write_mo(entries, mo_path)


def compile_all(locale_dir: str) -> list[str]:
    """Compile every .po under *locale_dir*.

    Returns the list of .mo paths that were written.
    """
    compiled: list[str] = []
    for po_file in Path(locale_dir).rglob("*.po"):
        mo_file = str(po_file.with_suffix(".mo"))
        compile_po_file(str(po_file), mo_file)
        compiled.append(mo_file)
    return compiled


# ── .po parser ──────────────────────────────────────────────────────

def _parse_po(path: str) -> list[tuple[str, str]]:
    """Return ordered (msgid, msgstr) pairs from a .po file.

    Includes the header entry (empty msgid → metadata) so the .mo is
    byte-identical with what msgfmt produces.
    """
    entries: list[tuple[str, str]] = []
    msgid: list[str] = []
    msgstr: list[str] = []
    active: str | None = None  # 'msgid' or 'msgstr'

    def _flush() -> None:
        nonlocal msgid, msgstr, active
        entries.append(("".join(msgid), "".join(msgstr)))
        msgid, msgstr, active = [], [], None

    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("msgid "):
                if active is not None:
                    _flush()
                msgid.append(_unquote(line, "msgid "))
                active = "msgid"
            elif line.startswith("msgstr "):
                msgstr.append(_unquote(line, "msgstr "))
                active = "msgstr"
            elif line.startswith('"') and active is not None:
                buf = msgid if active == "msgid" else msgstr
                buf.append(_unquote(line))

    if active is not None:
        _flush()

    return entries


def _unquote(line: str, prefix: str = "") -> str:
    """Extract and unescape a quoted .po string.

    .po escape sequences (``\\n``, ``\\t``, ``\\\\``, ``\\"``) are
    converted to their literal characters.
    """
    if prefix:
        line = line[len(prefix):]
    if len(line) >= 2 and line.startswith('"') and line.endswith('"'):
        line = line[1:-1]
    # Unescape .po escape sequences
    return line.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\x00", "\\")


# ── .mo writer ──────────────────────────────────────────────────────

def _write_mo(entries: list[tuple[str, str]], path: str) -> None:
    """Write a GNU .mo binary catalog.

    Layout::
        [28-byte header][orig-table][trans-table][orig-data][trans-data]

    Each string is NUL-terminated in the data region, but the length
    field in the table **excludes** the NUL (matching msgfmt).
    """
    N = len(entries)
    if N == 0:
        return

    # --- encoded strings with NUL terminators ----------------------------------
    orig_b: list[bytes] = [o.encode("utf-8") + b"\x00" for o, _ in entries]
    trans_b: list[bytes] = [t.encode("utf-8") + b"\x00" for _, t in entries]

    # --- fixed offsets ----------------------------------------------------------
    HEADER = 28
    ORIG_TABLE = HEADER
    TRANS_TABLE = HEADER + N * 8
    DATA_START = TRANS_TABLE + N * 8

    total_orig = sum(len(b) for b in orig_b)

    # --- build tables -----------------------------------------------------------
    orig_table = bytearray()
    trans_table = bytearray()

    orig_pos = DATA_START
    trans_pos = DATA_START + total_orig

    for ob, tb in zip(orig_b, trans_b):
        # length *excludes* the trailing NUL
        orig_table += struct.pack("<II", len(ob) - 1, orig_pos)
        orig_pos += len(ob)
        trans_table += struct.pack("<II", len(tb) - 1, trans_pos)
        trans_pos += len(tb)

    # --- header -----------------------------------------------------------------
    header = struct.pack(
        "<IIIIIII",
        _MAGIC,       # magic
        0,            # revision
        N,            # number of strings
        ORIG_TABLE,   # offset of original-string table
        TRANS_TABLE,  # offset of translated-string table
        0,            # hash table size (0 = no hash)
        0,            # hash table offset
    )

    # --- write ------------------------------------------------------------------
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(orig_table)
        fh.write(trans_table)
        fh.write(b"".join(orig_b))
        fh.write(b"".join(trans_b))


# ── Frontend JS dict generator ───────────────────────────────────────

def _js_escape(s: str) -> str:
    """Escape a string for safe inclusion in a JS double-quoted literal."""
    return (s
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t"))


def generate_js_dict(locale_dir: str, output_path: str) -> None:
    """Generate a JS file with the ``T`` translation dictionary from .po files.

    Reads every ``*.po`` under *locale_dir*, extracts msgid/msgstr pairs
    (skipping the header entry), and writes a ``const T = {...}``
    declaration to *output_path*.  The ``en`` key is always included as
    an empty identity map (English is the source language).

    This eliminates the dual-write between .po (server gettext) and the
    frontend ``T`` dictionary in state.js — .po is now the single
    authoritative source for UI translations.
    """
    translations: dict[str, dict[str, str]] = {}

    for po_file in Path(locale_dir).rglob("*.po"):
        # Derive language code from path: locale/zh_CN/LC_MESSAGES/… → zh-CN
        lang_code = str(Path(po_file).parents[1].name).replace("_", "-")
        entries = _parse_po(str(po_file))
        lang_dict: dict[str, str] = {}
        for msgid, msgstr in entries:
            if msgid == "":       # header entry — skip
                continue
            lang_dict[msgid] = msgstr
        translations[lang_code] = lang_dict

    # Always include English as empty identity map
    if "en" not in translations:
        translations["en"] = {}

    # Build JS source
    lines: list[str] = [
        "// Auto-generated from locale/*.po — DO NOT EDIT by hand.",
        "// Regenerate with: python -m storyloom.i18n_compile",
        "//",
        "// See CLAUDE.md §Tech Stack (i18n).",
        "const T = {",
    ]
    for lang in sorted(translations):
        lines.append(f'    "{lang}": {{')
        lang_dict = translations[lang]
        if not lang_dict:
            lines.append("        /* identity map — source language */")
        for msgid in sorted(lang_dict):
            msgid_e = _js_escape(msgid)
            msgstr_e = _js_escape(lang_dict[msgid])
            lines.append(f'        "{msgid_e}": "{msgstr_e}",')
        lines.append("    },")
    lines.append("};")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
