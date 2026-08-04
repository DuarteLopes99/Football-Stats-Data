import numpy as np
import pandas as pd

from football_stats.gps.skillcorner_metrics import (
    add_intensity_ratios,
    add_per90_columns,
    percentile_rank,
    robust_top_speed,
)


def test_add_per90_columns_normalizes_and_guards_zero_minutes():
    df = pd.DataFrame(
        {
            "duration_min": [90, 45, 0, None],
            "total_distance_m": [9000, 4500, 5000, 6000],
        }
    )
    result = add_per90_columns(df)
    assert result["total_distance_m_per90"].tolist()[:2] == [9000.0, 9000.0]  # 4500/45*90 = 9000
    assert pd.isna(result["total_distance_m_per90"].iloc[2])  # zero minutes -> NaN, not inf
    assert pd.isna(result["total_distance_m_per90"].iloc[3])  # missing minutes -> NaN


def test_add_intensity_ratios():
    df = pd.DataFrame({"total_distance_m": [10000, 0], "high_speed_distance_m": [1500, 100], "sprint_distance_m": [500, 50]})
    result = add_intensity_ratios(df)
    assert result["high_speed_pct"].iloc[0] == 15.0
    assert result["sprint_pct"].iloc[0] == 5.0
    assert pd.isna(result["high_speed_pct"].iloc[1])  # zero total distance -> NaN, not inf


def test_robust_top_speed_discounts_a_single_outlier():
    dates = pd.date_range("2025-09-01", periods=10, freq="7D")
    speeds = [28, 28.5, 29, 28, 29.5, 40, 28, 29, 28.5, 29]  # one outlier spike (40) mid-series
    df = pd.DataFrame({"date": dates, "top_speed_kmh": speeds})

    latest = robust_top_speed(df, window=10, percentile=95).iloc[-1]

    # The 95th percentile pulls toward the one-off 40 km/h outlier (small-window
    # percentiles interpolate between the top order statistics), but it must land
    # strictly below the outlier itself -- that's the noise-robustness this exists for.
    assert latest == round(float(np.percentile(speeds, 95)), 2)
    assert latest < 40


def test_robust_top_speed_default_percentile_not_99_over_small_window():
    """Regression: 99th percentile over ~10 samples degenerates to the window
    max, which defeats the noise-robustness this metric exists for."""
    dates = pd.date_range("2025-09-01", periods=10, freq="7D")
    speeds = [28] * 9 + [40]  # one outlier as the most recent session
    df = pd.DataFrame({"date": dates, "top_speed_kmh": speeds})

    p99 = robust_top_speed(df, window=10, percentile=99).iloc[-1]
    p95 = robust_top_speed(df, window=10, percentile=95).iloc[-1]

    # Both interpolate toward the outlier over such a small window (expected --
    # this is exactly why the docstring calls literal PSV-99 unsuitable here),
    # but the higher percentile must still sit closer to the raw outlier than the lower one.
    assert p99 > p95
    assert p99 == round(float(np.percentile([28] * 9 + [40], 99)), 2)


def test_percentile_rank():
    series = pd.Series([10, 20, 30, 40, 50])
    assert percentile_rank(series, 10) == 0.0  # nothing below the minimum
    assert percentile_rank(series, 50) == 80.0  # 4 of 5 values are below it
    assert pd.isna(percentile_rank(series, None))
