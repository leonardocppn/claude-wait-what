"""Open a prepared side instance in a terminal, when the adapter has no
native way to do it (the universal adapter).

Order:
1. if the source session runs in Konsole (the hook recorded it) and the
   claude-wait-what profile is installed, a new tab in the same Konsole window;
2. the terminal named in $WAIT_WHAT_TERMINAL (a command line; the command to
   run is appended to it);
3. xdg-terminal-exec, the freedesktop launcher for the default terminal;
4. the first known terminal installed, preferring the desktop's own.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess

from . import pending

# How each terminal runs a command in a new window: the command is appended.
# Taken from each terminal's documentation; see the README for which ones were tested.
TERMINALS: dict[str, list[str]] = {
    'konsole': ['konsole', '-e'],
    'ptyxis': ['ptyxis', '--'],
    'gnome-terminal': ['gnome-terminal', '--'],
    'kgx': ['kgx', '--'],
    'kitty': ['kitty'],
    'wezterm': ['wezterm', 'start', '--'],
    'alacritty': ['alacritty', '-e'],
    'ghostty': ['ghostty', '-e'],
    'foot': ['foot'],
    'xfce4-terminal': ['xfce4-terminal', '-x'],
    'xterm': ['xterm', '-e'],
}
DESKTOP_FIRST = {'KDE': ['konsole'], 'GNOME': ['ptyxis', 'gnome-terminal', 'kgx'],
                 'XFCE': ['xfce4-terminal']}


def terminal_command(command: list[str], env: dict[str, str] | None = None) -> list[str] | None:
    """Command line that opens a new terminal window running ``command``."""
    env = os.environ if env is None else env
    custom = env.get('WAIT_WHAT_TERMINAL')
    if custom:
        return shlex.split(custom) + command
    if shutil.which('xdg-terminal-exec'):
        return ['xdg-terminal-exec'] + command
    desktop = env.get('XDG_CURRENT_DESKTOP', '').upper()
    order = [t for d, ts in DESKTOP_FIRST.items() if d in desktop for t in ts]
    order += [t for t in TERMINALS if t not in order]
    for name in order:
        if shutil.which(name):
            return TERMINALS[name] + command
    return None


def _spawn(argv: list[str], cwd: str | None) -> None:
    subprocess.Popen(argv, cwd=cwd if cwd and os.path.isdir(cwd) else None,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# --- Konsole, through D-Bus -------------------------------------------------
#
# Konsole lets other programs open tabs, but (since Konsole 26) not type
# commands into them: that part of its D-Bus API is disabled by default, for
# good reasons. So the tab is opened with a dedicated profile, whose start
# command (`wait-what run --pending`) picks up the instance just prepared.
# The profile is created once with `wait-what install-konsole`; Konsole reads
# profiles at startup, so it must be restarted once after that.

KONSOLE_PROFILE = 'claude-wait-what'


def _qdbus() -> str | None:
    return shutil.which('qdbus6') or shutil.which('qdbus-qt6') or shutil.which('qdbus')


def _call(qdbus: str, *args: str) -> str:
    out = subprocess.run([qdbus, *args], capture_output=True, text=True, timeout=5)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout


def open_konsole(pane: str, folder: str, cwd: str | None) -> bool:
    """New tab in the Konsole window that holds ``pane``; False if not possible."""
    m = re.fullmatch(r'konsole-(.+)-(\d+)', pane)
    qdbus = _qdbus()
    if not m or not qdbus:
        return False
    service, session = ':' + m.group(1), m.group(2)
    try:
        windows = [line.rsplit('/', 1)[-1] for line in _call(qdbus, service).split()
                   if re.fullmatch(r'/Windows/\d+', line)]
        for win in windows:
            path = f'/Windows/{win}'
            if session not in _call(qdbus, service, path, 'org.kde.konsole.Window.sessionList').split():
                continue
            if KONSOLE_PROFILE not in _call(qdbus, service, path,
                                            'org.kde.konsole.Window.profileList').splitlines():
                return False  # not installed, or Konsole not restarted since
            pending.write(folder)
            _call(qdbus, service, path, 'org.kde.konsole.Window.newSession',
                  KONSOLE_PROFILE, cwd or os.path.expanduser('~'))
            return True
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False
    return False


def install_konsole_profile(command: list[str]) -> str:
    """Write the Konsole profile used by open_konsole(); returns its path."""
    base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    path = os.path.join(base, 'konsole', KONSOLE_PROFILE + '.profile')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('[General]\n'
                f'Name={KONSOLE_PROFILE}\n'
                f'Command={shlex.join(command)}\n'
                'Parent=FALLBACK/\n')
    return path


def open_anywhere(command: list[str], folder: str, meta: dict) -> bool:
    pane = meta.get('pane') or ''
    if pane.startswith('konsole-') and open_konsole(pane, folder, meta.get('cwd')):
        return True
    argv = terminal_command(command)
    if argv is None:
        return False
    _spawn(argv, meta.get('cwd'))
    return True
