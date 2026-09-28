"""Verify every distribution in requirements.txt is installed.

run.bat calls this before launching. Exit code 0 means everything is already
satisfied; exit code 1 means at least one is missing and the caller should run
`pip install -r requirements.txt`.

A previous version of the launcher checked only seven hardcoded import names
(fastapi, uvicorn, pydantic, webview, ollama, PIL, numpy). That let a machine
missing colorthief / transformers / torch / python-multipart sail past the
check and then fail at runtime, so this reads the requirements file instead and
never drifts from it.
"""
import importlib.metadata as metadata
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_PATH = os.path.join(BASE_DIR, 'requirements.txt')

# name, optional [extras], optional version specifier
_LINE_RE = re.compile(r'^([A-Za-z0-9._-]+)\s*(\[[^\]]*\])?\s*([<>=!~].*)?$')


def parse_requirements(path=None):
    """Distribution names from a requirements file.

    Skips blank lines, comments and pip options (-r, --index-url, ...).
    """
    # Resolved at call time, not as a default argument, so callers can point
    # the module at a different requirements file.
    if path is None:
        path = REQUIREMENTS_PATH
    names = []
    try:
        handle = open(path, encoding='utf-8')
    except OSError as e:
        print(f"[DEPS] Cannot read {path}: {e}")
        return names
    with handle:
        for raw in handle:
            line = raw.split('#', 1)[0].strip()
            if not line or line.startswith('-'):
                continue
            match = _LINE_RE.match(line)
            if match:
                names.append(match.group(1))
    return names


def is_installed(name):
    try:
        metadata.version(name)
        return True
    except metadata.PackageNotFoundError:
        return False


def missing_packages(path=None):
    return [n for n in parse_requirements(path) if not is_installed(n)]


def main():
    path = REQUIREMENTS_PATH
    if not os.path.exists(path):
        print(f"[DEPS] No requirements.txt at {path} - skipping check.")
        return 0

    required = parse_requirements(path)
    if not required:
        print("[DEPS] requirements.txt listed no packages - skipping check.")
        return 0

    absent = missing_packages(path)
    if absent:
        print(f"[DEPS] Missing {len(absent)} of {len(required)} package(s):")
        for name in absent:
            print(f"        - {name}")
        return 1

    print(f"[DEPS] All {len(required)} dependencies present.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
