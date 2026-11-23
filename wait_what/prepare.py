"""Prepare a side instance: one folder per "wait, what?" moment.

The folder holds everything the instance and the adapter need:

- ``prompt.md``        the instructions appended to the instance's system prompt
- ``conversation.md``  the whole source conversation as plain text
- ``header.txt``       the excerpt shown at the top of the new pane
- ``meta.json``        title, working directory, source session

Adapters call ``prepare()`` (or ``wait-what prepare``) and then start
``wait-what run <folder>`` wherever they want the instance to appear.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from . import CACHE, registry, transcript

TANGENTS = os.path.join(CACHE, 'tangents')
KEEP_DAYS = 7          # older folders are deleted
MAX_CHARS = 8000       # cap for each message passed in the prompt
PREVIOUS = 2           # messages before the source one
HEADER_ALL_WORDS = 30  # up to this, the header shows the whole selection
HEADER_WORDS = 20      # beyond, only the first words
TITLE_CHARS = 40

OPENING = """\
You are a side instance opened for a "wait, what?" moment: the user selected \
a passage from another Claude Code session, which keeps going on its own.

Selected passage:
«{selection}»
"""

WITH_SOURCE = """
The message it comes from, with the ones before it:

{messages}
The whole conversation, as plain text, is in {file}: read it only if what \
you have here is not enough to answer.
"""

WITHOUT_SOURCE = """
It was not possible to tell which message it comes from. The whole \
conversation, as plain text, is in {file}: look for it there if needed.
"""

CLOSING = """
Wait for the user's question and size your answer to it:
- if it is a narrow question (what a term or an acronym means, an unclear \
sentence), answer in a few lines from what you have here, without reading files;
- if it asks to dig into a point (its reasons, alternatives or consequences), \
use the context: reread the conversation and open project files when needed.
When in doubt, keep it short: the user will ask for more.

Reply in the language the user writes in. Do not modify files: this is for \
understanding, not for working."""


def header(selection: str) -> str:
    words = selection.split()
    if len(words) <= HEADER_ALL_WORDS:
        return ' '.join(words)
    return ' '.join(words[:HEADER_WORDS]) + ' …'


def title(selection: str) -> str:
    return '» ' + ' '.join(selection.split())[:TITLE_CHARS]


def _cap(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + '\n[…]'


def _clean_old() -> None:
    limit = time.time() - KEEP_DAYS * 86400
    for name in os.listdir(TANGENTS):
        p = os.path.join(TANGENTS, name)
        if os.path.isdir(p) and os.path.getmtime(p) < limit:
            shutil.rmtree(p, ignore_errors=True)


def compose(selection: str, session_file: str | None, folder: str) -> str:
    """The prompt for the side instance; exports the conversation as a side effect."""
    prompt = OPENING.format(selection=selection)
    if session_file is None:
        return prompt + CLOSING
    msgs = transcript.messages(session_file)
    i = transcript.find(msgs, selection)
    file = os.path.join(folder, 'conversation.md')
    transcript.export(msgs, i, file)
    if i is None:
        return prompt + WITHOUT_SOURCE.format(file=file) + CLOSING
    blocks = ''.join(f'--- {who} ---\n{_cap(text)}\n\n'
                     for who, text in msgs[max(0, i - PREVIOUS):i + 1])
    return prompt + WITH_SOURCE.format(messages=blocks, file=file) + CLOSING


def prepare(selection: str, pane: str | None = None) -> str:
    """Create the folder for a side instance and return its path.

    ``pane`` is the pane key the selection was taken from, if the adapter
    knows it. Without it (or if the hook has not recorded that pane) the
    session is guessed by searching the selection in recent sessions.
    """
    selection = selection.strip()
    os.makedirs(TANGENTS, exist_ok=True)
    _clean_old()
    folder = os.path.join(TANGENTS, time.strftime('%Y%m%d-%H%M%S-') + f'{time.time_ns() % 10**6:06d}')
    os.makedirs(folder)

    entry = registry.lookup(pane) if pane else None
    session_file = entry['transcript_path'] if entry else None
    cwd = entry.get('cwd') if entry else None
    try:
        if session_file is None:
            session_file = transcript.search_recent(selection)
            if session_file and pane is None:
                pane = registry.find_pane(session_file)  # where it runs, if the hook saw it
        if session_file and not cwd:
            cwd = transcript.session_cwd(session_file)
        prompt = compose(selection, session_file, folder)
    except Exception as e:  # the source is a bonus: on any failure, start without it
        prompt = OPENING.format(selection=selection) + CLOSING
        with open(os.path.join(folder, 'error.txt'), 'w', encoding='utf-8') as f:
            f.write(repr(e))

    with open(os.path.join(folder, 'prompt.md'), 'w', encoding='utf-8') as f:
        f.write(prompt)
    with open(os.path.join(folder, 'header.txt'), 'w', encoding='utf-8') as f:
        f.write(header(selection))
    with open(os.path.join(folder, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump({'title': title(selection), 'cwd': cwd, 'session_file': session_file,
                   'pane': pane}, f)
    return folder
