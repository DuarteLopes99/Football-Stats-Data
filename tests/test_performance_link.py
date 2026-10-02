"""Tests for the body-composition vs. running-output analysis."""

import numpy as np
import pandas as pd

from football_stats.body import performance_link as pl


def _assessments(dates, fat):
    return pd.DataFrame(
        {"date": pd.to_datetime(dates), "season": "2025/26", "phase": "1ª volta", "Massa Gorda": fat}
    )


def _sessions(dates, distance):
    return pd.DataFrame({"date": pd.to_datetime(dates), "total_distance_m": distance})


def test_only_training_before_an_assessment_is_paired_with_it():
    assessments = _assessments(["2026-01-15"], [12.0])
    sessions = _sessions(
        [
            "2026-01-10",  # inside the 28-day lookback
            "2026-01-14",  # inside
            "2026-01-20",  # AFTER the assessment: cannot explain a measurement already taken
            "2025-11-01",  # older than the lookback
        ],
        [8000.0, 6000.0, 12000.0, 9000.0],
    )
    result = pl.performance_per_assessment(sessions, assessments)

    assert result.loc[0, "sessions_in_window"] == 2
    assert result.loc[0, "total_distance_m"] == 7000.0  # mean of the two inside, not the later 12000


def test_windows_are_averaged_so_a_busy_block_is_not_automatically_higher():
    assessments = _assessments(["2026-01-15", "2026-03-15"], [12.0, 11.0])
    sessions = _sessions(
        ["2026-01-10", "2026-01-11", "2026-01-12", "2026-03-10"], [8000.0, 8000.0, 8000.0, 8000.0]
    )
    result = pl.performance_per_assessment(sessions, assessments)

    assert list(result["sessions_in_window"]) == [3, 1]
    assert list(result["total_distance_m"]) == [8000.0, 8000.0]


def test_underpowered_pairs_are_reported_but_labelled_not_suppressed():
    dates = pd.date_range("2026-01-01", periods=5, freq="30D")
    body = _assessments(dates, np.linspace(12.0, 10.0, 5))
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": np.linspace(5000, 9000, 5)}
    )
    result = pl.correlate_body_vs_performance(body, performance)

    # A perfect rank correlation over 5 points is unremarkable -- but withholding
    # it entirely left this dataset with a permanently blank tab. It is shown
    # with its sample size and a tier that says how much weight it can carry.
    assert not result.empty
    assert (result["n"] == 5).all()
    assert (result["reliability"] == "anecdotal").all()


def test_a_hard_floor_still_applies_below_which_rho_is_not_a_statistic():
    dates = pd.date_range("2026-01-01", periods=3, freq="30D")
    body = _assessments(dates, [12.0, 11.0, 10.0])
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": [5000.0, 7000.0, 9000.0]}
    )
    # With 3 points |rho| = 1.0 arises by chance often enough to be meaningless.
    assert pl.correlate_body_vs_performance(body, performance).empty


def test_raising_min_pairs_restores_the_strict_view():
    dates = pd.date_range("2026-01-01", periods=5, freq="30D")
    body = _assessments(dates, np.linspace(12.0, 10.0, 5))
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": np.linspace(5000, 9000, 5)}
    )
    assert pl.correlate_body_vs_performance(body, performance, min_pairs=pl.MIN_PAIRS).empty


def test_reliability_tier_tracks_sample_size():
    assert pl.reliability_tier(20) == "worth acting on"
    assert pl.reliability_tier(pl.MIN_PAIRS) == "worth acting on"
    assert pl.reliability_tier(6) == "indicative"
    assert pl.reliability_tier(pl.ABSOLUTE_MIN_PAIRS) == "anecdotal"
    assert pl.reliability_tier(2) == "not testable"


def test_correlation_reports_n_rho_and_an_fdr_corrected_q_value():
    dates = pd.date_range("2026-01-01", periods=12, freq="14D")
    body = _assessments(dates, np.linspace(14.0, 10.0, 12))
    performance = pd.DataFrame(
        {
            "date": dates,
            "sessions_in_window": 5,
            "total_distance_m": np.linspace(5000, 9000, 12),
            "top_speed_kmh": np.random.default_rng(0).normal(30, 1, 12),
        }
    )
    result = pl.correlate_body_vs_performance(body, performance)

    assert set(["body_metric", "performance_metric", "n", "rho", "p_value", "q_value", "survives_fdr"]).issubset(
        result.columns
    )
    assert (result["n"] == 12).all()
    # Perfectly anti-correlated by construction, and stronger than the random pair.
    top = result.iloc[0]
    assert top["performance_metric"] == "total_distance_m"
    assert top["rho"] == -1.0
    # A q-value is never smaller than its own p-value after correction.
    assert (result["q_value"] >= result["p_value"] - 1e-9).all()


def test_summary_says_no_relationship_rather_than_going_quiet():
    dates = pd.date_range("2026-01-01", periods=10, freq="14D")
    rng = np.random.default_rng(7)
    body = _assessments(dates, rng.normal(12, 0.5, 10))
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": rng.normal(7000, 500, 10)}
    )
    summary = pl.summarise_findings(pl.correlate_body_vs_performance(body, performance))

    assert summary["survivors"] == 0
    assert "chance" in summary["verdict"]
    # The denominator has to be visible for the claim to mean anything.
    assert str(summary["tested"]) in summary["detail"]
    # And at n=10 the power caveat has to travel with the null, or "we found
    # nothing" reads as "there is nothing".
    assert summary["underpowered"] is False


def test_summary_distinguishes_untestable_from_tested_and_null():
    assert "enough training" in pl.summarise_findings(pd.DataFrame())["verdict"]


def test_a_null_at_a_small_n_carries_its_power_caveat():
    dates = pd.date_range("2026-01-01", periods=6, freq="30D")
    rng = np.random.default_rng(3)
    body = _assessments(dates, rng.normal(12, 0.5, 6))
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": rng.normal(7000, 500, 6)}
    )
    summary = pl.summarise_findings(pl.correlate_body_vs_performance(body, performance))

    assert summary["underpowered"] is True
    assert summary["best_n"] == 6
    # A null this thin is weak evidence of absence, and has to say so.
    assert "weak evidence of absence" in summary["detail"]


def test_coverage_reports_the_overlap_that_limits_the_analysis():
    performance = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-06-01", "2026-01-01"]),
            "sessions_in_window": [0, 0, 5],
        }
    )
    result = pl.coverage(performance)

    assert result["assessments"] == 3
    assert result["paired"] == 1
    assert result["well_powered"] is False
    # One paired assessment is below even the hard floor, so nothing can run.
    assert result["analysable"] is False
    assert result["shortfall"] == pl.MIN_PAIRS - 1
    assert result["first_paired"] == pd.Timestamp("2026-01-01")


def test_paired_observations_are_available_even_when_untestable():
    dates = pd.to_datetime(["2026-01-01", "2026-02-01"])
    body = _assessments(dates, [12.0, 11.0])
    performance = pd.DataFrame({"date": dates, "sessions_in_window": [4, 4], "total_distance_m": [7000.0, 8000.0]})

    points = pl.paired_observations(body, performance, "Massa Gorda", "total_distance_m")
    assert len(points) == 2
    assert list(points.columns) == ["date", "phase", "sessions_in_window", "Massa Gorda", "total_distance_m"]


def test_phase_profile_orders_by_the_football_calendar():
    performance = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2025-09-01", "2025-08-01"]),
            "phase": ["2ª volta", "1ª volta", "pré-época"],
            "sessions_in_window": [5, 5, 5],
            "total_distance_m": [5000.0, 6000.0, 7000.0],
        }
    )
    # Not alphabetical -- "1ª volta" would otherwise sort before "pré-época".
    assert list(pl.phase_profile(performance)["phase"]) == ["pré-época", "1ª volta", "2ª volta"]


def test_a_perfect_rho_on_few_points_is_named_not_celebrated():
    """rho = -1.0 at n = 6 clears FDR because the p-value is computed as though
    the sample were adequate. Left unremarked it becomes the headline finding."""
    dates = pd.date_range("2026-01-01", periods=6, freq="21D")
    body = _assessments(dates, np.linspace(14.0, 10.0, 6))
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": np.linspace(5000, 9000, 6)}
    )
    correlations = pl.correlate_body_vs_performance(body, performance)
    summary = pl.summarise_findings(correlations)

    assert summary["survivors"] >= 1
    assert summary["suspect_survivors"] >= 1
    assert summary["underpowered"] is True
    assert "too few points" in summary["detail"]


def test_a_well_powered_survivor_carries_no_suspect_flag():
    """The caveat has to be conditional, or it is noise that gets ignored."""
    dates = pd.date_range("2024-01-01", periods=20, freq="21D")
    rng = np.random.default_rng(11)
    fat = np.linspace(14.0, 10.0, 20) + rng.normal(0, 0.3, 20)
    body = _assessments(dates, fat)
    performance = pd.DataFrame(
        {"date": dates, "sessions_in_window": 5, "total_distance_m": -fat * 500 + rng.normal(0, 100, 20)}
    )
    summary = pl.summarise_findings(pl.correlate_body_vs_performance(body, performance))

    assert summary["underpowered"] is False
    assert summary["suspect_survivors"] == 0
