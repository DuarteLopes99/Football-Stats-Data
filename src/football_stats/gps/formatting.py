"""Display-only formatting for GPS tables: raw snake_case schema columns (and the
aggregate columns analyzer methods produce from them) get Title Case, human
labels before ever reaching ``st.dataframe``. Never applied to data used for
computation — only to a copy right before rendering.
"""

from __future__ import annotations

import pandas as pd

DISPLAY_LABELS: dict[str, str] = {
    "date": "Date",
    "season": "Season",
    "session_kind": "Session Kind",
    "match_category": "Match Category",
    "week": "Week",
    "month": "Month",
    "month_label": "Month",
    "session_type": "Session Type",
    "competition_type": "Competition Type",
    "was_starter": "Started Match",
    "duration_min": "Duration (min)",
    "minutes_game_zerozero": "Minutes Played",
    "total_distance_m": "Total Distance (m)",
    "sprint_distance_m": "Sprint Distance (m)",
    "high_speed_distance_m": "High-Speed Distance (m)",
    "distance_per_min": "Distance per Minute (m/min)",
    "top_speed_kmh": "Top Speed (km/h)",
    "sprints_1st_half": "Sprints — 1st Half",
    "sprints_2nd_half": "Sprints — 2nd Half",
    "sprints_total": "Sprints (#)",
    "accelerations": "Accelerations (#)",
    "decelerations": "Decelerations (#)",
    "calories": "Calories",
    "notes": "Notes",
    # Fixture-link columns (gps/match_link.py)
    "fixture_date": "Fixture Date",
    "fixture_match": "Fixture Link",
    "days_from_fixture": "Days from Fixture",
    "competition": "Competition",
    "matchweek": "Matchweek",
    "venue": "Venue",
    "opponent": "Opponent",
    "goals_for": "Goals For",
    "goals_against": "Goals Against",
    "scoreline": "Score",
    "team_result": "Team Result",
    "official_minutes": "Official Minutes",
    "minutes_source": "Minutes Source",
    "short_appearance": "Rate Extrapolated",
    "goals_for": "Goals For",
    "goals_against": "Goals Against",
    "minutes_delta": "GPS − Match Sheet (min)",
    "flag": "Flag",
    "n": "Matches",
    "sessions": "Sessions",
    "mean_minutes": "Avg Minutes",
    # Body-composition link columns (body/gps_link.py)
    "assessment_date": "Assessment Date",
    "days_since_assessment": "Days Since Assessment",
    "window_start": "From",
    "window_end": "To",
    "days": "Days",
    "sessions_per_week": "Sessions / Week",
    "km_per_week": "km / Week",
    "football_kcal_per_day": "Football kcal / Day",
    "total_calories": "Total Calories",
    "total_duration_min": "Total Duration (min)",
    "plausible_range": "Plausible Range",
    "source_file": "Source Report",
}

MATCH_CATEGORY_LABELS: dict[str, str] = {
    "training": "Training",
    "official_match": "Official Match",
    "practice_match": "Practice Match",
}

_AGG_SUFFIX_LABELS = {"mean": "Avg", "sum": "Total", "max": "Max", "count": "#"}
_WEEKLY_CATEGORY_LABELS = {**MATCH_CATEGORY_LABELS, "total": "Overall"}
_WEEKLY_METRICS = ["duration_min", "total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]


def _humanize_one(col: str) -> str:
    if col in DISPLAY_LABELS:
        return DISPLAY_LABELS[col]
    if col in MATCH_CATEGORY_LABELS:
        return MATCH_CATEGORY_LABELS[col]
    if col == "duration_min_count":
        return "Sessions"
    if col.endswith("_per90_official"):
        base = col[: -len("_per90_official")]
        if base in DISPLAY_LABELS:
            return f"{DISPLAY_LABELS[base]} per 90 (match sheet)"
    if col.endswith("_per90"):
        base = col[: -len("_per90")]
        if base in DISPLAY_LABELS:
            return f"{DISPLAY_LABELS[base]} per 90"

    for suffix, suffix_label in _AGG_SUFFIX_LABELS.items():
        marker = f"_{suffix}"
        if col.endswith(marker):
            base = col[: -len(marker)]
            if base in DISPLAY_LABELS:
                base_label = DISPLAY_LABELS[base]
                return base_label if suffix == "sum" else f"{suffix_label} {base_label}"

    for category, category_label in _WEEKLY_CATEGORY_LABELS.items():
        for metric in _WEEKLY_METRICS:
            if col == f"{category}_{metric}":
                return f"{category_label} – {DISPLAY_LABELS[metric]}"

    if "_" not in col and col != col.lower():
        # Already a human label -- body-composition metric names arrive as
        # "Massa Isenta de Gordura (Δ)", which Title Case would mangle into
        # "Massa Isenta De Gordura".
        return col

    return col.replace("_", " ").title()


def humanize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with display-friendly Title Case column names."""
    return df.rename(columns={col: _humanize_one(col) for col in df.columns})


def numeric_column_config(df: pd.DataFrame, decimals: int = 1) -> dict:
    """Build a per-float-column ``st.column_config.NumberColumn`` format spec,
    so tables render fixed, short decimal places instead of long raw floats.
    """
    import streamlit as st

    fmt = f"%.{decimals}f"
    return {col: st.column_config.NumberColumn(format=fmt) for col in df.columns if pd.api.types.is_float_dtype(df[col])}
