r"""Text that is safe to show a person: a name from a model can't steer the terminal.

Part names come from the model, and a model can come from anybody; they survive a
STEP round trip byte for byte, escape sequences included. Printed raw, a name could
retitle the window or rewrite the screen (an escape sequence), print a line of its
own such as a forged summary (a carriage return or newline), or show its text in
another order than it is stored (a bidirectional override).

Everything wrenchroom prints for a person goes through :func:`printable`, which
writes each such character as a visible escape (``\x1b``, ``\u202e``) and leaves
every other character alone, accents and CJK included. The JSON report keeps names
exactly: its encoder escapes control characters itself, and a machine reading it
wants the real name.
"""

from __future__ import annotations

import re

#: The characters that can steer a terminal or disguise text: C0 controls
#: (escape, bell, backspace, tab, carriage return, newline...), DEL and the C1
#: controls (0x9b is a one-byte escape sequence on some terminals), the line and
#: paragraph separators, and the bidirectional marks, embeddings, overrides and
#: isolates.
UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def printable(text: str) -> str:
    """The text with every steering character written out as a visible escape."""
    return UNSAFE.sub(_escape, text)


def _escape(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"  # noqa: PLR2004
