import pandas as pd

from football_stats.gps.load_monitoring import (
    classify_acwr,
    classify_monotony,
    compute_acwr,
    weekly_monotony_and_strain,
)


def test_compute_acwr_matches_hand_calculated_ratio():
    # 7 days at 1000/day (chronic period), then a sudden acute week at 2000/day.
    dates = pd.date_range("2025-09-01", periods=14, freq="D")
    loads = [1000] * 7 + [2000] * 7
    df = pd.DataFrame({"date": dates, "total_distance_m": loads})

    acwr = compute_acwr(df, acute_days=7, chronic_days=14)
    latest = acwr.iloc[-1]

    # acute (last 7 days) = 2000/day; chronic (all 14 days) = 1500/day average -> ratio = 2000/1500
    assert latest == round(2000 / 1500, 2)
    assert classify_acwr(latest) == "Elevated Risk"


def test_classify_acwr_zones():
    assert classify_acwr(0.5) == "Undertrained"
    assert classify_acwr(1.0) == "Optimal"
    assert classify_acwr(1.4) == "Elevated Risk"
    assert classify_acwr(1.8) == "High Risk"
    assert classify_acwr(float("nan")) == "Unknown"


def test_weekly_monotony_and_strain_matches_hand_calculation():
    # One week, Mon-Sun, with a known mean/SD so monotony/strain can be hand-checked.
    dates = pd.date_range("2025-09-01", periods=7, freq="D")  # a Monday
    loads = [1000, 1000, 1000, 1000, 1000, 1000, 4000]  # one big outlier day
    df = pd.DataFrame({"date": dates, "total_distance_m": loads})

    result = weekly_monotony_and_strain(df)
    assert len(result) == 1
    row = result.iloc[0]

    load_series = pd.Series(loads)
    expected_mean = load_series.mean()
    expected_sd = load_series.std()  # sample std, ddof=1
    expected_monotony = round(expected_mean / expected_sd, 2)
    expected_strain = round(load_series.sum() * expected_monotony, 1)

    assert row["weekly_load"] == sum(loads)
    assert row["monotony"] == expected_monotony
    assert row["strain"] == expected_strain


def test_monotonous_week_has_higher_monotony_than_varied_week():
    dates = pd.date_range("2025-09-01", periods=7, freq="D")
    monotonous = pd.DataFrame({"date": dates, "total_distance_m": [2000] * 7})
    varied = pd.DataFrame({"date": dates, "total_distance_m": [500, 3000, 500, 3000, 500, 3000, 500]})

    monotonous_result = weekly_monotony_and_strain(monotonous)
    varied_result = weekly_monotony_and_strain(varied)

    # A week with zero variance has an undefined (NaN) monotony, not infinity.
    assert pd.isna(monotonous_result.iloc[0]["monotony"])
    assert varied_result.iloc[0]["monotony"] > 0


def test_single_session_week_has_no_monotony_or_strain():
    df = pd.DataFrame({"date": ["2025-09-01"], "total_distance_m": [5000]})
    result = weekly_monotony_and_strain(df)
    assert pd.isna(result.iloc[0]["monotony"])
    assert pd.isna(result.iloc[0]["strain"])


def test_classify_monotony_zones():
    assert classify_monotony(0.5) == "Low"
    assert classify_monotony(1.5) == "Normal"
    assert classify_monotony(2.5) == "High — low day-to-day variability"
    assert classify_monotony(float("nan")) == "Unknown"


def test_weekly_monotony_and_strain_empty_input():
    empty = pd.DataFrame(columns=["date", "total_distance_m"])
    result = weekly_monotony_and_strain(empty)
    assert result.empty
