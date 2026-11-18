"""WHAT A RUNNING PROCESS CAN TAKE FROM A CHANGED FILE (`CodeAdoption`), where the running object is not the plain
function the file declares.

A property and a decorator-built wrapper are both a function ONE LEVEL DOWN, and reaching only as far as
staticmethod and classmethod meant no module holding either could be taken up while it ran. Measured on
2026-11-17: a change to `core.semantics.grammar` was refused for `Grammar._of_words`, `GrammarView.words`,
`GrammarView.rules` and `reading_teaches` -- not one of which that change touched -- and 49 of the 268 modules
under `core` define a property, so a restart was owed for any edit to any of them.
"""
import contextlib
import importlib.util
import sys
import textwrap

from core.agents.autonomous.autonomous_coordinator import CodeAdoption

HELD = textwrap.dedent('''
    import contextlib

    class Thing:
        @property
        def held(self):
            return 1

        def plain(self):
            return 10

    @contextlib.contextmanager
    def wrapped():
        yield 1
''')

SETS = textwrap.dedent('''
    class Thing:
        @property
        def two_ways(self):
            return self._x

        @two_ways.setter
        def two_ways(self, value):
            self._x = value
''')


def running(tmp_path, name: str, source: str):
    """A module imported from a file, as a substrate imports its own code, and the file it came from."""
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:                                  # pragma: no cover - a subject that will not import
        del sys.modules[name]
        raise
    return module, path


def test_a_read_only_property_and_a_wrapped_function_are_taken_up_while_the_module_runs(tmp_path):
    """The code behind a property and behind a `@contextlib.contextmanager` is swapped IN PLACE, so what the class
    and the module already hold runs the new body with no restart -- which is the point of swapping rather than
    replacing an attribute, since a registry or a tier table holds the object itself.

    `contextlib`'s wrapper PASSES `inspect.isfunction`, so stopping the unwrap at the first function returned the
    wrapper, whose code carries `contextmanager.<locals>.helper` as its qualname, and the change was refused for
    naming a function that was not this one. What decides is `__wrapped__` being there, not what the object looks
    like."""
    module, path = running(tmp_path, "takeable_subject", HELD)
    assert module.Thing().held == 1 and module.Thing().plain() == 10
    with module.wrapped() as given:
        assert given == 1

    changed = HELD.replace("return 1", "return 2").replace("return 10", "return 20").replace("yield 1", "yield 2")
    path.write_text(changed)
    plan = CodeAdoption.plan(module, HELD, changed)
    assert not plan.refused, plan.refused
    assert set(plan.swaps) == {"Thing.held", "Thing.plain", "wrapped"}, plan.swaps

    done = CodeAdoption.apply(module, plan)
    assert done.get("adopted") is True, done
    # THE RUNNING OBJECTS, not a freshly imported copy: no restart, no re-import.
    assert module.Thing().held == 2, "a property's getter runs the new body"
    assert module.Thing().plain() == 20, "and a plain method still does"
    with module.wrapped() as given:
        assert given == 2, "and the function a decorator wrapped does too"


def test_a_property_that_also_sets_is_refused_so_its_getter_keeps_its_own_body(tmp_path):
    """A SETTER IS WRITTEN UNDER THE GETTER'S NAME, and `_shape` keys a function by its qualname, so of
    `@property def x` and `@x.setter def x` only the LAST survives in the shape. Following such a property to its
    getter would put the setter's body into the getter -- a defect, not an adoption -- so one that sets or deletes
    is left exactly as it was and refused as before, and the refusal names what a restart is for."""
    module, path = running(tmp_path, "settable_subject", SETS)
    changed = SETS.replace("return self._x", "return self._x + 1")
    path.write_text(changed)
    plan = CodeAdoption.plan(module, SETS, changed)
    assert not plan.swaps, plan.swaps
    assert [name for name, _ in plan.refused] == ["Thing.two_ways"], plan.refused
    # ALL OF IT OR NONE OF IT: a plan with anything refused performs nothing at all.
    assert CodeAdoption.apply(module, plan).get("adopted") is False


def test_a_function_that_carries_a_wrapped_attribute_is_still_its_own(tmp_path):
    """A FUNCTION MAY CARRY `__wrapped__` AND STILL BE THE FUNCTION THE FILE DECLARES, so the chain is followed
    only where the object in hand is NOT that function -- which its `co_qualname` says. Unwrapping whatever had a
    `__wrapped__` refused this name for the qualname of something else, where it had been swapped correctly
    before: a fix for one refusal that invented another.

    `__wrapped__` is an ordinary attribute and anything may set it, which is the whole reason it cannot decide on
    its own what a name means."""
    frozen = textwrap.dedent('''
        def other():
            return "other"

        def named():
            return 1

        named.__wrapped__ = other
    ''')
    module, path = running(tmp_path, "elsewhere_subject", frozen)
    changed = frozen.replace("return 1", "return 2")
    assert changed != frozen, "the test's own edit must change the source"
    path.write_text(changed)
    plan = CodeAdoption.plan(module, frozen, changed)
    assert not plan.refused, plan.refused
    assert "named" in plan.swaps, plan.swaps
    assert CodeAdoption.apply(module, plan).get("adopted") is True
    assert module.named() == 2, "its own body ran, not the one __wrapped__ points at"
    assert module.other() == "other", "and the function it points at is untouched"


CACHED = textwrap.dedent('''
    import functools

    @functools.lru_cache(maxsize=None)
    def counted(n):
        return n + 1

    class Thing:
        @functools.cached_property
        def once(self):
            return 1

        def plain(self):
            return 10
''')


def test_a_cached_function_is_swapped_and_its_cache_emptied(tmp_path):
    """A cache on the function holds answers THE OLD BODY GAVE, and serving one after the swap is serving code that
    is in no file -- the same fault as a half-taken module, one answer deep. The cache is one object and can be
    emptied, so `apply` empties it.

    `functools.lru_cache` gives back a `_lru_cache_wrapper`, which is not a function at all, so reaching only
    through staticmethod and classmethod said "a function now stands where something else did" and sent the whole
    module to a restart."""
    module, path = running(tmp_path, "cached_subject", CACHED)
    assert module.counted(1) == 2, "and now that answer is cached"

    changed = CACHED.replace("return n + 1", "return n + 100")
    path.write_text(changed)
    plan = CodeAdoption.plan(module, CACHED, changed)
    assert not plan.refused, plan.refused
    assert "counted" in plan.swaps, plan.swaps
    assert CodeAdoption.apply(module, plan).get("adopted") is True
    assert module.counted(1) == 101, "the new body's answer, not the cached one"


def test_a_cached_property_blocks_nothing_until_it_changes_and_is_then_refused(tmp_path):
    """REACHED TO COMPARE, REFUSED TO SWAP. A `cached_property` keeps its value in each instance's own `__dict__`,
    and those instances cannot be found from here, so swapping the code would leave some objects answering with the
    old body and some with the new -- a module in a state nobody wrote.

    But an UNCHANGED one must block nothing, and this is where a module was lost: the plan walks every function the
    file declares, not only the changed ones, so a module was refused for merely CONTAINING a cached property. A
    no-op change to `core.semantics.derived_reader` was refused for nine names -- five caches and four cached
    properties, not one of them touched (2026-11-17)."""
    module, path = running(tmp_path, "cached_property_subject", CACHED)
    # UNCHANGED: the cached property compares equal and asks for nothing, so the module is takeable.
    elsewhere = CACHED.replace("return 10", "return 20")
    path.write_text(elsewhere)
    plan = CodeAdoption.plan(module, CACHED, elsewhere)
    assert not plan.refused, plan.refused
    assert plan.swaps == ("Thing.plain",), plan.swaps
    # CHANGED: refused, and the refusal says where the stale values live.
    path.write_text(CACHED)
    moved = CACHED.replace("        return 1\n", "        return 2\n")
    assert moved != CACHED, "the test's own edit must reach the cached property's body"
    plan = CodeAdoption.plan(module, CACHED, moved)
    assert not plan.swaps, plan.swaps
    assert [name for name, _ in plan.refused] == ["Thing.once"], plan.refused
    assert "each instance" in dict(plan.refused)["Thing.once"], plan.refused
