"""Function-granularity source surgery + differential behavior verification.
Pure and fast — code improvement operates on ONE function, extracted to valid
top-level source, differentially verified, and spliced back preserving indentation.
A change that alters the signature or any output is rejected."""
from core.learning.enhanced_asi_self_improvement import (
    list_module_functions, extract_function_source, splice_function_source,
    verify_behavior_preserved)

MODULE = ("import logging\nlogger = logging.getLogger(__name__)\n\n"
          "class Worker:\n"
          "    def collect(self, items):\n"
          "        result = []\n"
          "        for x in items:\n"
          "            result.append(x * 2)\n"
          "        return result\n\n"
          "    def other(self):\n"
          "        return 1\n")


def test_extract_dedents_to_valid_source():
    import ast
    ded, ln, end, col = extract_function_source(MODULE, "Worker.collect")
    ast.parse(ded)  # dedented method is valid top-level code
    assert col == 4 and ded.startswith("def collect(self, items):")


def test_splice_replaces_only_the_target_function():
    import ast
    new_fn = "def collect(self, items):\n    return [x * 2 for x in items]\n"
    spliced = splice_function_source(MODULE, "Worker.collect", new_fn)
    ast.parse(spliced)  # module still parses
    assert "return [x * 2 for x in items]" in spliced
    assert "def other(self):" in spliced          # sibling untouched
    assert "logger = logging.getLogger" in spliced  # module body untouched


def test_list_functions_includes_methods_with_qualnames():
    quals = [q for q, *_ in list_module_functions(MODULE)]
    assert quals == ["Worker.collect", "Worker.other"]


def test_differential_verifier_accepts_equivalent_rejects_bugs():
    old = ("def collect(items: list):\n    r = []\n    for x in items:\n"
           "        r.append(x * 2)\n    return r\n")
    good = "def collect(items: list):\n    return [x * 2 for x in items]\n"
    bug = "def collect(items: list):\n    return [x * 3 for x in items]\n"
    sig = "def collect(items: list, k: int):\n    return [x * 2 for x in items]\n"
    method = "def collect(self, items: list):\n    return [x * 2 for x in items]\n"

    assert verify_behavior_preserved(old, good)[0] == "verified"
    assert verify_behavior_preserved(old, bug)[0] == "behavior_changed"
    assert verify_behavior_preserved(old, sig)[0] == "signature_changed"
    assert verify_behavior_preserved(method, method)[0] == "unverifiable"
