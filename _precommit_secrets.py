"""Refuse to commit if the real key (or anything key-shaped) is staged.

Reads the live key from the gitignored settings.json, then checks every blob
git has staged. The key is never printed - only match counts.
"""
import json
import pathlib
import re
import subprocess
import sys

key = json.loads(pathlib.Path('settings.json').read_text(encoding='utf-8')).get('cloud_api_key') or ''
prefix = key[:10] if len(key) >= 10 else key

files = subprocess.run(
    ['git', 'diff', '--cached', '--name-only'],
    capture_output=True, text=True, check=True).stdout.split()

# Long opaque tokens: base32/hex-ish blobs that are not comments or identifiers.
TOKEN = re.compile(rb'[A-Za-z0-9_\-]{32,}')

secret_hits, token_report = [], []
for f in files:
    p = pathlib.Path(f)
    if not p.is_file():
        continue
    blob = p.read_bytes()
    if key and key.encode() in blob:
        secret_hits.append((f, 'EXACT KEY'))
    elif prefix and prefix.encode() in blob:
        secret_hits.append((f, 'KEY PREFIX'))
    for m in TOKEN.finditer(blob):
        tok = m.group().decode('ascii')
        if re.fullmatch(r'[0-9a-fA-F]{32,}', tok):      # hashes
            continue
        line = blob[:m.start()].count(b'\n') + 1
        token_report.append((f, line, tok[:6] + f'...{tok[-4:]} ({len(tok)} chars)'))

print(f'staged files scanned : {len(files)}')
print(f'full key occurrences : {len([h for h in secret_hits if h[1] == "EXACT KEY"])}')
print(f'key prefix hits      : {len([h for h in secret_hits if h[1] == "KEY PREFIX"])}')
for f, kind in secret_hits:
    print(f'  !! {f}: {kind}')

if token_report:
    print('\nlong opaque tokens worth eyeballing:')
    for f, line, tok in token_report:
        print(f'  {f}:{line}  {tok}')

sys.exit(1 if secret_hits else 0)
