import pandas as pd

from football_stats.gps.load_monitoring import (
    classify_acwr,
    classify_monotony,
    compute_acwr,
    weekly_monotony_and_strain,
)


def test_compute_acwr_matches_hand_calculated_ratio():
    # 14 days at 1000/day (chronic period), then a sudden acute week at 2000/day.
    dates = pd.date_range("2025-09-01", periods=21, freq="D")
    loads = [1000] * 14 + [2000] * 7
    df = pd.DataFrame({"date": dates, "total_distance_m": loads})

    acwr = compute_acwr(df, acute_days=7, chronic_days=14)

    # Uncoupled: acute (last 7 days) = 14000; chronic = the 14 days *before*
    # them, averaged per 7-day block = 7000 -> ratio 2.0.
    assert acwr.iloc[-1] == 2.0
    assert classify_acwr(acwr.iloc[-1]) == "Above range"


def test_compute_acwr_needs_full_history():
    dates = pd.date_range("2025-09-01", periods=20, freq="D")
    df = pd.DataFrame({"date": dates, "total_distance_m": [1000] * 20})
    # 7 acute + 14 chronic days are needed; 20 days is one short.
    assert compute_acwr(df, acute_days=7, chronic_days=14).isna().all()


def test_classify_acwr_zones():
    assert classify_acwr(0.5) == "Below range"
    assert classify_acwr(0.8) == "Within range"
    assert classify_acwr(1.4) == "Within range"
    assert classify_acwr(1.5) == "Above range"
    assert classify_acwr(float("nan")) == "Insufficient history"


def test_weekly_monotony_and_strain_matches_hand_calculation():
    # One week, Sun-Sat (gps.config.WEEK_FREQ), with a known mean/SD so monotony/strain can be hand-checked.
    dates = pd.date_range("2025-08-31", periods=7, freq="D")  # a Sunday
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
    dates = pd.date_range("2025-08-31", periods=7, freq="D")
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


# --------------------------------------------------------------------------- #
# Weekly load and weekly ACWR (the report's section 2)
# --------------------------------------------------------------------------- #

from football_stats.gps.load_monitoring import weekly_acwr, weekly_load  # noqa: E402
from tests._gps_helpers import build, friendly, match, training  # noqa: E402


def _weeks(loads, start="2025-08-31"):
    """One training session on the Saturday of each Sunday-start week, so every
    week — including the last — is fully covered by the data."""
    sundays = pd.date_range(start, periods=len(loads), freq="7D")
    return build([training(str((d + pd.Timedelta(days=6)).date()), load) for d, load in zip(sundays, loads)])


def test_weekly_load_sums_every_session_type_and_keeps_empty_weeks():
    df = build([training("2025-09-02", 5000), match("2025-09-07", 9000), friendly("2025-09-11", 7000), training("2025-09-23", 4000)])
    weekly = weekly_load(df)
    assert list(weekly["week_start"].dt.strftime("%m-%d")) == ["08-31", "09-07", "09-14", "09-21"]
    assert list(weekly["load"]) == [5000, 16000, 0, 4000]          # Sun-Sat weeks; the gap week is a real zero
    assert weekly.loc[1, "load_official_match"] == 9000 and weekly.loc[1, "load_practice_match"] == 7000
    assert weekly.loc[1, "wow_pct"] == 220.0 and weekly.loc[1, "spike"]


def test_acwr_needs_four_full_weeks():
    weekly = weekly_acwr(_weeks([1000, 1000, 1000]))
    assert weekly["acwr"].isna().all() and set(weekly["acwr_zone"]) == {"Insufficient history"}


def test_rolling_acwr_hand_calculation():
    weekly = weekly_acwr(_weeks([1000, 2000, 3000, 2000, 4000]), method="rolling")
    # Week 5: acute 4000 / mean(1000, 2000, 3000, 2000) = 2000 -> 2.0, uncoupled.
    assert weekly["acwr"].iloc[-1] == 2.0 and weekly["acwr_zone"].iloc[-1] == "Above range"


def test_partial_final_week_is_not_rated():
    # Five full weeks, then data stopping on the Sunday of week six.
    df = _weeks([1000, 1000, 1000, 1000, 1000])
    df = build([training(str(d.date()), 1000) for d in df["date"]] + [training("2025-10-05", 300)])
    weekly = weekly_acwr(df)
    assert weekly["partial"].iloc[-1] and pd.isna(weekly["acwr"].iloc[-1])
    assert weekly["acwr_zone"].iloc[-1] == "Partial week" and pd.isna(weekly["wow_pct"].iloc[-1])
    assert weekly["acwr"].iloc[-2] == 1.0


def test_ewma_acwr_runs_and_respects_history():
    weekly = weekly_acwr(_weeks([1000] * 8), method="ewma")
    assert weekly["acwr"].iloc[:4].isna().all() and weekly["acwr"].iloc[4:].notna().all()


def test_week_with_missing_gps_is_flagged_incomplete():
    df = build([training("2025-09-02", 5000), {"date": "2025-09-04", "session_kind": "training", "duration_min": 80}])
    weekly = weekly_load(df)
    assert weekly.loc[0, "incomplete"] and weekly.loc[0, "missing_sessions"] == 1 and weekly.loc[0, "load"] == 5000


def test_double_match_week_sums_both_matches():
    df = build([match("2025-09-07", 9000), match("2025-09-10", 8000, competition="Taça"), match("2025-09-13", 7000)])
    assert weekly_load(df).loc[0, "load_official_match"] == 24000
