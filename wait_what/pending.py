"""Hand-over of a prepared folder to a process started without arguments.

Some terminals can open a tab with a fixed command but cannot pass it a
different argument each time (Konsole with a profile). The adapter writes the
folder here just before opening the tab; `wait-what run --pending` reads it.
"""

from __future__ import annotations

import os
import time

from . import CACHE

PATH = os.path.join(CACHE, 'pending')
MAX_AGE = 60  # seconds: an older hand-over is stale


def write(folder: str) -> None:
    os.makedirs(CACHE, exist_ok=True)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(folder)
    os.replace(tmp, PATH)


def take() -> str | None:
    """The pending folder, removed from the hand-over; None if none or stale."""
    try:
        if time.time() - os.path.getmtime(PATH) > MAX_AGE:
            os.remove(PATH)
            return None
        with open(PATH, encoding='utf-8') as f:
            folder = f.read().strip()
        os.remove(PATH)
    except OSError:
        return None
    return folder if os.path.isdir(folder) else None
