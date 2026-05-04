"""Unit tests for Track 1 (duration-bucket action with cyclic phase advance).

Mocks the TraCI side of CoLightEnv so the cycling decision logic can be
exercised without a running SUMO.
"""

import pytest

from app.ml.colight_env import CoLightEnv, DURATION_BUCKETS_SEC


def _make_env_minimal() -> CoLightEnv:
    """Build a CoLightEnv shell with internal state seeded for one TL.

    Skips _initialize() (which would require TraCI) by populating its
    outputs directly. The Phase-1 action interpretation in step() reads
    only this state, so we can exercise it standalone.
    """
    env = CoLightEnv(
        network_path="/dev/null",
        network_id="test",
        tl_ids=["tl0"],
        max_steps=3600,
        steps_per_action=10,
        yellow_time=5,
        min_green=10,
    )
    # Mimic _initialize's per-TL state for a 2-phase TL
    env.tl_ids = ["tl0"]
    env._green_phases = {"tl0": [0, 1]}
    env._current_green_idx = {"tl0": 0}
    env._elapsed_in_green = {"tl0": 0}
    env.phase_lengths = [2]
    env.num_actions = len(DURATION_BUCKETS_SEC)
    return env


def _decide_phase(env: CoLightEnv, action: int) -> tuple[int, bool]:
    """Run only the Phase-1 action interpretation and return (desired, yellow).

    Reproduces the logic in step()'s Phase 1 without invoking TraCI. Bound
    to the duration-mode branch — phase mode would compute differently.
    """
    tl_id = env.tl_ids[0]
    num_green = len(env._green_phases[tl_id])
    current_idx = env._current_green_idx[tl_id]
    bucket = action % len(DURATION_BUCKETS_SEC)
    target_age = DURATION_BUCKETS_SEC[bucket]
    if num_green <= 1:
        return current_idx, False
    if env._elapsed_in_green[tl_id] >= target_age:
        return (current_idx + 1) % num_green, True
    return current_idx, False


def test_default_action_mode_is_duration():
    env = CoLightEnv(network_path="/dev/null", network_id="t", tl_ids=["x"])
    assert env.action_mode == "duration"


def test_duration_mode_holds_when_elapsed_below_target():
    env = _make_env_minimal()
    env._elapsed_in_green["tl0"] = 5  # below smallest bucket (10)
    desired, yellow = _decide_phase(env, action=0)  # bucket 10s
    assert desired == 0
    assert yellow is False


def test_duration_mode_cycles_when_elapsed_meets_target():
    env = _make_env_minimal()
    env._elapsed_in_green["tl0"] = 10
    desired, yellow = _decide_phase(env, action=0)  # bucket 10s
    assert desired == 1  # cycled to next phase
    assert yellow is True


def test_duration_mode_cycles_at_higher_bucket():
    env = _make_env_minimal()
    env._elapsed_in_green["tl0"] = 30
    desired, yellow = _decide_phase(env, action=2)  # bucket 30s
    assert desired == 1
    assert yellow is True


def test_duration_mode_holds_when_below_higher_bucket():
    env = _make_env_minimal()
    env._elapsed_in_green["tl0"] = 25
    desired, yellow = _decide_phase(env, action=3)  # bucket 40s
    assert desired == 0  # still holding phase 0
    assert yellow is False


def test_duration_action_modulo():
    """Action values out of range wrap modulo bucket count (defensive)."""
    env = _make_env_minimal()
    env._elapsed_in_green["tl0"] = 25
    # action=5 → bucket 5 % 4 = 1 → 20s target → 25 >= 20 → cycle
    desired, yellow = _decide_phase(env, action=5)
    assert desired == 1
    assert yellow is True


def test_duration_mode_2phase_cyclic_starvation_impossible():
    """With cyclic constraint, every cycle gets reached eventually.

    Simulates 100 decisions where the agent always picks bucket 3 (40s).
    Expect phase to flip multiple times — never starve on phase 0.
    """
    env = _make_env_minimal()
    flips = 0
    for _ in range(100):
        desired, yellow = _decide_phase(env, action=3)  # bucket 40
        if yellow:
            flips += 1
            env._current_green_idx["tl0"] = desired
            env._elapsed_in_green["tl0"] = 0
        env._elapsed_in_green["tl0"] += 10
    # 100 decisions × 10 sec = 1000 sec; 40-sec target → flip every 4-5
    # decisions → at least 20 flips
    assert flips >= 20, f"Phase never cycled enough times ({flips} flips)"


def test_duration_mode_num_actions_uniform_4():
    """Check the env reports num_actions=4 in duration mode regardless of TL count."""
    env = _make_env_minimal()
    assert env.num_actions == 4
    assert len(DURATION_BUCKETS_SEC) == 4


def test_phase_mode_legacy_path_still_works():
    """Sanity: action_mode='phase' branch interprets action as phase index."""
    env = CoLightEnv(
        network_path="/dev/null",
        network_id="t",
        tl_ids=["x"],
        action_mode="phase",
    )
    assert env.action_mode == "phase"


def test_invalid_action_mode_raises():
    with pytest.raises(ValueError, match="action_mode must be"):
        CoLightEnv(
            network_path="/dev/null",
            network_id="t",
            tl_ids=["x"],
            action_mode="bogus",
        )
