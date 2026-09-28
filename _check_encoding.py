"""Detect mojibake / encoding damage across the project's text files.

PowerShell 5.1's `Set-Content -Encoding utf8` re-encodes through cp1252 and
prepends a BOM, which silently turns an em-dash (U+2014) into three garbage
characters. That has corrupted this project more than once, including prompt
text, so this is worth running after any scripted edit.

Patterns are built from codepoints so this file does not flag itself.
"""
import pathlib
import sys

PATTERNS = [
    chr(0xFFFD),                          # replacement char
    chr(0x00E2) + chr(0x20AC),            # a-circumflex + euro: start of a mangled run
    chr(0x00E2) + chr(0x20AC) + chr(0x201D),   # mangled em-dash
    chr(0x00E2) + chr(0x20AC) + chr(0x00A2),   # mangled bullet
    chr(0x00E2) + chr(0x20AC) + chr(0x2122),   # mangled trademark
    chr(0x00E2) + chr(0x20AC) + chr(0x0153),   # mangled right quote
    chr(0x00E2) + chr(0x20AC) + chr(0x2013),   # mangled en-dash
]
ROOT = pathlib.Path('.')

SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', 'uploads', 'avatar'}
EXTS = {'.py', '.js', '.html', '.css', '.bat', '.json', '.md', '.txt'}

bad = 0
for p in sorted(ROOT.rglob('*')):
    if not p.is_file():
        continue
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    if p.suffix.lower() not in EXTS:
        continue
    raw = p.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as e:
        print(f"INVALID UTF-8  {p}  {e}")
        bad += 1
        continue
    for pat in PATTERNS:
        if pat in text:
            for i, line in enumerate(text.splitlines(), 1):
                if pat in line:
                    safe = line.strip()[:100].encode('ascii', 'backslashreplace').decode()
                    print(f"MOJIBAKE       {p}:{i}  {safe}")
                    bad += 1
            break
    if raw.startswith(b'\xef\xbb\xbf'):
        print(f"BOM            {p}")
        bad += 1

print("clean" if not bad else f"{bad} problem(s)")
sys.exit(1 if bad else 0)
