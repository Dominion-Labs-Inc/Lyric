#!/usr/bin/env python3
"""The keys' pattern finds exactly what the alternation of every key form, longest first, found.

It is written as a tree of the forms' beginnings (`secrets._one_pattern`) so a long text costs one look per letter
rather than one per form per letter: 267 forms over a belief's 2.7 million characters of evidence took 0.77 s as an
alternation. These forms are made up; no key is read.
"""

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.security.secrets import _forms, _one_pattern  # noqa: E402

VALUES = ["sk-test-abcdefgh12345678", "sk-test-abcdefgh9999", "ghp_0000aaaa1111bbbb", "ghp_0000aaaa", "zz-only-one-key"]
FORMS = sorted({form for value in VALUES for form in _forms(value)})
ALTERNATION = re.compile("|".join(re.escape(f) for f in sorted(FORMS, key=len, reverse=True)))
TREE = re.compile(_one_pattern(FORMS))


def _found(pattern, text):
    return [(m.start(), m.group(0)) for m in pattern.finditer(text)]


def test_every_form_is_found_alone_and_in_text():
    for form in FORMS:
        for text in (form, f"x{form}y", f"{form}{form}", f'{{"note": "{form}"}}'):
            assert _found(TREE, text) == _found(ALTERNATION, text)


def test_the_longest_form_wins_where_one_begins_another():
    # A padded base64 form begins with its unpadded twin, and one key here begins another.
    text = "before sk-test-abcdefgh12345678 after ghp_0000aaaa1111bbbb and ghp_0000aaaa"
    assert _found(TREE, text) == _found(ALTERNATION, text)
    assert ("sk-test-abcdefgh12345678" in [m for _, m in _found(TREE, text)])
    assert ("ghp_0000aaaa1111bbbb" in [m for _, m in _found(TREE, text)])


def test_mixed_texts_match_the_alternation():
    rng = random.Random(11)
    letters = 'abcdefghXYZ0123456789{}":, =-_/+'
    for _ in range(2000):
        parts = []
        for _ in range(10):
            pick = rng.random()
            if pick < 0.3:
                parts.append(rng.choice(FORMS))
            elif pick < 0.5:
                form = rng.choice(FORMS)
                parts.append(form[:rng.randint(1, len(form) - 1)])
            else:
                parts.append("".join(rng.choice(letters) for _ in range(rng.randint(0, 20))))
        text = "".join(parts)
        assert _found(TREE, text) == _found(ALTERNATION, text)
