import pytest

from volley import schema
from volley.shorthand import ShorthandError, parse


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7 k", (7, schema.ATTACK, "kill")),
        ("#7 k", (7, schema.ATTACK, "kill")),
        ("7 e", (7, schema.ATTACK, "error")),
        ("7 a0", (7, schema.ATTACK, "attempt")),
        ("7 p", (7, schema.RECEPTION, "perfect")),
        ("7 ok", (7, schema.RECEPTION, "playable")),
        ("7 re", (7, schema.RECEPTION, "error")),
        ("7 bt", (7, schema.BLOCK, "attempt")),
        ("7 s0", (7, schema.SET, "attempt")),
        ("7 ace", (7, schema.SERVE, "ace")),
        ("7 se", (7, schema.SERVE, "error")),
        ("12 3", (12, schema.RECEPTION, "perfect")),
        ("12 2", (12, schema.RECEPTION, "playable")),
        ("12 0", (12, schema.RECEPTION, "error")),
        ("4 d", (4, schema.DIG, "dig")),
        ("4 bk", (4, schema.BLOCK, "kill")),
        ("4 bs", (4, schema.BLOCK, "kill")),
        ("2 as", (2, schema.SET, "assist")),
    ],
)
def test_compact_codes(text, expected):
    parsed = parse(text)
    assert (parsed["number"], parsed["action"], parsed["result"]) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7 a k", (7, schema.ATTACK, "kill")),
        ("7 attack kill", (7, schema.ATTACK, "kill")),
        ("7 A K", (7, schema.ATTACK, "kill")),
        ("12 r p", (12, schema.RECEPTION, "perfect")),
        ("12 rec error", (12, schema.RECEPTION, "error")),
        ("12 pass good", (12, schema.RECEPTION, "playable")),
        ("4 block kill", (4, schema.BLOCK, "kill")),
        ("4 b a", (4, schema.BLOCK, "attempt")),
        ("9 s ace", (9, schema.SERVE, "ace")),
        ("2 set assist", (2, schema.SET, "assist")),
        ("2 st e", (2, schema.SET, "error")),
        ("  7   a   k  ", (7, schema.ATTACK, "kill")),
        ("7, a, k", (7, schema.ATTACK, "kill")),
    ],
)
def test_spelled_out(text, expected):
    parsed = parse(text)
    assert (parsed["number"], parsed["action"], parsed["result"]) == expected


def test_serve_is_s_and_set_is_st():
    assert parse("9 s a")["action"] == schema.SERVE
    assert parse("9 st a")["action"] == schema.SET


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "ana k",          # not a jersey number
        "7",              # no action
        "7 zz",           # unknown shortcut
        "7 q k",          # unknown action
        "7 a zzz",        # invalid result for the action
        "7 s k",          # kill is not a serve result
        "7 d k",          # kill is not a dig result
        "7 a k extra",    # too many tokens
    ],
)
def test_rejects_garbage(text):
    with pytest.raises(ShorthandError):
        parse(text)


def test_error_message_lists_valid_results():
    with pytest.raises(ShorthandError) as excinfo:
        parse("7 dig zzz")
    assert "dig" in str(excinfo.value) and "error" in str(excinfo.value)


def test_every_result_in_the_taxonomy_is_reachable():
    """No action/result pair should be impossible to type."""
    for action, results in schema.ACTIONS.items():
        for result in results:
            parsed = parse(f"7 {action.lower()} {result}")
            assert (parsed["action"], parsed["result"]) == (action, result)
