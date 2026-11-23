# claude-wait-what

Select a passage in a Claude Code session, press a key, and a second Claude
opens beside it to discuss that passage, without interrupting the first one's
work.

![Demo: in the main session Claude lists what is missing to launch a weather balloon; the user selects "Kessler KV-20 valve" and presses Ctrl+A; a side window opens and explains it, while the main session goes on writing an email.](assets/cww-demo.gif)

## How it works

1. **The hook.** When a Claude Code session starts, a `SessionStart` hook
   records which terminal pane it runs in (Kitty, Konsole, tmux and WezTerm
   expose a pane id in the environment) and the path of its session file.
2. **The trigger.** You select a passage and press the key. The adapter for
   your terminal reads the selection and knows which pane it came from, so
   the session is known, not guessed.
3. **The source.** The passage is located in the session file. On screen the
   text is rendered (wrapped lines, bullets, no markdown symbols); in the file
   it is raw markdown. Both are reduced to letters and digits before
   comparing, so they match.
4. **The side instance.** A new Claude Code instance opens next to the first,
   in the same project directory. It receives the passage, the message it
   comes from and the two before it, plus the whole conversation exported as
   plain text, to read only if needed. It cannot edit files, and it sizes its
   answer to your question: a few lines for "what does this term mean?", more
   context for "why this choice?".

If the pane is unknown (a terminal without an adapter, or a session started
before the hook was installed), the passage is searched for in recently
modified sessions.

## Supported terminals

| Terminal  | Trigger | Opens | Tested |
|-----------|---------|-------|--------|
| Kitty     | select, then `Ctrl+A` | a tab in a separate window, with the colors of the source pane | yes |
| Konsole   | select, then a desktop shortcut | a tab in the same window | yes |
| tmux      | `Ctrl+A` in copy mode, or `prefix a` after a mouse selection | a new tmux window | end to end, scripted |
| any other | select, then a desktop shortcut | a window of your default terminal | yes, with Konsole as the default |
| WezTerm   | — | not written yet (the hook already records its panes) | — |

In Kitty, `Ctrl+A` keeps its usual meaning (beginning of line) when nothing is
selected. In tmux the binding exists only in copy mode, so `Ctrl+A` elsewhere
is untouched.

## Install

Requirements: Linux, Python 3.10+, Claude Code. No other dependencies.

    git clone https://github.com/leonardocppn/claude-wait-what.git

Below, `/path/to/claude-wait-what` is where you cloned it.

**1. The hook.** Add it to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command",
          "command": "python3 -I /path/to/claude-wait-what/bin/wait-what hook" } ] }
    ]
  }
}
```

Sessions started before this step still work: their passage is searched for.

**2. Trust the working directory, once.** Each side instance gets a folder
under `~/.cache/claude-wait-what/`, and Claude Code asks whether to trust it.
Trusting the parent once covers them all:

    mkdir -p ~/.cache/claude-wait-what && cd ~/.cache/claude-wait-what && claude
    # accept, then /exit

**3. Your terminal.**

*Kitty.* In `kitty.conf`:

    map ctrl+a kitten /path/to/claude-wait-what/adapters/kitty/wait_what_kitty.py pass-ctrl-a

Side instances open as tabs of a separate window of class `claude-wait-what`;
a window manager rule can place it, for instance on the right half of the
screen.

*Konsole.* Konsole cannot bind a key to a command, and since version 26 it
does not let other programs type into its tabs. It needs a dedicated profile,
created once (then restart Konsole, which reads profiles at startup):

    /path/to/claude-wait-what/bin/wait-what install-konsole

plus the desktop shortcut described under *any other terminal*.

*tmux.*

    /path/to/claude-wait-what/bin/wait-what install-tmux

writes a ready config and prints the `source-file` line to add to
`~/.tmux.conf`.

*Any other terminal.* Bind a desktop shortcut to

    python3 -I /path/to/claude-wait-what/bin/wait-what anywhere

(KDE: System Settings → Keyboard → Shortcuts → Add New → Command or Script;
GNOME: Settings → Keyboard → Custom Shortcuts). Pick a combination with the
Super key: a desktop shortcut takes the key away from every application.

It reads the primary selection (whatever text was last selected), so it needs
`wl-paste` (package `wl-clipboard`) on Wayland, or `xclip` or `xsel` on X11.
The terminal it opens is, in order: the command in `$WAIT_WHAT_TERMINAL` (the
command to run is appended to it), `xdg-terminal-exec`, or the first known
terminal installed, preferring your desktop's own. If the source session runs
in Konsole and the profile is installed, it opens a tab there instead.

## What the side instance receives

Appended to its system prompt:

- the passage;
- the message it comes from and the two before it, each capped at 8,000
  characters (the second one is there because a short question, such as "and
  point 3?", needs the answer it refers to);
- the path of the whole conversation as plain text, with the source message
  marked;
- instructions: wait for the question, size the answer to it, reply in the
  user's language, do not edit files.

It starts in the working directory of the source session, so it loads the same
`CLAUDE.md` and memory. `Edit`, `Write` and `NotebookEdit` are disabled;
reading is allowed, so it can open project files when the question needs them.

Each side instance has a folder in `~/.cache/claude-wait-what/tangents/`:
`prompt.md` is exactly what it received, `conversation.md` the exported
conversation. Folders older than 7 days are deleted.

## Limitations

- **Claude Code's session files are not a public API.** Only a few fields are
  read, but a change in their format can break the search for the source
  message. The side instance still opens, with the passage alone.
- **The same passage in two messages**: the most recent one wins. A passage
  that spans two messages is matched by its beginning or its end.
- **Universal adapter**: the primary selection is the last text selected
  anywhere, and the session is guessed among those modified in the last 12
  hours.
- **Konsole**: tabs need the profile and one restart; colors are not
  inherited.
- **Cost**: every side instance is a new session, with its own system prompt
  and `CLAUDE.md`. Reading the whole conversation, when the instance decides
  it needs it, costs more.

## Writing an adapter

An adapter supplies three things:

1. **A trigger that reads the selection.**
2. **The key of the pane** the selection comes from, the same that the hook
   computes from the environment (`wait_what/registry.py`, `pane_key()`). For
   a new terminal, add a branch there that reads its pane id.
3. **A place to open the instance**, running `wait-what run FOLDER`.

In between, the core does the rest:

    echo "$SELECTION" | wait-what prepare --pane KEY
    # → {"folder": "...", "title": "» ...", "cwd": "...", ...}

Without `--pane`, the session is searched for. If the terminal can open a tab
with a fixed command but cannot pass it an argument, write the folder with
`wait_what.pending.write()` and start `wait-what run --pending` (this is what
the Konsole profile does).

Tests: `python3 -m unittest discover tests`

## License

MIT, see [LICENSE](LICENSE).

Unofficial project, not affiliated with or endorsed by Anthropic. Claude and
Claude Code are trademarks of Anthropic.
