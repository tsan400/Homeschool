import pytest

from hs.grade import check


@pytest.mark.parametrize("text,key,form,expected", [
    ("35", "35", "value", True),
    ("1,542", "1542", "value", True),
    ("34", "35", "value", False),
    ("3/4", "3/4", "lowest", True),
    ("6/8", "3/4", "lowest", False),       # not simplified
    ("6/8", "3/4", "value", True),
    ("0.75", "3/4", "lowest", True),
    ("1 1/4", "5/4", "lowest", True),      # mixed or improper both fine
    ("5/4", "1 1/4", "lowest", True),
    ("1 2/8", "5/4", "lowest", False),
    ("-5", "-5", "value", True),
    ("−5", "-5", "value", True),      # unicode minus
    ("x = 7", "7", "value", True),
    ("2.50", "2.5", "value", True),
    (".5", "0.5", "value", True),
    ("40%", "40", "value", True),
    ("12 R3", "12 R3", "remainder", True),
    ("12r3", "12 R3", "remainder", True),
    ("12 R2", "12 R3", "remainder", False),
    ("12", "12", "remainder", True),
    ("12 R0", "12", "remainder", True),
    ("seven", "7", "value", None),
    ("", "7", "value", None),
])
def test_check(text, key, form, expected):
    assert check(text, key, form) is expected
