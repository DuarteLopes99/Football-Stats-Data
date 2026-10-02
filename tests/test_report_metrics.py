"""Cleaning, MD labelling, Gref and weekly change % — the report's calculations."""

import math

import pandas as pd
import pytest

from football_stats.gps import config as cfg
from football_stats.gps.reference import match_reference
from football_stats.gps.weekly_change import pct_change, weekly_change
from tests._gps_helpers import build, friendly, match, row_on, training, unused_sub

# A regular Sunday-to-Sunday season: matches on Sundays 5, 12, 19 Oct 2025,
# training Tue/Thu/Fri in between, a friendly on Thursday 16 Oct.
REGULAR = [
    training("2025-09-30"), training("2025-10-02"), training("2025-10-03"),
    match("2025-10-05", 9000),
    training("2025-10-06", 3000), training("2025-10-07", 6000), training("2025-10-09", 8000), training("2025-10-10", 5000),
    match("2025-10-12", 9900),
    training("2025-10-14", 6600), friendly("2025-10-16"), training("2025-10-17", 4000),
    match("2025-10-19", 8100),
]


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #


def test_unused_substitute_zeros_become_missing_not_zero():
    df = build([match("2025-10-05"), unused_sub("2025-10-12")], labelled=False)
    bench = row_on(df, "2025-10-12")
    assert bench["unused_sub"] and not bench["has_gps"]
    assert pd.isna(bench["total_distance_m"]) and pd.isna(bench["top_speed_kmh"]) and pd.isna(bench["duration_min"])
    # The played match is untouched.
    assert row_on(df, "2025-10-05")["total_distance_m"] == 9000


def test_session_without_gps_data_is_kept_but_flagged():
    df = build([training("2025-10-01"), {"date": "2025-10-02", "session_kind": "training", "duration_min": 80}], labelled=False)
    empty = row_on(df, "2025-10-02")
    assert len(df) == 2 and not empty["has_gps"]
    assert pd.isna(empty["hia"]) and pd.isna(empty["m_per_min"])


def test_friendly_with_duration_only_has_no_sprint_count():
    df = build([{"date": "2025-12-23", "session_kind": "game", "competition_type": "Treino", "duration_min": 45}], labelled=False)
    assert not df.iloc[0]["has_gps"] and pd.isna(df.iloc[0]["sprints_total"])


def test_derived_metrics_follow_statsports_bands():
    row = build([training("2025-10-01", 6000, duration_min=75)], labelled=False).iloc[0]
    assert row["hsr_sprint_m"] == 800          # HSD already includes sprinting
    assert row["hsr_m"] == 600                 # 19.8–25.2 band = HSD − sprint
    assert row["hia"] == 40 + 50 + 8           # acc + dec + sprints
    assert row["m_per_min"] == 80.0            # 6000 / 75


def test_short_appearance_flag_uses_match_sheet_minutes():
    df = build([match("2025-10-05", 2000, duration_min=20, minutes_game_zerozero=9)], labelled=False)
    assert df.iloc[0]["short_appearance"] and df.iloc[0]["minutes_played"] == 9


# --------------------------------------------------------------------------- #
# MD labels
# --------------------------------------------------------------------------- #


def test_regular_week_gets_ravé_labels():
    df = build(REGULAR)
    labels = {d: row_on(df, d)["md_label"] for d in ["2025-10-05", "2025-10-06", "2025-10-07", "2025-10-09", "2025-10-10"]}
    assert labels == {"2025-10-05": "MD", "2025-10-06": "MD+1", "2025-10-07": "MD+2", "2025-10-09": "MD-3", "2025-10-10": "MD-2"}


def test_friendly_does_not_anchor_a_microcycle():
    df = build(REGULAR)
    thursday_friendly = row_on(df, "2025-10-16", cfg.PRACTICE_MATCH)
    assert thursday_friendly["md_label"] == "MD-3"
    # Friday after the friendly still counts down to Sunday's official match.
    assert row_on(df, "2025-10-17")["md_label"] == "MD-2"
    assert thursday_friendly["microcycle_id"] == "MD 2025-10-12"


def test_microcycle_runs_from_md_to_md_minus_1():
    df = build(REGULAR)
    week = df[df["microcycle_id"] == "MD 2025-10-05"]
    assert week["date"].min() == pd.Timestamp("2025-10-05")
    assert week["microcycle_end"].iloc[0] == pd.Timestamp("2025-10-11")
    assert week["microcycle_days"].iloc[0] == 7 and not week["microcycle_extended"].iloc[0]


def test_preseason_and_lead_in():
    df = build([training("2025-09-01"), training("2025-09-30"), match("2025-10-05")])
    assert row_on(df, "2025-09-01")["md_label"] == cfg.PRESEASON_LABEL       # 34 days out
    assert row_on(df, "2025-09-30")["md_label"] == "MD-5"                    # within the lead-in window


def test_winter_break_is_an_extended_microcycle():
    df = build([match("2025-12-14"), training("2025-12-16"), training("2025-12-30"), match("2026-01-04")])
    assert row_on(df, "2025-12-16")["md_label"] == "MD+2"
    assert row_on(df, "2025-12-30")["md_label"] == "MD-5"
    assert row_on(df, "2025-12-30")["microcycle_extended"]


def test_labels_are_per_season_and_a_matchless_season_is_preseason():
    df = build([match("2026-05-10"), training("2026-05-12"), friendly("2026-09-05")])
    assert row_on(df, "2026-05-12")["md_label"] == "MD+2"
    assert row_on(df, "2026-09-05")["md_label"] == cfg.PRESEASON_LABEL      # not MD+118


def test_unused_sub_match_day_still_anchors():
    df = build([match("2025-10-05"), training("2025-10-09"), unused_sub("2025-10-12"), training("2025-10-14")])
    assert row_on(df, "2025-10-12")["md_label"] == "MD"
    assert row_on(df, "2025-10-14")["md_label"] == "MD+2"


# --------------------------------------------------------------------------- #
# Gref
# --------------------------------------------------------------------------- #


def test_gref_is_mean_of_best_five_official_matches():
    distances = [9000, 8000, 7000, 6000, 5000, 4000, 3000]
    rows = [match(f"2025-10-{5 + 7 * i:02d}", d) for i, d in enumerate(distances[:4])]
    rows += [match(f"2025-11-{2 + 7 * i:02d}", d) for i, d in enumerate(distances[4:])]
    rows += [friendly("2025-10-08", 20000), training("2025-10-09", 15000)]   # must not count
    ref = match_reference(build(rows), "2025/26")
    assert ref.get("total_distance_m") == pytest.approx((9000 + 8000 + 7000 + 6000 + 5000) / 5)
    assert ref.matches_used["total_distance_m"] == 5 and not ref.warning


def test_gref_with_fewer_than_five_matches_uses_all_and_warns():
    ref = match_reference(build([match("2025-10-05", 9000), match("2025-10-12", 7000), unused_sub("2025-10-19")]), "2025/26")
    assert ref.get("total_distance_m") == 8000          # the unused-sub zero is not a value
    assert ref.matches_used["total_distance_m"] == 2 and ref.warning
    assert "Only 2 eligible" in ref.describe()


def test_gref_rate_ignores_cameos():
    cameo = match("2025-10-19", 1000, duration_min=8, minutes_game_zerozero=6)   # 125 m/min
    ref = match_reference(build([match("2025-10-05", 9000), cameo]), "2025/26")
    assert ref.get("m_per_min") == 100.0                # 9000 / 90 only


def test_season_without_matches_borrows_previous_reference():
    ref = match_reference(build([match("2026-05-10", 9000), friendly("2026-09-05")]), "2026/27")
    assert ref.borrowed and ref.season == "2025/26" and ref.get("total_distance_m") == 9000


# --------------------------------------------------------------------------- #
# Weekly change %
# --------------------------------------------------------------------------- #


def test_pct_change_edges():
    assert pct_change(110, 100) == 10.0
    assert math.isnan(pct_change(100, 0)) and math.isnan(pct_change(None, 100)) and math.isnan(pct_change(100, float("nan")))


def test_same_md_label_previous_microcycle():
    wc = weekly_change(build(REGULAR), ["total_distance_m"])
    md_plus2 = row_on(wc, "2025-10-14")
    assert md_plus2["compare_date"] == pd.Timestamp("2025-10-07") and not md_plus2["fallback"]
    assert md_plus2["total_distance_m_pct"] == 10.0     # 6600 vs 6000
    second_match = row_on(wc, "2025-10-12")
    assert second_match["compare_date"] == pd.Timestamp("2025-10-05")
    assert second_match["total_distance_m_pct"] == 10.0  # 9900 vs 9000


def test_fallback_to_previous_session_of_same_type_is_marked():
    wc = weekly_change(build(REGULAR), ["total_distance_m"])
    # Previous microcycle had an MD-2 on 10 Oct → no fallback; the 2025-10-17 MD-2 compares with it.
    assert not row_on(wc, "2025-10-17")["fallback"]
    # MD+1 on 6 Oct: previous microcycle is pre-season → fallback to the previous training (3 Oct).
    md_plus1 = row_on(wc, "2025-10-06")
    assert md_plus1["fallback"] and md_plus1["compare_date"] == pd.Timestamp("2025-10-03")


def test_never_compares_across_session_types():
    wc = weekly_change(build(REGULAR), ["total_distance_m"])
    friendly_row = row_on(wc, "2025-10-16", cfg.PRACTICE_MATCH)
    # The only friendly: nothing of its type before it, so no comparison at all —
    # not the MD-3 training of the previous week.
    assert pd.isna(friendly_row["compare_date"]) and pd.isna(friendly_row["total_distance_m_pct"])


def test_gref_mode():
    df = build(REGULAR)
    ref = match_reference(df, "2025/26")
    wc = weekly_change(df, ["total_distance_m"], mode="gref", reference=ref)
    gref = ref.get("total_distance_m")  # (9000 + 9900 + 8100) / 3 = 9000
    assert gref == 9000
    assert row_on(wc, "2025-10-07")["total_distance_m_pct"] == pytest.approx(-33.3, abs=0.05)


def test_sessions_without_data_have_no_change():
    df = build([training("2025-10-01"), {"date": "2025-10-02", "session_kind": "training", "duration_min": 80}, training("2025-10-03", 6600)])
    wc = weekly_change(df, ["total_distance_m"])
    assert pd.isna(row_on(wc, "2025-10-02")["total_distance_m_pct"])
    # And the empty row is skipped as a baseline.
    assert row_on(wc, "2025-10-03")["compare_date"] == pd.Timestamp("2025-10-01")
