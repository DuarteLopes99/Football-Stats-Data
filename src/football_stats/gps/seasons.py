"""Football-season boundary helpers for GPS data.

A season runs July 1 - June 30, crossing a calendar-year boundary, so grouping
or sorting GPS sessions by raw month number (1-12) sorts wrong (January renders
before September) and, once more than one season of data exists, would merge
distinct seasons' same-numbered months together. Every session gets a `season`
label derived from its date so analysis can be scoped to one season or compared
across seasons explicitly, instead of silently mixing them.
"""

from __future__ import annotations

import pandas as pd

SEASON_START_MONTH = 7
"""Month a new season starts on (July) — Jul-Dec belongs to the season starting
that calendar year, Jan-Jun belongs to the season that started the previous year."""


def season_label(date) -> str:
    """"2025/26" for any date between Jul 2025 and Jun 2026."""
    ts = pd.Timestamp(date)
    start_year = ts.year if ts.month >= SEASON_START_MONTH else ts.year - 1
    return f"{start_year}/{str(start_year + 1)[-2:]}"


def add_season_column(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    df = df.copy()
    df["season"] = df[date_col].apply(season_label)
    return df
