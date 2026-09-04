#!/usr/bin/env python3
"""Recognising a NUMBER or a DATE in text, so the store can hold one as a thing.

A concept is a named thing, and the door refused a bare number because `1530`
names no thing the way `robin` does. That was right for a mis-read word and
wrong for a numeral: a number DOES name a thing -- a quantity -- and a date
names a point in time. `1530s isa decade`, `battle occurred_in 1530`, and
`price is 3.14` are facts, and the reason they could not be admitted was not
that they were nonsense but that the store had no notion of a LITERAL.

This is that notion, and it is the same shape as `arithmetic_reading` and
`genericity`: classify the surface form DETERMINISTICALLY, hand back a typed
value, and let the store hold it. The grammar is deliberately narrow -- a form
it cannot read returns None and the term is treated as an ordinary word, which
for junk digits means the door refuses it exactly as before. A recogniser that
guesses is worse than one that declines: reading `9/11` as the eleventh of
September would invent a date nobody wrote, when the thing meant is the name of
an event.

NO MODEL IS INVOLVED. The FORM is given (these regexes, like `COPULA` is given
to the sentence machine); the VALUE is derived from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

#: A quantity -- how many, how much. The store holds it so a count or a measure
#: can be a term without being mistaken for a word.
QUANTITY = "quantity"
#: A point in time. Held ISO-canonical so the same day written two ways is one
#: thing, the way `the ladder` and `ladder` are.
TEMPORAL = "temporal"

#: The literal KINDS, finer than the two concept types above. `decade` and
#: `year` are both quantities to the store but different things to a reader, and
#: keeping the distinction here means a later stage can use it without re-deriving.
CARDINAL = "cardinal"
DECIMAL = "decimal"
ORDINAL = "ordinal"
YEAR = "year"
DECADE = "decade"
DATE = "date"

#: kind -> the concept type the store files it under.
_CONCEPT_TYPE = {
    CARDINAL: QUANTITY, DECIMAL: QUANTITY, ORDINAL: QUANTITY,
    YEAR: QUANTITY, DECADE: QUANTITY, DATE: TEMPORAL,
}


@dataclass(frozen=True)
class Literal:
    """A number or a date, read off its surface form.

    `canonical` is the identity-bearing form -- what the store keys on, so
    `1530s` and `1530S` are one thing and `2026-8-6` and `2026-08-06` are one
    day. `value` is the thing itself: an int/float for a quantity, a `date` for
    a date. `kind` is the fine class; `concept_type` is the store's coarse one.
    """
    kind: str
    canonical: str
    value: object
    surface: str

    @property
    def concept_type(self) -> str:
        return _CONCEPT_TYPE[self.kind]


_DECADE = re.compile(r"^(\d{1,4})0s$")
_ORDINAL_NUM = re.compile(r"^(\d+)(st|nd|rd|th)$")
_DECIMAL = re.compile(r"^[+-]?\d+\.\d+$")
_CARDINAL = re.compile(r"^[+-]?\d+$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
#: A slash date is admitted ONLY with a year. `9/11` and `24/7` have none, are
#: month/day-ambiguous, and are in fact the names of things -- so they stay
#: unread here and the door refuses them as the proper names they are.
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
#: `september 11`, `sep 11 2001`, `11 september 2001`.
_MONTH_DAY = re.compile(
    rf"^(?P<month>{_MONTH_ALT})\s+(?P<day>\d{{1,2}})(?:,?\s+(?P<year>\d{{4}}))?$",
    re.IGNORECASE)
_DAY_MONTH = re.compile(
    rf"^(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_ALT})(?:,?\s+(?P<year>\d{{4}}))?$",
    re.IGNORECASE)


def _valid_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:                       # 2026-02-31 is not a day
        return None


def classify_literal(term: str) -> Optional[Literal]:
    """The number or date this term names, or None if it names neither.

    Order matters: the most specific form wins, so `1530s` is a DECADE before it
    is a run of digits, and a decimal is a DECIMAL before its integer part could
    look like a cardinal.
    """
    if term is None:
        return None
    surface = str(term).strip()
    if not surface:
        return None
    low = surface.lower()

    m = _DECADE.match(low)
    if m:
        base = int(m.group(1)) * 10
        return Literal(DECADE, f"{base}s", base, surface)

    m = _ORDINAL_NUM.match(low)
    if m:
        return Literal(ORDINAL, f"{int(m.group(1))}{m.group(2)}", int(m.group(1)), surface)

    m = _ISO_DATE.match(low)
    if m:
        d = _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return Literal(DATE, d.isoformat(), d, surface)
        return None

    m = _SLASH_DATE.match(low)
    if m:
        month, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:                         # a two-digit year is this century
            yr += 2000
        d = _valid_date(yr, month, day)      # read US month/day; validity guards it
        if d:
            return Literal(DATE, d.isoformat(), d, surface)
        return None

    for pattern in (_MONTH_DAY, _DAY_MONTH):
        m = pattern.match(low)
        if m:
            month = _MONTHS[m.group("month").lower()]
            day = int(m.group("day"))
            year = int(m.group("year")) if m.group("year") else None
            if year is not None:
                d = _valid_date(year, month, day)
                if not d:
                    return None
                return Literal(DATE, d.isoformat(), d, surface)
            # A day with no year is a recurring calendar point; keep it as the
            # month-day it is rather than inventing a year.
            if 1 <= day <= 31:
                return Literal(DATE, f"{month:02d}-{day:02d}", (month, day), surface)
            return None

    if _DECIMAL.match(low):
        return Literal(DECIMAL, str(float(low)), float(low), surface)

    if _CARDINAL.match(low):
        return Literal(CARDINAL, str(int(low)), int(low), surface)

    return None


def is_literal(term: str) -> bool:
    return classify_literal(term) is not None
