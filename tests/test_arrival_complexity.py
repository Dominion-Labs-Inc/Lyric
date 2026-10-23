"""How complex what arrives is, measured once by the reasoning authority, and read where it is needed.

The score is the larger of two measured parts (`NeuralSymbolicBridge.complexity_of`): the thinking it asks for, by the
kinds of thinking its meaning asks for and how hard each has been (`reasoning_difficulty`), between the easiest kind
and the hardest; and what of it is unknown, the share of its words no taught construction holds or of its sentences
nothing reads. No store.
"""

from core.reasoning.neural_bridge import NeuralSymbolicBridge
from core.semantics.derived_reader import Lexical, Meaning, MeaningFact, PatternInventory
from core.semantics.sentence_machine import Piece


def _knowing(*words):
    """A view holding these words, each as a word taught."""
    view = PatternInventory()
    for word in words:
        view.add(Lexical((Piece(word, True),), word))
    return view


def test_the_thinking_asked_for_is_as_hard_as_its_hardest_kind():
    bridge = NeuralSymbolicBridge()          # measured nothing yet: each kind at its declared prior
    view = _knowing("smoke", "causes", "fire", "a", "robin", "is", "bird")
    caused = Meaning("tell", (MeaningFact("causes", "smoke", "fire"),))
    kind = Meaning("tell", (MeaningFact("isa", "robin", "bird"),))
    assert bridge.complexity_of("smoke causes fire", caused, inventory=view) == 1.0, "causal: the hardest kind"
    assert bridge.complexity_of("a robin is a bird", kind, inventory=view) == 0.0, "is-a: the easiest kind"


def test_what_of_it_is_unknown_is_complexity():
    bridge = NeuralSymbolicBridge()
    view = _knowing("a", "robin", "is")
    kind = Meaning("tell", (MeaningFact("isa", "robin", "zorbel"),))
    assert bridge.complexity_of("a robin is zorbel", kind, inventory=view) == 0.25, "one word of four never met"
    assert bridge.complexity_of("whatever this says", inventory=PatternInventory()) == 1.0, "nothing of it read"
    assert bridge.complexity_of("", inventory=view) == 0.0

