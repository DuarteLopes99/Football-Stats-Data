"""Tests for fatigue, mechanical-load and speed-exposure metrics."""

import pandas as pd

from football_stats.gps import fatigue as ft


def _match(date, first, second, minutes, category="official_match", starter=True, **extra):
    row = {
        "date": pd.Timestamp(date),
        "session_type": "match",
        "match_category": category,
        "was_starter": starter,
        "sprints_1st_half": first,
        "sprints_2nd_half": second,
        "minutes_game_zerozero": minutes,
        "duration_min": minutes,
        "top_speed_kmh": 30.0,
        "total_distance_m": 8000.0,
        "high_speed_distance_m": 1000.0,
        "sprint_distance_m": 300.0,
    }
    row.update(extra)
    return row


def test_half_time_substitution_is_not_counted_as_a_collapse():
    sessions = pd.DataFrame(
        [
            # Played the full match and faded: a real retention observation.
            _match("2026-02-22", 20, 11, minutes=89),
            # 25 sprints then zero -- but only 45 minutes, i.e. subbed at half time.
            _match("2026-01-17", 25, 0, minutes=45),
        ]
    )
    result = ft.second_half_retention(sessions)

    assert len(result) == 1
    assert result.loc[0, "date"] == pd.Timestamp("2026-02-22")
    # Including the 45-minute appearance would drag the median from 0.55 to ~0.28.
    assert result["second_half_retention"].median() == 0.55


def test_gps_runtime_is_used_only_when_the_match_sheet_is_missing():
    sessions = pd.DataFrame(
        [
            # Unit ran 56 min through the warm-down but the player only played 45.
            _match("2025-10-12", 18, 2, minutes=45, duration_min=56.0),
            _match("2025-09-06", 13, 10, minutes=None, duration_min=79.0),
        ]
    )
    result = ft.second_half_retention(sessions)

    # The 45-minute appearance is excluded despite a 56-minute recording.
    assert list(result["date"]) == [pd.Timestamp("2025-09-06")]
    assert result.loc[0, "minutes_played"] == 79.0


def test_zero_first_half_never_divides_by_zero():
    sessions = pd.DataFrame([_match("2026-03-01", 0, 4, minutes=60)])
    assert ft.second_half_retention(sessions).empty


def test_retention_summary_splits_official_from_practice():
    sessions = pd.DataFrame(
        [
            _match("2026-02-22", 20, 10, minutes=89),
            _match("2026-03-01", 10, 5, minutes=65),
            _match("2025-09-13", 12, 14, minutes=134, category="practice_match"),
        ]
    )
    summary = ft.second_half_retention(sessions).pipe(ft.retention_summary).set_index("match_category")

    assert summary.loc["official_match", "matches"] == 2
    assert summary.loc["official_match", "median_retention"] == 0.5
    assert summary.loc["practice_match", "median_retention"] == 1.17


def test_mechanical_load_is_independent_of_distance():
    sessions = pd.DataFrame(
        [
            # Same distance and duration, very different number of speed changes.
            {"date": pd.Timestamp("2026-01-01"), "total_distance_m": 8000.0, "duration_min": 90.0,
             "accelerations": 60.0, "decelerations": 60.0},
            {"date": pd.Timestamp("2026-01-08"), "total_distance_m": 8000.0, "duration_min": 90.0,
             "accelerations": 20.0, "decelerations": 40.0},
        ]
    )
    result = ft.add_mechanical_load(sessions)

    assert result.loc[0, "mechanical_load"] == 120.0
    assert result.loc[1, "mechanical_load"] == 60.0
    assert result.loc[0, "accel_decel_ratio"] == 1.0
    assert result.loc[1, "accel_decel_ratio"] == 0.5


def test_mechanical_load_is_missing_not_zero_when_both_counts_are_absent():
    sessions = pd.DataFrame(
        [{"date": pd.Timestamp("2026-05-12"), "total_distance_m": None, "duration_min": None,
          "accelerations": None, "decelerations": None}]
    )
    assert pd.isna(ft.add_mechanical_load(sessions).loc[0, "mechanical_load"])


def test_accel_decel_classification_band():
    assert ft.classify_accel_decel_ratio(0.6) == "Deceleration-dominant"
    assert ft.classify_accel_decel_ratio(1.0) == "Balanced"
    assert ft.classify_accel_decel_ratio(1.5) == "Acceleration-dominant"
    assert ft.classify_accel_decel_ratio(float("nan")) == "Unknown"


def test_high_speed_exposure_reports_a_share_not_a_count():
    sessions = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-12", "2026-01-19", "2026-02-02"]),
            # Reference is the 30.0 max; 90% of that is 27.0.
            "top_speed_kmh": [30.0, 24.0, 24.0, 28.0],
        }
    )
    result = ft.high_speed_exposure(sessions).set_index("month_label")

    # A month with more sessions shouldn't look better just for being busier.
    assert result.loc["2026-01", "sessions"] == 3
    assert result.loc["2026-01", "near_max_sessions"] == 1
    assert result.loc["2026-01", "near_max_pct"] == round(1 / 3 * 100, 1)
    assert result.loc["2026-02", "near_max_pct"] == 100.0


def test_intensity_gap_needs_both_a_match_and_a_training_that_month():
    sessions = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-01-05"), "match_category": "training",
             "total_distance_m": 8000.0, "high_speed_distance_m": 800.0, "sprint_distance_m": 200.0},
            {"date": pd.Timestamp("2026-01-12"), "match_category": "official_match",
             "total_distance_m": 8000.0, "high_speed_distance_m": 1600.0, "sprint_distance_m": 400.0},
            # February has training but no official match: nothing to compare against.
            {"date": pd.Timestamp("2026-02-05"), "match_category": "training",
             "total_distance_m": 8000.0, "high_speed_distance_m": 800.0, "sprint_distance_m": 200.0},
        ]
    )
    result = ft.training_match_intensity_gap(sessions)

    assert list(result["month_label"]) == ["2026-01"]
    # Training reached half the match's high-speed share.
    assert result.loc[0, "high_speed_gap_pct"] == 50.0
    assert result.loc[0, "sprint_gap_pct"] == 50.0
