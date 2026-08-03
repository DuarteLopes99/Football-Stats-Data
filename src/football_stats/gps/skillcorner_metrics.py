"""GPS metrics inspired by SkillCorner's physical-data methodology, adapted to a
single-player, session-aggregated dataset (we have no raw point-level tracking
data, only per-session totals/maxes already computed by the source device).

What's genuinely SkillCorner-sourced vs. adapted vs. general sports science is
spelled out in ``docs/skillcorner_metrics.md`` — the short version:

- **Per-90 normalization** and **percentile-based comparison** are directly
  borrowed from SkillCorner's open-source `skillcornerviz` toolkit
  (`skillcorner_physical_utils.py`'s `add_standard_metrics()`, and the
  percentile-colored tables in `summary_table.py`/`table_grid.py`) — same idea,
  applied against the player's own history instead of a peer group.
- **``robust_top_speed``** is inspired by SkillCorner's PSV-99 (99th-percentile
  of in-match speed *samples*, designed to be noise-robust) but is NOT that
  metric: we only have session-level maxes, so this is a rolling percentile
  over recent *sessions*, not raw samples. Deliberately non-99th-percentile —
  see the function docstring.
- **``compute_acwr``** (Acute:Chronic Workload Ratio) is general sports science
  (Gabbett, 2016), not a SkillCorner metric — included because it's the
  standard injury-risk indicator this kind of data is built for.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PER90_METRICS = [
    "total_distance_m",
    "sprint_distance_m",
    "high_speed_distance_m",
    "accelerations",
    "decelerations",
    "sprints_total",
    "calories",
]

ACWR_ZONES = [
    (0.0, 0.8, "Undertrained"),
    (0.8, 1.3, "Optimal"),
    (1.3, 1.5, "Elevated Risk"),
    (1.5, float("inf"), "High Risk"),
]


def add_per90_columns(df: pd.DataFrame, minutes_col: str = "duration_min") -> pd.DataFrame:
    """Add ``{metric}_per90`` columns, normalizing by minutes played.

    A 120-minute training session and a 79-minute match aren't comparable on
    raw totals — same idea as skillcornerviz's ``add_standard_metrics()``.
    Sessions with zero/missing minutes get NaN (not inf) for every per-90 column.
    """
    df = df.copy()
    minutes = pd.to_numeric(df[minutes_col], errors="coerce")
    safe_minutes = minutes.where(minutes > 0)
    for metric in PER90_METRICS:
        if metric in df.columns:
            values = pd.to_numeric(df[metric], errors="coerce")
            df[f"{metric}_per90"] = (values / safe_minutes * 90).round(2)
    return df


def add_intensity_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``high_speed_pct`` / ``sprint_pct``: share of total distance covered
    at high speed / sprinting — an intensity *profile* independent of session
    volume (a 60-min and a 120-min session can have the same intensity mix).
    """
    df = df.copy()
    total = pd.to_numeric(df["total_distance_m"], errors="coerce")
    safe_total = total.where(total > 0)
    df["high_speed_pct"] = (pd.to_numeric(df["high_speed_distance_m"], errors="coerce") / safe_total * 100).round(2)
    df["sprint_pct"] = (pd.to_numeric(df["sprint_distance_m"], errors="coerce") / safe_total * 100).round(2)
    return df


def robust_top_speed(df: pd.DataFrame, window: int = 10, percentile: int = 95, speed_col: str = "top_speed_kmh") -> pd.Series:
    """Rolling percentile of recent sessions' top speed — a session-level
    adaptation of SkillCorner's PSV-99, not the metric itself.

    Real PSV-99 is the 99th percentile over thousands of raw in-match speed
    *samples*, which makes a single glitchy sample harmless. We only have one
    already-aggregated max speed per *session* — over a ~10-session window, the
    99th percentile degenerates to "the max of the window" (defeats the point).
    The 95th percentile still meaningfully discounts one outlier session while
    keeping the window's information content.

    Returns a Series aligned to ``df``'s index (chronologically ordered
    internally, then reindexed back) — ``.iloc[-1]`` after sorting by date is
    the current "robust top speed."
    """
    ordered = df.sort_values("date")
    speeds = pd.to_numeric(ordered[speed_col], errors="coerce")

    def _pct(window_values: pd.Series) -> float:
        clean = window_values.dropna()
        return float(np.percentile(clean, percentile)) if len(clean) else np.nan

    rolling = speeds.rolling(window=window, min_periods=1).apply(_pct, raw=False).round(2)
    return rolling.reindex(df.index)


def percentile_rank(series: pd.Series, value: float) -> float:
    """Where ``value`` ranks (0-100) within ``series``'s empirical distribution.

    Used to answer "how does this session/week compare to my own season?" —
    the single-player equivalent of SkillCorner's peer-percentile tables.
    """
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    return round(float((clean < value).mean()) * 100, 1)


def classify_acwr(value: float) -> str:
    """Gabbett (2016) Acute:Chronic Workload Ratio risk zone for one ratio value."""
    if pd.isna(value):
        return "Unknown"
    for low, high, label in ACWR_ZONES:
        if low <= value < high:
            return label
    return "High Risk"


def compute_acwr(df: pd.DataFrame, load_col: str = "total_distance_m", acute_days: int = 7, chronic_days: int = 28) -> pd.Series:
    """Daily Acute:Chronic Workload Ratio: rolling `acute_days`-sum ÷ rolling
    `chronic_days`-average (scaled to the same `acute_days` window so the ratio
    is unitless). General sports-science injury-risk indicator (Gabbett, 2016)
    — not a SkillCorner metric.

    Sessions are resampled to a daily sum first (days with no session = 0
    load), since ``load_col`` is per-session, not per-day.
    """
    dates = pd.to_datetime(df["date"])
    load = pd.to_numeric(df[load_col], errors="coerce").fillna(0)
    daily = pd.Series(load.to_numpy(), index=dates).sort_index()
    daily = daily.groupby(daily.index).sum().resample("D").sum()

    acute = daily.rolling(acute_days, min_periods=1).sum()
    chronic = daily.rolling(chronic_days, min_periods=1).mean() * acute_days
    return (acute / chronic.replace(0, np.nan)).round(2)
