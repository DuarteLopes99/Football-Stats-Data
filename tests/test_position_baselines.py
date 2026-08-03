import pytest

from football_stats.gps.position_baselines import (
    BASELINE_METRICS_KEYS,
    OFFICIAL_MATCH_BASELINES,
    POSITIONS,
    TRAINING_RATIO,
    get_baseline,
    training_baseline,
)


def test_every_position_has_every_metric():
    for position in POSITIONS:
        assert set(OFFICIAL_MATCH_BASELINES[position]) == BASELINE_METRICS_KEYS


def test_training_baseline_is_lower_intensity_than_match():
    for position in POSITIONS:
        match = OFFICIAL_MATCH_BASELINES[position]
        training = training_baseline(position)
        for metric in ("total_distance_m", "high_speed_distance_m", "sprint_distance_m"):
            assert training[metric] < match[metric], f"{position}/{metric} should be lower for training"


def test_training_baseline_matches_documented_ratio():
    training = training_baseline("forward")
    match = OFFICIAL_MATCH_BASELINES["forward"]
    for metric, ratio in TRAINING_RATIO.items():
        assert training[metric] == round(match[metric] * ratio, 1)


def test_get_baseline_practice_match_falls_back_to_official():
    assert get_baseline("practice_match", "wide_midfielder") == get_baseline("official_match", "wide_midfielder")


def test_get_baseline_unknown_position_raises():
    with pytest.raises(ValueError):
        get_baseline("official_match", "sweeper")


def test_wide_players_have_higher_sprint_baseline_than_central_defenders():
    # Well-established finding across the cited literature: wide players
    # (fullbacks/wingers) cover more sprint distance than central defenders.
    assert OFFICIAL_MATCH_BASELINES["wide_midfielder"]["sprint_distance_m"] > OFFICIAL_MATCH_BASELINES["center_back"]["sprint_distance_m"]
    assert OFFICIAL_MATCH_BASELINES["full_back"]["sprint_distance_m"] > OFFICIAL_MATCH_BASELINES["center_back"]["sprint_distance_m"]


def test_goalkeeper_baseline_is_far_lower_than_outfield():
    gk = OFFICIAL_MATCH_BASELINES["goalkeeper"]
    outfield_min = min(OFFICIAL_MATCH_BASELINES[p]["total_distance_m"] for p in POSITIONS if p != "goalkeeper")
    assert gk["total_distance_m"] < outfield_min / 2
