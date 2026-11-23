"""Kitty adapter for claude-wait-what.

A kitten without UI: Kitty runs it inside its own process, with access to the
"boss" (the object that manages windows and tabs). When triggered it:

1. reads the text selected in the pane you are in;
2. asks the core (``wait-what prepare``) to prepare a side instance, passing
   the pane key so the core knows which session runs there;
3. opens it as a tab in a separate Kitty window (class ``claude-wait-what``),
   creating that window the first time, with the colors of the source pane.

kitty.conf:

    map ctrl+a kitten /path/to/claude-wait-what/adapters/kitty/wait_what_kitty.py pass-ctrl-a

With ``pass-ctrl-a``, Ctrl+A without a selection is sent on to the program
(where it usually means "beginning of line"), so the key keeps its old job.
"""

import json
import os
import shutil
import subprocess
import sys

from kittens.tui.handler import result_handler

# While loading a kitten Kitty puts the kitten's directory first in sys.path:
# that is how the kitten finds the checkout it belongs to.
_ROOT = os.path.realpath(os.path.join(sys.path[0], '..', '..'))
CLI = os.path.join(_ROOT, 'bin', 'wait-what')
if not os.path.exists(CLI):
    CLI = shutil.which('wait-what') or CLI

WINDOW_CLASS = 'claude-wait-what'


def main(args: list[str]) -> str:
    return ''


def _python() -> str:
    return shutil.which('python3') or 'python3'


@result_handler(no_ui=True)
def handle_result(args: list[str], answer: str, target_window_id: int, boss) -> None:
    w = boss.window_id_map.get(target_window_id)
    if w is None:
        return
    selection = (w.text_for_selection() or '').strip()
    if not selection:
        if 'pass-ctrl-a' in args:
            # send-key encodes the key the way the program expects it.
            boss.call_remote_control(w, ('send-key', '--match', f'id:{w.id}', 'ctrl+a'))
        return

    pane = f'kitty-{os.getpid()}-{w.id}'  # same key the hook computes from KITTY_PID/KITTY_WINDOW_ID
    try:
        out = subprocess.run([_python(), '-I', CLI, 'prepare', '--pane', pane],
                             input=selection, capture_output=True, text=True, timeout=30)
        meta = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        boss.show_error('claude-wait-what', f'Could not prepare the side instance:\n{e}')
        return

    # One separate Kitty window holds all side instances, one tab each.
    window = next((tm for tm in boss.os_window_map.values()
                   if tm.wm_class == WINDOW_CLASS and tm.tabs), None)
    if window is not None:
        where = ('--type=tab', '--match', f'id:{window.tabs[0].id}')
    else:
        where = ('--type=os-window', '--os-window-class', WINDOW_CLASS,
                 '--os-window-title', 'wait, what?')

    boss.call_remote_control(w, (
        'launch', *where,
        '--cwd', meta.get('cwd') or w.cwd_of_child or os.path.expanduser('~'),
        '--tab-title', meta['title'],
        # Same colors as the source pane, even if it was given its own theme.
        '--source-window', f'id:{w.id}', '--copy-colors',
        _python(), '-I', CLI, 'run', meta['folder'],
    ))
    # Clear the selection: the next Ctrl+A must mean "beginning of line" again.
    w.clear_selection()
