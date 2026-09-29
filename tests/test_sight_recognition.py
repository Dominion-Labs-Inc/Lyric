#!/usr/bin/env python3
"""Sight knows what it has seen before (`core.perception.vision`, the sight
trace; `senses.sight_agreements`), on real photographs: UKBench, four views of
each object. A seeing keeps its features, never the photograph; the same thing
in another view agrees on one geometry, a different thing does not; the same
picture resized or re-encoded keeps its difference hash. No store and no boot.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from core.perception import senses, vision

REPO = Path(__file__).resolve().parents[1]
UKBENCH = REPO / "test_data" / "vision" / "ukbench" / "full"
needs = pytest.mark.skipif(not UKBENCH.exists(), reason="UKBench is not in test_data")


def _view(i: int) -> str:
    return str(UKBENCH / f"ukbench{i:05d}.jpg")


@needs
def test_a_seeing_keeps_its_features_never_the_picture():
    features = vision.sight_features(_view(0))
    trace = vision.sight_trace_bytes(features)
    back = vision.sight_trace(trace)
    assert np.array_equal(back["descriptors"], features["descriptors"])
    assert back["dhash"] == features["dhash"]
    assert len(trace) < Path(_view(0)).stat().st_size
    keys = vision.keypoint_hashes(features["descriptors"])
    # A picture's keys never overlap a sound's landmark hashes (under 2^26).
    assert len(keys) and int(keys.min()) >= 1 << 28


@needs
def test_the_same_thing_seen_again_agrees_and_another_does_not():
    object_0, other_view, object_10 = (vision.sight_features(_view(i)) for i in (0, 1, 40))
    same, other = senses.sight_agreements(
        object_0, [vision.sight_trace_bytes(other_view), vision.sight_trace_bytes(object_10)])
    # Measured: 393 agreeing for another view of the object, 4 for another object;
    # the cut is 20 (MemoryAgent.SIGHT_MIN_AGREE).
    from core.agents.memory_agent import MemoryAgent
    assert same["agreeing"] >= 5 * MemoryAgent.SIGHT_MIN_AGREE
    assert other["agreeing"] < MemoryAgent.SIGHT_MIN_AGREE


@needs
def test_the_same_picture_resized_and_reencoded_is_the_same_picture(tmp_path):
    from core.agents.memory_agent import MemoryAgent
    img = cv2.imread(_view(0))
    small = tmp_path / "small.jpg"
    cv2.imwrite(str(small), cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2)),
                [cv2.IMWRITE_JPEG_QUALITY, 50])
    got = senses.sight_agreements(vision.sight_features(str(small)),
                                  [vision.sight_trace_bytes(vision.sight_features(_view(0)))])[0]
    assert got["hash_distance"] <= MemoryAgent.SIGHT_SAME_PICTURE


@needs
def test_a_thing_shown_is_held_once_remembered():
    from core.perception.perception_faculty import PerceptionFaculty, _encode
    faculty = PerceptionFaculty()
    assert PerceptionFaculty.lesson_of({"thing": "the green mug"}) == ("thing", "the green mug")
    trace = vision.sight_trace_bytes(vision.sight_features(_view(0)))
    before = faculty.taught_version
    assert faculty.hold_lesson({"lesson": {"thing": "the green mug"}, "trace": _encode(trace)})
    assert "the_green_mug" in faculty._instances and faculty.taught_version == before + 1


def test_seen_before_is_claimed_as_the_same_thing():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    claims = AutonomousCoordinator._sensed_claims(
        "pic2", {"seen_before": [{"memory": "mem_1", "subject": "pic1", "support": 1.0}]})
    assert "pic2 same_thing_as pic1" in claims
    caption = AutonomousCoordinator._heard_before_caption(
        [{"when": "2026-09-29T10:02", "named": ["the green mug"]}], "seen")
    assert caption == '; seen before, 1 time(s), last on 2026-09-29 10:02, as "the green mug"'
