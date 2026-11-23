"""Which Claude Code session runs in which terminal pane.

A SessionStart hook (``wait-what hook``) runs every time a session starts,
also after /clear or --resume. Claude Code passes it the session id and the
path of the session file; the hook reads from its environment which terminal
pane it is in and writes ``<cache>/sessions/<pane key>.json``.

When the selection is taken, the adapter knows the pane it came from and
computes the same key: the session is then known for certain, not guessed.
"""

from __future__ import annotations

import json
import os

from . import CACHE

SESSIONS = os.path.join(CACHE, 'sessions')


def pane_key(env: dict[str, str] | None = None) -> str | None:
    """Key of the terminal pane this process runs in, from its environment.

    Each key also contains something that changes when the terminal restarts
    (process id, socket), so a stale entry is never mistaken for a new pane
    that happens to reuse the same number.
    """
    env = os.environ if env is None else env
    if env.get('KITTY_PID') and env.get('KITTY_WINDOW_ID'):
        return f"kitty-{env['KITTY_PID']}-{env['KITTY_WINDOW_ID']}"
    if env.get('TMUX') and env.get('TMUX_PANE'):
        server = env['TMUX'].split(',')[1] if ',' in env['TMUX'] else ''
        return f"tmux-{server}-{env['TMUX_PANE'].lstrip('%')}"
    if env.get('WEZTERM_PANE'):
        socket = os.path.basename(env.get('WEZTERM_UNIX_SOCKET', ''))
        return f"wezterm-{socket}-{env['WEZTERM_PANE']}"
    if env.get('KONSOLE_DBUS_SERVICE') and env.get('KONSOLE_DBUS_SESSION'):
        session = env['KONSOLE_DBUS_SESSION'].rsplit('/', 1)[-1]
        return f"konsole-{env['KONSOLE_DBUS_SERVICE'].lstrip(':')}-{session}"
    return None


def _safe(key: str) -> str:
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in key)


def record(key: str, hook_input: dict) -> None:
    os.makedirs(SESSIONS, exist_ok=True)
    with open(os.path.join(SESSIONS, _safe(key) + '.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'session_id': hook_input.get('session_id'),
            'transcript_path': hook_input.get('transcript_path'),
            'cwd': hook_input.get('cwd'),
        }, f)


def find_pane(transcript_path: str) -> str | None:
    """The pane a session runs in, found from its file (most recent entry wins).

    Used the other way round from lookup(): when the session was found by
    searching the selection, this tells where it lives, so an adapter can
    open the side instance next to it.
    """
    try:
        names = os.listdir(SESSIONS)
    except OSError:
        return None
    best, best_time = None, -1.0
    for name in names:
        p = os.path.join(SESSIONS, name)
        try:
            with open(p, encoding='utf-8') as f:
                if json.load(f).get('transcript_path') != transcript_path:
                    continue
            t = os.path.getmtime(p)
        except (OSError, ValueError):
            continue
        if t > best_time:
            best, best_time = name[:-len('.json')], t
    return best


def lookup(key: str) -> dict | None:
    """The entry recorded for a pane, if its session file still exists."""
    try:
        with open(os.path.join(SESSIONS, _safe(key) + '.json'), encoding='utf-8') as f:
            entry = json.load(f)
    except (OSError, ValueError):
        return None
    path = entry.get('transcript_path')
    return entry if path and os.path.exists(path) else None
