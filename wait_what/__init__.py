"""claude-wait-what: open a side Claude Code instance on a passage you selected.

The core is terminal-agnostic. It knows how to:

- remember which Claude Code session runs in which terminal pane (registry);
- find the message a selected passage comes from (transcript);
- prepare a side instance: context, prompt, exported conversation (prepare);
- start that instance (cli: ``wait-what run``).

Each terminal adapter only supplies the trigger (a key that reads the
selection), the pane identifier and the place where the instance opens.
"""

import os

CACHE = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
                     'claude-wait-what')
