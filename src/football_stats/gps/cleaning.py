"""Turn the session log into an analysis-ready frame: typed, flagged, derived.

The CSV is never modified. Everything here happens on a copy, and every row is
kept: a session that has no usable numbers is *flagged*, not dropped, because it
still happened (it still sits in a microcycle, and a match where you were an
unused substitute is still a match day).

Three kinds of row would otherwise poison the averages:

- **No GPS data** — a training or friendly whose metrics were never recorded.
  Its metrics are missing, not zero.
- **Unused substitute** — an official match with 0 minutes, exported as a row of
  zeros. Those zeros are "did not play", not measurements, so they become
  missing too. (Three matches this season; read naively they put the average
  match at 34.6 minutes.)
- **Short appearance** — a match under ``SHORT_APPEARANCE_MIN`` official minutes.
  Kept and measured, but flagged: per-minute rates from a cameo are
  extrapolation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from football_stats.gps import config as cfg
from football_stats.gps.seasons import add_season_column

_NUMERIC = [
    "duration_min", "minutes_game_zerozero", "total_distance_m", "sprint_distance_m",
    "high_speed_distance_m", "distance_per_min", "top_speed_kmh", "sprints_1st_half",
    "sprints_2nd_half", "sprints_total", "accelerations", "decelerations", "calories",
]
_MEASURED = list(cfg.CORE_GPS_COLUMNS) + ["sprints_total", "sprints_1st_half", "sprints_2nd_half", "calories", "distance_per_min"]


def match_category(df: pd.DataFrame) -> pd.Series:
    """training / official_match / practice_match for every row."""
    kind = df["session_kind"]
    competition = df.get("competition_type", pd.Series(index=df.index, dtype=object))
    return pd.Series(
        np.select(
            [kind == "training", competition.isin(cfg.OFFICIAL_COMPETITION_TYPES)],
            [cfg.TRAINING, cfg.OFFICIAL_MATCH],
            default=cfg.PRACTICE_MATCH,
        ),
        index=df.index,
    )


def prepare_sessions(raw: pd.DataFrame) -> pd.DataFrame:
    """Typed, flagged and derived copy of the session log.

    Adds: ``match_category``, ``season``, ``has_gps``, ``unused_sub``,
    ``minutes_played``, ``short_appearance`` and the derived metrics
    ``hsr_sprint_m``, ``hsr_m``, ``hia`` and ``m_per_min``.
    """
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for column in _NUMERIC:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = np.nan

    df["match_category"] = match_category(df)
    df = add_season_column(df)

    core = df[list(cfg.CORE_GPS_COLUMNS)]
    duration = df["duration_min"]
    sheet = df["minutes_game_zerozero"]

    # A game with no time on the pitch by either clock, and nothing recorded
    # beyond zeros: the unused substitute.
    zero_everything = core.fillna(0).eq(0).all(axis=1)
    df["unused_sub"] = (df["session_kind"] == "game") & (duration.fillna(0) == 0) & (sheet.fillna(0) == 0) & zero_everything
    # Duration too: "0 minutes" is a fact about the match sheet (kept in
    # minutes_game_zerozero), but as a GPS duration it drags every average down.
    df.loc[df["unused_sub"], _MEASURED + ["duration_min"]] = np.nan
    duration = df["duration_min"]

    df["has_gps"] = df[list(cfg.CORE_GPS_COLUMNS)].notna().any(axis=1) & ~df["unused_sub"]
    # Duration-only rows (a friendly with a logged length but no GPS file) keep
    # their minutes but measure nothing else.
    df.loc[~df["has_gps"], _MEASURED] = np.nan

    # A 0 km/h top speed on a session with recorded distance is a dropout, not a stroll.
    df.loc[df["top_speed_kmh"] == 0, "top_speed_kmh"] = np.nan

    is_game = df["session_kind"] == "game"
    df["minutes_played"] = np.where(
        is_game, sheet.where(sheet > 0, duration.where(duration > 0)), duration.where(duration > 0)
    )
    df["short_appearance"] = is_game & df["has_gps"] & (df["minutes_played"] < cfg.SHORT_APPEARANCE_MIN)

    # Derived metrics (see gps.config for the STATSports band definitions).
    if cfg.HSR_INCLUDES_SPRINT:
        df["hsr_sprint_m"] = df["high_speed_distance_m"]
        df["hsr_m"] = (df["high_speed_distance_m"] - df["sprint_distance_m"]).clip(lower=0)
    else:
        df["hsr_sprint_m"] = df["high_speed_distance_m"] + df["sprint_distance_m"]
        df["hsr_m"] = df["high_speed_distance_m"]
    df["hia"] = df[list(cfg.HIA_COMPONENTS)].sum(axis=1, min_count=len(cfg.HIA_COMPONENTS))
    # Recomputed rather than read from the export's own column, which disagrees
    # with distance ÷ duration by up to 17 m/min on five rows.
    df["m_per_min"] = (df["total_distance_m"] / duration.where(duration > 0)).round(1)

    return df.sort_values(["date", "match_category"]).reset_index(drop=True)


def measured(df: pd.DataFrame) -> pd.DataFrame:
    """Only the rows that carry GPS numbers."""
    return df[df["has_gps"]]


def filter_scope(
    df: pd.DataFrame,
    season: str | None = None,
    start=None,
    end=None,
    categories: list[str] | None = None,
) -> pd.DataFrame:
    """The report's global filters, applied in one place."""
    out = df
    if season is not None:
        out = out[out["season"] == season]
    if start is not None:
        out = out[out["date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["date"] <= pd.Timestamp(end)]
    if categories is not None:
        out = out[out["match_category"].isin(categories)]
    return out
