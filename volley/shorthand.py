"""Keyboard shorthand for entering an event without touching the mouse.

Working from video, typing `7 k` is several times faster than three clicks,
so this is the primary entry path and the button grid is the fallback.

Accepted forms::

    <number> <compact>            7 k        -> #7 ATTACK kill
    <number> <action> <result>    7 a k      -> #7 ATTACK kill
                                  12 r p     -> #12 RECEPTION perfect
                                  4 b kill   -> #4 BLOCK kill
"""

from __future__ import annotations

from . import schema

# --- two-token compact codes ------------------------------------------------
# Bare digits read as a reception rating, which is how a passing chart is
# normally written down (`7 3` = player 7 passed a 3).
COMPACT = {
    "k": (schema.ATTACK, "kill"),
    "kill": (schema.ATTACK, "kill"),
    "e": (schema.ATTACK, "error"),
    "ae": (schema.ATTACK, "error"),
    "a0": (schema.ATTACK, "attempt"),
    "att": (schema.ATTACK, "attempt"),
    "ace": (schema.SERVE, "ace"),
    "se": (schema.SERVE, "error"),
    "si": (schema.SERVE, "in"),
    "sv": (schema.SERVE, "in"),
    "d": (schema.DIG, "dig"),
    "dig": (schema.DIG, "dig"),
    "de": (schema.DIG, "error"),
    "bk": (schema.BLOCK, "kill"),
    "bs": (schema.BLOCK, "kill"),     # "block stuff"
    "bt": (schema.BLOCK, "attempt"),
    "b0": (schema.BLOCK, "attempt"),
    "be": (schema.BLOCK, "error"),
    "as": (schema.SET, "assist"),
    "ast": (schema.SET, "assist"),
    "s0": (schema.SET, "attempt"),
    "ste": (schema.SET, "error"),
    "p": (schema.RECEPTION, "perfect"),
    "3": (schema.RECEPTION, "perfect"),
    "ok": (schema.RECEPTION, "playable"),
    "g": (schema.RECEPTION, "playable"),
    "2": (schema.RECEPTION, "playable"),
    "1": (schema.RECEPTION, "playable"),
    "re": (schema.RECEPTION, "error"),
    "0": (schema.RECEPTION, "error"),
}

# --- three-token aliases ----------------------------------------------------
# "s" is serve; set needs the longer "st" because serve is entered far more often.
ACTION_ALIASES = {
    "a": schema.ATTACK,
    "at": schema.ATTACK,
    "att": schema.ATTACK,
    "attack": schema.ATTACK,
    "h": schema.ATTACK,
    "s": schema.SERVE,
    "sv": schema.SERVE,
    "serve": schema.SERVE,
    "b": schema.BLOCK,
    "bl": schema.BLOCK,
    "block": schema.BLOCK,
    "d": schema.DIG,
    "dig": schema.DIG,
    "r": schema.RECEPTION,
    "rec": schema.RECEPTION,
    "reception": schema.RECEPTION,
    "p": schema.RECEPTION,
    "pass": schema.RECEPTION,
    "st": schema.SET,
    "set": schema.SET,
}

RESULT_ALIASES = {
    schema.SERVE: {
        "a": "ace", "ace": "ace",
        "i": "in", "in": "in", "ok": "in",
        "e": "error", "err": "error", "error": "error",
    },
    schema.ATTACK: {
        "k": "kill", "kill": "kill",
        "a": "attempt", "att": "attempt", "attempt": "attempt", "0": "attempt", "ok": "attempt",
        "e": "error", "err": "error", "error": "error",
    },
    schema.BLOCK: {
        "k": "kill", "kill": "kill", "s": "kill", "solo": "kill", "stuff": "kill",
        "a": "attempt", "att": "attempt", "attempt": "attempt", "t": "attempt",
        "touch": "attempt", "0": "attempt",
        "e": "error", "err": "error", "error": "error",
    },
    schema.DIG: {
        "d": "dig", "dig": "dig", "ok": "dig",
        "e": "error", "err": "error", "error": "error",
    },
    schema.RECEPTION: {
        "p": "perfect", "perfect": "perfect", "3": "perfect",
        "ok": "playable", "playable": "playable", "g": "playable", "good": "playable",
        "2": "playable", "1": "playable", "po": "playable", "poor": "playable",
        "e": "error", "err": "error", "error": "error", "0": "error",
    },
    schema.SET: {
        "a": "assist", "ast": "assist", "assist": "assist",
        "0": "attempt", "att": "attempt", "attempt": "attempt", "t": "attempt",
        "e": "error", "err": "error", "error": "error",
    },
}

HELP = """\
`7 k` kill · `7 a0` attempt · `7 e` attack error
`7 ace` ace · `7 si` serve in · `7 se` serve error
`7 p` perfect pass · `7 ok` playable · `7 re` reception error
`7 d` dig · `7 de` dig error
`7 bk` block point · `7 bt` block touch · `7 be` block error
`7 as` set assist · `7 s0` set · `7 ste` set error
Or spell it out: `7 attack kill`, `12 rec perfect`, `4 block kill`
"""


class ShorthandError(ValueError):
    """Raised when a shorthand line cannot be understood."""


def parse(text: str) -> dict:
    """Parse one shorthand line into {number, action, result}.

    Raises ShorthandError with a message meant to be shown to the user.
    """
    tokens = str(text).replace(",", " ").split()
    if not tokens:
        raise ShorthandError("nothing to parse")

    raw_number = tokens[0].lstrip("#")
    if not raw_number.isdigit():
        raise ShorthandError(f"{tokens[0]!r} is not a jersey number")
    number = int(raw_number)

    rest = [t.lower() for t in tokens[1:]]
    if not rest:
        raise ShorthandError(f"#{number} what? add an action, e.g. `{number} k`")

    if len(rest) == 1:
        code = rest[0]
        if code not in COMPACT:
            raise ShorthandError(f"{code!r} is not a known shortcut")
        action, result = COMPACT[code]
    elif len(rest) == 2:
        action_token, result_token = rest
        if action_token not in ACTION_ALIASES:
            raise ShorthandError(f"{action_token!r} is not a known action")
        action = ACTION_ALIASES[action_token]
        result = RESULT_ALIASES[action].get(result_token)
        if result is None:
            valid = ", ".join(schema.ACTIONS[action])
            raise ShorthandError(
                f"{result_token!r} is not a valid {action} result (expected: {valid})"
            )
    else:
        raise ShorthandError("too many words - use `7 k` or `7 attack kill`")

    action, result = schema.validate(action, result)
    return {"number": number, "action": action, "result": result}
