"""Prompt history — a small append-only JSONL log with a lock and a size cap.

Every generated/finalized/injected/TTS prompt that reaches the user is recorded
so past work can be reloaded or exported from the UI.
"""
import json
import os
import threading
import time

from . import log
from .config import HISTORY_LIMIT, HISTORY_PATH

logger = log.get_logger(__name__)

_lock = threading.Lock()


def append_history(kind, prompt, template=''):
    if not prompt or not str(prompt).strip():
        return
    entry = {
        'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        'kind': str(kind),
        'template': str(template or ''),
        'prompt': str(prompt),
    }
    with _lock:
        try:
            with open(HISTORY_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except OSError as e:
            logger.info("[HISTORY] Failed to append: %s", e)
            return
    trim_history(locked=True)


def list_history(limit=50):
    items = []
    with _lock:
        if not os.path.exists(HISTORY_PATH):
            return []
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.info("[HISTORY] Failed to read: %s", e)
            return []
    return items[-max(1, int(limit)):][::-1]


def trim_history(locked=False):
    with _lock if not locked else _null_ctx():
        if not os.path.exists(HISTORY_PATH):
            return
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                lines = [ln for ln in f if ln.strip()]
            if len(lines) <= HISTORY_LIMIT:
                return
            with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
                f.writelines(lines[-HISTORY_LIMIT:])
        except OSError as e:
            logger.info("[HISTORY] Failed to trim: %s", e)


def clear_history():
    with _lock:
        try:
            if os.path.exists(HISTORY_PATH):
                os.remove(HISTORY_PATH)
        except OSError as e:
            logger.info("[HISTORY] Failed to clear: %s", e)


class _null_ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False