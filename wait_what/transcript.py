"""Read Claude Code session files and find where a selection comes from.

Claude Code stores each session as a JSON Lines file under
``~/.claude/projects/<project>/<session-id>.jsonl``. The format is not a public
API: this module reads only the few fields it needs and skips anything else.
"""

from __future__ import annotations

import glob
import json
import os
import time

USER, CLAUDE = 'User', 'Claude'

# User entries that are not something the user typed: slash commands, their
# output, system reminders, shell escapes, background notifications.
NOT_TYPED = ('<command-', '<local-command-', '<system-reminder', '<task-notification',
             '<bash-', '<user-memory-input')

Message = tuple[str, str]  # (speaker, text)


def normalize(s: str) -> str:
    """Letters and digits only, case-folded.

    On screen the text is laid out (wrapped lines, indentation, bullets, no
    markdown asterisks or backticks); in the file it is raw markdown. Dropping
    everything that is not a letter or a digit makes the two comparable.
    """
    return ''.join(c for c in s.casefold() if c.isalnum())


def messages(path: str) -> list[Message]:
    """The readable messages of a session, in order.

    Claude's replies are split in the file into several blocks (tool calls sit
    between them); consecutive blocks are merged into one message per turn, as
    they appear on screen.
    """
    out: list[Message] = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            # Message lines all start like this; skipping the others without
            # decoding them (API requests, snapshots) keeps large files fast.
            if not line.startswith('{"parentUuid"'):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get('isSidechain') or entry.get('isMeta'):
                continue
            content = (entry.get('message') or {}).get('content')
            kind = entry.get('type')
            if kind == 'assistant' and isinstance(content, list):
                text = '\n\n'.join(b.get('text', '') for b in content
                                   if isinstance(b, dict) and b.get('type') == 'text').strip()
                if not text:
                    continue
                if out and out[-1][0] == CLAUDE:
                    out[-1] = (CLAUDE, out[-1][1] + '\n\n' + text)
                else:
                    out.append((CLAUDE, text))
            elif kind == 'user':
                if isinstance(content, list):  # tool results are skipped here
                    content = '\n\n'.join(b.get('text', '') for b in content
                                          if isinstance(b, dict) and b.get('type') == 'text')
                text = (content or '').strip()
                if text and not text.startswith(NOT_TYPED):
                    out.append((USER, text))
    return out


def find(msgs: list[Message], selection: str) -> int | None:
    """Index of the most recent message that contains the selection.

    If the whole selection is not found (for instance because it spans two
    messages), its beginning and then its end are tried.
    """
    sel = normalize(selection)
    if len(sel) < 4:
        return None
    norm = [normalize(t) for _, t in msgs]
    # Half of the selection, between 20 and 80 characters: long enough not to
    # match by chance, short enough to fit inside one of two messages.
    n = min(80, max(20, len(sel) // 2))
    for piece in (sel, sel[:n], sel[-n:]):
        for i in range(len(msgs) - 1, -1, -1):
            if piece in norm[i]:
                return i
    return None


def session_cwd(path: str) -> str | None:
    """Working directory recorded in the session file (first entry that has one)."""
    with open(path, encoding='utf-8') as f:
        for line in f:
            if '"cwd"' not in line:
                continue
            try:
                cwd = json.loads(line).get('cwd')
            except ValueError:
                continue
            if cwd:
                return cwd
    return None


def projects_dir() -> str:
    base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.expanduser('~/.claude')
    return os.path.join(base, 'projects')


def search_recent(selection: str, hours: float = 12, limit: int = 30) -> str | None:
    """Session file that contains the selection, among recently modified ones.

    Used when the terminal cannot tell which session runs in the pane (the
    universal adapter, or a session started before the hook was installed).
    """
    since = time.time() - hours * 3600
    files = [p for p in glob.glob(os.path.join(projects_dir(), '*', '*.jsonl'))
             if os.path.getmtime(p) >= since]
    files.sort(key=os.path.getmtime, reverse=True)
    for path in files[:limit]:
        try:
            if find(messages(path), selection) is not None:
                return path
        except OSError:
            continue
    return None


def export(msgs: list[Message], index: int | None, path: str) -> None:
    """Write the conversation as plain text, marking the source message."""
    with open(path, 'w', encoding='utf-8') as f:
        for i, (who, text) in enumerate(msgs):
            mark = '  ◀ the selection comes from here' if i == index else ''
            f.write(f'## {who}{mark}\n\n{text}\n\n')
