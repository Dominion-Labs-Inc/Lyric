#!/usr/bin/env python3
"""What an instance or an agent is called.

`queue_a3f91c0d4e21` is an identifier. It is unique, it joins correctly, and
nobody can hold it in their head or say it out loud. Two of them side by side
in a console are indistinguishable at a glance, which is the moment a name
starts to matter: the point of a name is that a person can tell one thing from
another and refer to it afterwards.

So every instance and every agent gets a name of three words:

    tidal-amber-falcon
    candid-slate-harbor

DERIVED, NOT STORED. The name comes from the identifier by hash, so the same
instance is called the same thing everywhere -- in the console, in a log line,
in a conversation about it next week -- with nothing written down and no column
to migrate. Identifiers already in `unified.queue_instances` get their names
the moment anything asks, without a single row changing.

THE IDENTIFIER IS STILL THE KEY. A name is for people. Nothing joins on one,
and `name_for` is not reversible: two identifiers can land on the same name,
which is harmless where a name is read and never looked up.

There are 64 x 64 x 64 = 262,144 names.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import List

#: Three lists rather than one used three times, so a name reads as a phrase
#: instead of a bag of words. Nothing here is a person, a place anybody owns, or
#: a word that means something inside Lyric already -- a thing called "memory"
#: or "domain" would be read as the faculty rather than as a name.
FIRST: List[str] = [
    'amber', 'arctic', 'ashen', 'autumn', 'azure', 'bright', 'brisk', 'candid',
    'carbon', 'cedar', 'cobalt', 'copper', 'coral', 'crimson', 'dusky', 'eager',
    'ember', 'fallow', 'fleet', 'frosted', 'gilded', 'glacial', 'golden', 'hollow',
    'indigo', 'ivory', 'jade', 'keen', 'lucid', 'lunar', 'marble', 'mellow',
    'midnight', 'misty', 'northern', 'nimble', 'opal', 'patient', 'pewter', 'quiet',
    'rapid', 'russet', 'saffron', 'sable', 'scarlet', 'silent', 'silver', 'slate',
    'solar', 'steady', 'stormy', 'sunlit', 'tidal', 'timber', 'umber', 'upland',
    'velvet', 'verdant', 'vivid', 'walnut', 'wandering', 'winter', 'woven', 'zephyr',
]

SECOND: List[str] = [
    'alloy', 'anchor', 'aurora', 'basalt', 'beacon', 'birch', 'bramble', 'canyon',
    'cinder', 'clover', 'comet', 'current', 'delta', 'drift', 'dune', 'echo',
    'ember', 'fathom', 'fenwick', 'flint', 'forge', 'gable', 'granite', 'harrow',
    'hazel', 'horizon', 'juniper', 'kestrel', 'lantern', 'ledger', 'lichen', 'linden',
    'marrow', 'meadow', 'mercury', 'meridian', 'mirror', 'moorland', 'nickel', 'obsidian',
    'orchard', 'pennant', 'pine', 'quarry', 'quartz', 'reed', 'ridge', 'rosewood',
    'sable', 'sandstone', 'shale', 'sierra', 'solstice', 'spindle', 'summit', 'thicket',
    'thistle', 'tundra', 'vellum', 'vesper', 'willow', 'windrow', 'yarrow', 'zenith',
]

THIRD: List[str] = [
    'albatross', 'auger', 'badger', 'bastion', 'bellows', 'bittern', 'bowline', 'caldera',
    'capstan', 'cascade', 'chandler', 'cormorant', 'crucible', 'dovetail', 'escarpment', 'falcon',
    'fathom', 'ferrule', 'foundry', 'gantry', 'gyre', 'halyard', 'harbor', 'hawthorn',
    'heron', 'inlet', 'jetty', 'kiln', 'lantern', 'lattice', 'lighthouse', 'lodestone',
    'magpie', 'mariner', 'merlin', 'millrace', 'mooring', 'osprey', 'parapet', 'pelican',
    'pilgrim', 'plover', 'quarry', 'quill', 'rampart', 'raven', 'sextant', 'shearwater',
    'skiff', 'sparrow', 'spire', 'stanchion', 'starling', 'tanager', 'teal', 'threshold',
    'trestle', 'vantage', 'viaduct', 'warbler', 'watchman', 'weaver', 'wheelhouse', 'wren',
]

_LISTS = (FIRST, SECOND, THIRD)


def name_for(identifier: str) -> str:
    """The name this identifier is always called.

    Stable across processes and machines: a plain SHA-256 of the identifier,
    not `hash()`, which is salted per process and would call the same instance
    something different in the console and in the log.
    """
    if not identifier:
        return 'unnamed'
    digest = hashlib.sha256(str(identifier).encode('utf-8')).digest()
    # Six bits per word, taken from bytes far enough apart not to correlate.
    return '-'.join(words[digest[index * 7] % len(words)]
                    for index, words in enumerate(_LISTS))


def new_name() -> str:
    """A name for something that has no identifier yet."""
    return '-'.join(secrets.choice(words) for words in _LISTS)


def looks_like_a_name(text: str) -> bool:
    """Whether `text` is one of these names rather than an identifier."""
    parts = str(text).split('-')
    return (len(parts) == 3
            and all(part in words for part, words in zip(parts, _LISTS)))


__all__ = ['name_for', 'new_name', 'looks_like_a_name', 'FIRST', 'SECOND', 'THIRD']
