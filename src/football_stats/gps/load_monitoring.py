"""Training-load monitoring metrics — general sports science, **not** SkillCorner.

Moved out of ``skillcorner_metrics.py`` (where ACWR previously lived alongside
genuinely SkillCorner-sourced content) into its own honestly-named module: none
of this is from SkillCorner's methodology or toolkit. It's the standard
injury-risk/overtraining literature that session-level GPS load data like this
is built for.

**Load-proxy disclosure**: every metric here needs a single number per session
representing "how much work was done." The literature's standard input is
**session-RPE** (Rating of Perceived Exertion × duration) — we don't collect
RPE (no subjective-exertion field in the schema), so ``total_distance_m`` is
used as the load proxy instead, same choice already made for ACWR. This is a
real substitution, not the textbook input — see ``docs/load_monitoring.md``.

- **ACWR** (Acute:Chronic Workload Ratio): Gabbett, T.J. (2016). *The
  training—injury prevention paradox: should athletes be training smarter and
  harder?* British Journal of Sports Medicine, 50(5), 273-280.
- **Training Monotony & Strain**: Foster, C. (1998). *Monitoring training in
  athletes with reference to overtraining syndrome.* Medicine & Science in
  Sports & Exercise, 30(7), 1164-1168.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ACWR_ZONES = [
    (0.0, 0.8, "Undertrained"),
    (0.8, 1.3, "Optimal"),
    (1.3, 1.5, "Elevated Risk"),
    (1.5, float("inf"), "High Risk"),
]

MONOTONY_CAUTION_LEVEL = 2.0
"""Foster (1998): monotony at/above this level, combined with a high weekly
load, is a commonly cited caution point — not a hard, universally-validated
threshold. Treat as a prompt to look closer, not an automatic red flag."""


def daily_load(df: pd.DataFrame, load_col: str = "total_distance_m") -> pd.Series:
    """Resample per-session load to a daily sum (days with no session = 0).

    Shared by every function in this module — training/match load is recorded
    per session, but ACWR/monotony/strain are all defined over calendar days.
    """
    dates = pd.to_datetime(df["date"])
    load = pd.to_numeric(df[load_col], errors="coerce").fillna(0)
    daily = pd.Series(load.to_numpy(), index=dates).sort_index()
    return daily.groupby(daily.index).sum().resample("D").sum()


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
    is unitless).
    """
    daily = daily_load(df, load_col)
    acute = daily.rolling(acute_days, min_periods=1).sum()
    chronic = daily.rolling(chronic_days, min_periods=1).mean() * acute_days
    return (acute / chronic.replace(0, np.nan)).round(2)


def classify_monotony(value: float) -> str:
    if pd.isna(value):
        return "Unknown"
    if value < 1.0:
        return "Low"
    if value < MONOTONY_CAUTION_LEVEL:
        return "Normal"
    return "High — low day-to-day variability"


def weekly_monotony_and_strain(df: pd.DataFrame, load_col: str = "total_distance_m") -> pd.DataFrame:
    """One row per calendar week: total load, monotony, and strain.

    - **Monotony** = mean daily load ÷ standard deviation of daily load, over
      the week. High monotony means day-to-day load barely varies — every day
      looks the same, with no easier days built in.
    - **Strain** = weekly total load × monotony. Foster's flag for "a big week
      that was also monotonous" — the combination associated with
      overtraining risk, more than either figure alone.

    A week with only one session (SD undefined/zero) gets NaN monotony/strain
    rather than a divide-by-zero artifact.
    """
    daily = daily_load(df, load_col)
    if daily.empty:
        return pd.DataFrame(columns=["week_start", "weekly_load", "mean_daily_load", "sd_daily_load", "monotony", "strain"])

    weekly = daily.resample("W-MON", label="left", closed="left")
    rows = []
    for week_start, values in weekly:
        total = values.sum()
        mean = values.mean()
        sd = values.std()  # sample std (ddof=1) -- the common spreadsheet/coaching-tool convention
        monotony = round(mean / sd, 2) if sd > 0 else float("nan")
        strain = round(total * monotony, 1) if pd.notna(monotony) else float("nan")
        rows.append(
            {
                "week_start": week_start,
                "weekly_load": round(float(total), 1),
                "mean_daily_load": round(float(mean), 1),
                "sd_daily_load": round(float(sd), 2),
                "monotony": monotony,
                "strain": strain,
            }
        )
    return pd.DataFrame(rows)
