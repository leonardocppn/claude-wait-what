"""Command line: ``wait-what <command>``.

    wait-what hook                 SessionStart hook for Claude Code (reads stdin)
    wait-what prepare [--pane K]   read the selection from stdin, prepare a
                                   side instance, print its folder as JSON
    wait-what run FOLDER           show the excerpt and start Claude there
    wait-what anywhere             universal adapter: read the primary selection
                                   and open the instance in a terminal window
    wait-what install-konsole      create the Konsole profile used for tabs
    wait-what install-tmux         write a ready tmux config to source
    wait-what tmux --socket S --server-pid P --pane %N [--buffer]
                                   tmux adapter: selection from stdin (copy-pipe)
                                   or from the last tmux buffer, new tmux window
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

from . import opener, pending, registry
from .prepare import prepare

# Tools the side instance cannot use: it reads, it does not write.
DENIED_TOOLS = ('Edit', 'Write', 'NotebookEdit')


def cmd_hook(_args) -> int:
    # Prints nothing: whatever a SessionStart hook prints ends up in Claude's context.
    key = registry.pane_key()
    if key is None:
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    registry.record(key, data)
    return 0


def cmd_prepare(args) -> int:
    selection = sys.stdin.read()
    if not selection.strip():
        return 1
    folder = prepare(selection, args.pane)
    with open(os.path.join(folder, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    print(json.dumps({'folder': folder, **meta}))
    return 0


def cmd_run(args) -> int:
    folder = pending.take() if args.pending else args.folder
    if not folder:
        print('wait, what? Nothing pending: the selection was not prepared in time.', file=sys.stderr)
        input('Press Enter to close.')
        return 1
    folder = os.path.abspath(folder)
    with open(os.path.join(folder, 'prompt.md'), encoding='utf-8') as f:
        prompt = f.read()
    with open(os.path.join(folder, 'header.txt'), encoding='utf-8') as f:
        head = f.read()
    with open(os.path.join(folder, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    if meta.get('cwd') and os.path.isdir(meta['cwd']):
        os.chdir(meta['cwd'])  # same project as the source session: same CLAUDE.md
    # Excerpt in the palette's color 3 (yellow/orange), italic.
    sys.stdout.write(f'\n  \033[33m»\033[0m \033[3m{head}\033[0m\n\n')
    sys.stdout.flush()
    claude = shutil.which('claude') or 'claude'
    os.execvp(claude, [claude, '--append-system-prompt', prompt, '--add-dir', folder,
                       '--disallowedTools', *DENIED_TOOLS])
    return 1  # not reached


def _cli() -> list[str]:
    """How to call this same CLI from a new terminal."""
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'bin', 'wait-what')
    return [shutil.which('python3') or 'python3', '-I', here]


def _meta(folder: str) -> dict:
    with open(os.path.join(folder, 'meta.json'), encoding='utf-8') as f:
        return json.load(f)


def _notify(message: str) -> None:
    # Started from a desktop shortcut there is no terminal to print to.
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', '--app-name=claude-wait-what', 'wait, what?', message])
    else:
        print(message, file=sys.stderr)


def read_primary_selection() -> str:
    if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-paste'):
        argv = ['wl-paste', '--primary', '--no-newline']
    elif shutil.which('xclip'):
        argv = ['xclip', '-o', '-selection', 'primary']
    elif shutil.which('xsel'):
        argv = ['xsel', '--primary', '--output']
    else:
        raise RuntimeError('no clipboard tool found (wl-paste, xclip or xsel)')
    out = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    return out.stdout if out.returncode == 0 else ''


def cmd_anywhere(_args) -> int:
    try:
        selection = read_primary_selection()
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        _notify(str(e))
        return 1
    if not selection.strip():
        _notify('Nothing selected.')
        return 1
    folder = prepare(selection)
    if not opener.open_anywhere(_cli() + ['run', folder], folder, _meta(folder)):
        _notify('No terminal found: set WAIT_WHAT_TERMINAL.')
        return 1
    return 0


def cmd_tmux(args) -> int:
    tmux = ['tmux', '-S', args.socket]
    if args.buffer:
        out = subprocess.run(tmux + ['save-buffer', '-'], capture_output=True, text=True)
        selection = out.stdout
    else:
        selection = sys.stdin.read()
    if not selection.strip():
        subprocess.run(tmux + ['display-message', 'wait, what? Nothing selected.'])
        return 1
    folder = prepare(selection, f"tmux-{args.server_pid}-{args.pane.lstrip('%')}")
    meta = _meta(folder)
    cmd = ['new-window', '-n', meta['title']]
    if meta.get('cwd'):
        cmd += ['-c', meta['cwd']]
    # "exec": when Claude exits, the window closes.
    subprocess.run(tmux + cmd + ['exec ' + shlex.join(_cli() + ['run', folder])])
    return 0


def cmd_install_tmux(_args) -> int:
    """Write a ready tmux config (the template with this checkout's path)."""
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    with open(os.path.join(root, 'adapters', 'tmux', 'wait-what.tmux.conf'), encoding='utf-8') as f:
        conf = f.read().replace('WAIT_WHAT', shlex.join(_cli()))
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    path = os.path.join(base, 'claude-wait-what', 'wait-what.tmux.conf')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(conf)
    print(f'tmux config written to {path}. Add this line to ~/.tmux.conf:\n'
          f'    source-file {path}')
    return 0


def cmd_install_konsole(_args) -> int:
    path = opener.install_konsole_profile(_cli() + ['run', '--pending'])
    print(f'Konsole profile written to {path}. Restart Konsole once to load it.')
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog='wait-what')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('hook', help='SessionStart hook for Claude Code').set_defaults(fn=cmd_hook)
    pp = sub.add_parser('prepare', help='prepare a side instance from the selection on stdin')
    pp.add_argument('--pane', help='key of the pane the selection comes from')
    pp.set_defaults(fn=cmd_prepare)
    pr = sub.add_parser('run', help='start the side instance prepared in FOLDER')
    pr.add_argument('folder', nargs='?')
    pr.add_argument('--pending', action='store_true', help='take the folder handed over by an adapter')
    pr.set_defaults(fn=cmd_run)
    sub.add_parser('anywhere', help='universal adapter (primary selection, new terminal)'
                   ).set_defaults(fn=cmd_anywhere)
    sub.add_parser('install-konsole', help='create the Konsole profile (restart Konsole after)'
                   ).set_defaults(fn=cmd_install_konsole)
    sub.add_parser('install-tmux', help='write a ready tmux config to source'
                   ).set_defaults(fn=cmd_install_tmux)
    pt = sub.add_parser('tmux', help='tmux adapter')
    pt.add_argument('--socket', required=True, help='#{socket_path}')
    pt.add_argument('--server-pid', required=True, help='#{pid}')
    pt.add_argument('--pane', required=True, help='#{pane_id}')
    pt.add_argument('--buffer', action='store_true', help='use the last tmux buffer, not stdin')
    pt.set_defaults(fn=cmd_tmux)
    # Commands pasted into a desktop shortcut dialog often carry a trailing
    # newline ("anywhere\n"): stray whitespace around arguments is dropped.
    argv = [a.strip() for a in (sys.argv[1:] if argv is None else argv)]
    args = p.parse_args(argv)
    return args.fn(args)
