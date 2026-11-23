"""Tests for the core, on synthetic sessions. Run: python3 -m unittest discover tests"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wait_what import opener, pending, registry, transcript  # noqa: E402


def _line(kind, content, **extra):
    entry = {'parentUuid': None, 'isSidechain': False, 'type': kind,
             'message': {'role': kind, 'content': content}, 'cwd': '/tmp/project', **extra}
    return json.dumps(entry) + '\n'


def write_session(lines):
    f = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False, encoding='utf-8')
    f.write('{"type":"permission-mode","permissionMode":"default"}\n')  # non-message line
    f.writelines(lines)
    f.close()
    return f.name


SESSION = [
    _line('user', '<command-name>/theme</command-name>'),
    _line('user', 'How do I split a window?'),
    _line('assistant', [{'type': 'thinking', 'thinking': '...'}]),
    _line('assistant', [{'type': 'text', 'text': 'Use the **splits** layout.'}]),
    _line('assistant', [{'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {}}]),
    _line('user', [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'}]),
    _line('assistant', [{'type': 'text', 'text': '- Then press `Ctrl+Shift+Enter`\n  to open a new pane.'}]),
    _line('user', 'And the tabs?', isMeta=True),
    _line('user', 'And the tabs?'),
    _line('assistant', [{'type': 'text', 'text': 'Tabs belong to the whole window.'}]),
]


class TestTranscript(unittest.TestCase):
    def setUp(self):
        self.path = write_session(SESSION)
        self.addCleanup(os.remove, self.path)

    def test_messages_merge_turn_and_skip_noise(self):
        msgs = transcript.messages(self.path)
        self.assertEqual([who for who, _ in msgs], ['User', 'Claude', 'User', 'Claude'])
        self.assertIn('splits', msgs[1][1])
        self.assertIn('Ctrl+Shift+Enter', msgs[1][1])  # second block of the same turn

    def test_find_with_screen_layout(self):
        msgs = transcript.messages(self.path)
        # As it looks on screen: bullet, no backticks, line wrapped with indent.
        selection = '• Then press Ctrl+Shift+Enter\n      to open a new pane.'
        self.assertEqual(transcript.find(msgs, selection), 1)

    def test_find_selection_spanning_two_messages(self):
        msgs = transcript.messages(self.path)
        selection = 'Use the splits layout. Then press Ctrl+Shift+Enter to open a new pane. And the tabs?'
        self.assertEqual(transcript.find(msgs, selection), 1)

    def test_find_missing_and_too_short(self):
        msgs = transcript.messages(self.path)
        self.assertIsNone(transcript.find(msgs, 'something that is not there'))
        self.assertIsNone(transcript.find(msgs, '• a'))

    def test_session_cwd(self):
        self.assertEqual(transcript.session_cwd(self.path), '/tmp/project')

    def test_export_marks_source(self):
        msgs = transcript.messages(self.path)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'c.md')
            transcript.export(msgs, 3, out)
            text = open(out, encoding='utf-8').read()
        self.assertIn('## Claude  ◀ the selection comes from here\n\nTabs belong', text)
        self.assertEqual(text.count('◀'), 1)


class TestRegistry(unittest.TestCase):
    def test_pane_keys(self):
        self.assertEqual(registry.pane_key({'KITTY_PID': '12', 'KITTY_WINDOW_ID': '3'}), 'kitty-12-3')
        self.assertEqual(registry.pane_key({'TMUX': '/tmp/tmux-1/default,456,0', 'TMUX_PANE': '%7'}),
                         'tmux-456-7')
        self.assertEqual(registry.pane_key({'WEZTERM_PANE': '2',
                                            'WEZTERM_UNIX_SOCKET': '/run/user/1/wezterm/gui-sock-99'}),
                         'wezterm-gui-sock-99-2')
        self.assertEqual(registry.pane_key({'KONSOLE_DBUS_SERVICE': ':1.97',
                                            'KONSOLE_DBUS_SESSION': '/Sessions/3'}), 'konsole-1.97-3')
        self.assertIsNone(registry.pane_key({}))

    def test_record_and_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            old = registry.SESSIONS
            registry.SESSIONS = d
            try:
                session = os.path.join(d, 's.jsonl')
                open(session, 'w').close()
                registry.record('kitty-1-2', {'session_id': 's', 'transcript_path': session, 'cwd': '/x'})
                self.assertEqual(registry.lookup('kitty-1-2')['cwd'], '/x')
                self.assertIsNone(registry.lookup('kitty-1-3'))
                os.remove(session)  # session file gone: the entry no longer counts
                self.assertIsNone(registry.lookup('kitty-1-2'))
            finally:
                registry.SESSIONS = old


class TestFindPane(unittest.TestCase):
    def test_most_recent_entry_wins(self):
        with tempfile.TemporaryDirectory() as d:
            old = registry.SESSIONS
            registry.SESSIONS = d
            try:
                session = os.path.join(d, 's.jsonl')
                open(session, 'w').close()
                registry.record('konsole-1.5-2', {'transcript_path': session})
                os.utime(os.path.join(d, 'konsole-1.5-2.json'), (1, 1))
                registry.record('kitty-9-4', {'transcript_path': session})
                self.assertEqual(registry.find_pane(session), 'kitty-9-4')
                self.assertIsNone(registry.find_pane('/nowhere.jsonl'))
            finally:
                registry.SESSIONS = old


class TestPending(unittest.TestCase):
    def test_hand_over_once_and_stale(self):
        with tempfile.TemporaryDirectory() as d:
            old = pending.PATH
            pending.PATH = os.path.join(d, 'pending')
            try:
                pending.write(d)
                self.assertEqual(pending.take(), d)
                self.assertIsNone(pending.take())  # taken only once
                pending.write(d)
                os.utime(pending.PATH, (1, 1))
                self.assertIsNone(pending.take())  # too old
            finally:
                pending.PATH = old


class TestTerminalCommand(unittest.TestCase):
    def test_override_and_desktop_preference(self):
        self.assertEqual(opener.terminal_command(['x'], {'WAIT_WHAT_TERMINAL': 'myterm --new -e'}),
                         ['myterm', '--new', '-e', 'x'])
        argv = opener.terminal_command(['x'], {'XDG_CURRENT_DESKTOP': 'KDE'})
        if argv is not None and not opener.shutil.which('xdg-terminal-exec'):
            self.assertEqual(argv[-1], 'x')
            self.assertIn(argv[0], opener.TERMINALS)


if __name__ == '__main__':
    unittest.main()
