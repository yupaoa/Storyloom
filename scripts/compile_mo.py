#!/usr/bin/env python3
"""Compile a GNU gettext .po file to .mo binary format (stdlib only).

Usage:
    python scripts/compile_mo.py locale/zh_CN/LC_MESSAGES/storyloom.po

Writes the .mo file alongside the .po file.
"""
import sys, struct, os


def unescape_po(s: str) -> str:
    """Convert PO escape sequences to actual characters."""
    s = s.replace('\\\\', '\x00')
    s = s.replace('\\n', '\n')
    s = s.replace('\\t', '\t')
    s = s.replace('\\r', '\r')
    s = s.replace('\\"', '"')
    s = s.replace('\x00', '\\')
    return s


def compile_po_to_mo(po_path: str, mo_path: str | None = None) -> int:
    """Compile .po → .mo.  Returns entry count."""
    if mo_path is None:
        mo_path = os.path.splitext(po_path)[0] + '.mo'

    with open(po_path, 'r', encoding='utf-8') as f:
        text = f.read()

    entries = []
    current_msgid = []
    current_msgstr = []
    in_msgid = False
    in_msgstr = False
    first = True

    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#') or stripped == '':
            continue
        if stripped.startswith('msgid '):
            if not first:
                entries.append((''.join(current_msgid), ''.join(current_msgstr)))
            first = False
            current_msgid = [stripped[6:].strip('"')]
            current_msgstr = []
            in_msgid = True
            in_msgstr = False
        elif stripped.startswith('msgstr '):
            current_msgstr = [stripped[7:].strip('"')]
            in_msgid = False
            in_msgstr = True
        elif stripped.startswith('"') and (in_msgid or in_msgstr):
            val = stripped.strip('"')
            if in_msgid:
                current_msgid.append(val)
            else:
                current_msgstr.append(val)

    if current_msgid is not None:
        entries.append((''.join(current_msgid), ''.join(current_msgstr)))

    entries = [(unescape_po(m), unescape_po(t)) for m, t in entries]

    N = len(entries)
    HEADER_SIZE = 28
    TABLE_SIZE = N * 8 * 2

    orig_encoded = [m.encode('utf-8') + b'\x00' for m, _ in entries]
    trans_encoded = [t.encode('utf-8') + b'\x00' for _, t in entries]

    offset = HEADER_SIZE + TABLE_SIZE
    orig_tab = []
    for s in orig_encoded:
        orig_tab.append((len(s) - 1, offset))
        offset += len(s)
    trans_tab = []
    for s in trans_encoded:
        trans_tab.append((len(s) - 1, offset))
        offset += len(s)

    with open(mo_path, 'wb') as f:
        f.write(struct.pack('<I', 0x950412de))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', N))
        f.write(struct.pack('<I', HEADER_SIZE))
        f.write(struct.pack('<I', HEADER_SIZE + N * 8))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', 0))
        for length, off in orig_tab:
            f.write(struct.pack('<I', length))
            f.write(struct.pack('<I', off))
        for length, off in trans_tab:
            f.write(struct.pack('<I', length))
            f.write(struct.pack('<I', off))
        for s in orig_encoded:
            f.write(s)
        for s in trans_encoded:
            f.write(s)

    msg_count = sum(1 for m, _ in entries if m)  # exclude header
    print(f"Compiled: {msg_count} messages → {mo_path}")
    return msg_count


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    compile_po_to_mo(sys.argv[1])
