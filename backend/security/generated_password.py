"""Generated passwords an administrator hands to a person.

From `secrets`, never `random`: this is a credential. 16 characters from an
alphabet without the look-alikes (0/O, 1/l/I) because it will be read off a
screen and typed by somebody else, and with at least one lower-case letter,
upper-case letter, digit and symbol so it satisfies any reasonable policy.
About 95 bits of entropy.
"""

from __future__ import annotations

import secrets

LENGTH = 16

_LOWER = "abcdefghijkmnopqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGITS = "23456789"
_SYMBOLS = "!@#$%^&*-_=+?"
_ALL = _LOWER + _UPPER + _DIGITS + _SYMBOLS


def generate_password(length: int = LENGTH) -> str:
    if length < 12:
        raise ValueError("A generated password is at least 12 characters.")
    chars = [secrets.choice(group) for group in (_LOWER, _UPPER, _DIGITS, _SYMBOLS)]
    chars += [secrets.choice(_ALL) for _ in range(length - len(chars))]
    # Shuffle with the same CSPRNG so the four guaranteed classes are not
    # always the first four characters.
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)
