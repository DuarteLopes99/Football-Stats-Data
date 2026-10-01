"""Training-load monitoring: weekly load, week-over-week change, ACWR, monotony, strain.

General sports science, not SkillCorner. The load input is a GPS volume
(total distance by default, any summable metric on request) — the textbook
input is session-RPE, which this dataset doesn't collect.

- **ACWR** (acute:chronic workload ratio) — Gabbett (2016), *Br J Sports Med*
  50(5); weekly, uncoupled form as used by Ravé et al. (2020); EWMA variant
  after Williams et al. (2017). **A monitoring indicator, not an injury
  predictor** — Ravé et al. say so explicitly, and the dashboard repeats it.
- **Monotony & strain** — Foster (1998), *Med Sci Sports Exerc* 30(7).

Loads are always summed over **every session type**: ACWR describes what the
body absorbed, and a training-only ratio would omit the match. Rows without GPS
data contribute nothing (not zero); weeks containing such rows are flagged as
``incomplete`` because their total is a lower bound.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from football_stats.gps import config as cfg

ACWR_ZONES = cfg.ACWR_ZONES
MONOTONY_CAUTION_LEVEL = cfg.MONOTONY_CAUTION_LEVEL


def daily_load(df: pd.DataFrame, load_col: str = "total_distance_m") -> pd.Series:
    """Per-session load summed to calendar days (days without a session = 0)."""
    dates = pd.to_datetime(df["date"])
    load = pd.to_numeric(df[load_col], errors="coerce").fillna(0)
    daily = pd.Series(load.to_numpy(), index=dates).sort_index()
    if daily.empty:
        return daily
    return daily.groupby(daily.index).sum().resample("D").sum()


def classify_acwr(value: float) -> str:
    """Where one ratio sits against ``ACWR_SAFE_BAND``."""
    if pd.isna(value):
        return "Insufficient history"
    for low, high, label in ACWR_ZONES:
        if low <= value < high:
            return label
    return ACWR_ZONES[-1][2]


def compute_acwr(df: pd.DataFrame, load_col: str = "total_distance_m", acute_days: int = 7, chronic_days: int = 28) -> pd.Series:
    """Daily rolling ACWR, uncoupled: last ``acute_days`` summed ÷ the average
    ``acute_days``-block over the ``chronic_days`` *before* them.

    NaN until a full chronic window exists, and where the chronic load is 0 —
    an early-season ratio built on a few days of history is noise, not signal.
    """
    daily = daily_load(df, load_col)
    if daily.empty:
        return daily
    acute = daily.rolling(acute_days, min_periods=acute_days).sum()
    chronic = daily.shift(acute_days).rolling(chronic_days, min_periods=chronic_days).mean() * acute_days
    return (acute / chronic.replace(0, np.nan)).round(2)


def weekly_load(
    sessions: pd.DataFrame,
    metric: str = "total_distance_m",
    week_freq: str = cfg.WEEK_FREQ,
) -> pd.DataFrame:
    """One row per calendar week (gaps included as zero-load weeks).

    Columns: ``week_start``, ``week_end``, ``load``, one ``load_<category>``
    column per session type, ``sessions``, ``missing_sessions``, ``incomplete``,
    ``wow_pct`` (change on the previous week), ``spike`` (rise above
    ``WEEKLY_PROGRESSION_GUIDE_PCT``) and ``partial`` — the last week, when the
    data stops before its Saturday. A partial week's total is not comparable to
    a full one, so it gets no week-on-week change and no ACWR.
    """
    columns = ["week_start", "week_end", "load", *[f"load_{c}" for c in cfg.SESSION_CATEGORIES],
               "sessions", "missing_sessions", "incomplete", "partial", "wow_pct", "spike"]
    if sessions.empty:
        return pd.DataFrame(columns=columns)

    df = sessions.copy()
    df["date"] = pd.to_datetime(df["date"])
    measured = df[df["has_gps"]] if "has_gps" in df.columns else df

    def weekly_sum(frame: pd.DataFrame) -> pd.Series:
        series = pd.Series(pd.to_numeric(frame[metric], errors="coerce").fillna(0).to_numpy(), index=frame["date"])
        return series.groupby(level=0).sum()

    first, last = df["date"].min(), df["date"].max()
    days = pd.date_range(first, last, freq="D")
    total = weekly_sum(measured).reindex(days, fill_value=0).resample(week_freq).sum()
    out = pd.DataFrame({"week_end": total.index, "load": total.to_numpy()})
    out["week_start"] = out["week_end"] - pd.Timedelta(days=6)

    for category in cfg.SESSION_CATEGORIES:
        part = measured[measured["match_category"] == category] if "match_category" in measured.columns else measured.iloc[0:0]
        series = weekly_sum(part).reindex(days, fill_value=0).resample(week_freq).sum()
        out[f"load_{category}"] = series.to_numpy()

    counts = pd.Series(1, index=df["date"]).groupby(level=0).sum().reindex(days, fill_value=0).resample(week_freq).sum()
    out["sessions"] = counts.to_numpy()
    if "has_gps" in df.columns:
        missing_mask = ~df["has_gps"] & ~df.get("unused_sub", pd.Series(False, index=df.index))
        missing = pd.Series(missing_mask.astype(int).to_numpy(), index=df["date"]).groupby(level=0).sum()
        out["missing_sessions"] = missing.reindex(days, fill_value=0).resample(week_freq).sum().to_numpy()
    else:
        out["missing_sessions"] = 0
    out["incomplete"] = out["missing_sessions"] > 0
    out["partial"] = out["week_end"] > last

    previous = out["load"].shift(1)
    out["wow_pct"] = ((out["load"] - previous) / previous.replace(0, np.nan) * 100).round(1).where(~out["partial"])
    out["spike"] = out["wow_pct"] > cfg.WEEKLY_PROGRESSION_GUIDE_PCT
    return out[columns]


def weekly_acwr(
    sessions: pd.DataFrame,
    metric: str = "total_distance_m",
    method: str = cfg.ACWR_METHOD,
    chronic_weeks: int = cfg.ACWR_CHRONIC_WEEKS,
    min_history_weeks: int = cfg.ACWR_MIN_HISTORY_WEEKS,
) -> pd.DataFrame:
    """``weekly_load`` plus ``chronic``, ``acwr`` and ``acwr_zone`` per week.

    - ``"rolling"``: acute = this week's load; chronic = mean of the previous
      ``chronic_weeks`` weeks (this week excluded — uncoupled).
    - ``"ewma"``: daily loads smoothed with spans of
      ``ACWR_EWMA_ACUTE_DAYS`` / ``ACWR_EWMA_CHRONIC_DAYS``; the ratio is read
      on each week's last day.

    The first ``min_history_weeks`` weeks have no ratio (``acwr`` NaN,
    zone "Insufficient history"), and neither does a week whose chronic load is
    zero (e.g. straight after a break).
    """
    weekly = weekly_load(sessions, metric)
    if weekly.empty:
        return weekly.assign(chronic=pd.Series(dtype=float), acwr=pd.Series(dtype=float), acwr_zone=pd.Series(dtype=object))

    if method == "rolling":
        chronic = weekly["load"].shift(1).rolling(chronic_weeks, min_periods=chronic_weeks).mean()
        ratio = weekly["load"] / chronic.replace(0, np.nan)
    elif method == "ewma":
        measured = sessions[sessions["has_gps"]] if "has_gps" in sessions.columns else sessions
        days = pd.date_range(pd.to_datetime(sessions["date"]).min(), weekly["week_end"].max(), freq="D")
        daily = daily_load(measured, metric).reindex(days, fill_value=0)
        acute = daily.ewm(span=cfg.ACWR_EWMA_ACUTE_DAYS, adjust=False).mean()
        chronic_daily = daily.ewm(span=cfg.ACWR_EWMA_CHRONIC_DAYS, adjust=False).mean()
        at_week_end = weekly["week_end"].clip(upper=days.max())
        acute_end = acute.reindex(at_week_end).to_numpy()
        chronic_end = chronic_daily.reindex(at_week_end).to_numpy()
        chronic = pd.Series(chronic_end * 7, index=weekly.index)  # expressed as a weekly load
        ratio = pd.Series(acute_end / np.where(chronic_end == 0, np.nan, chronic_end), index=weekly.index)
    else:
        raise ValueError("method must be 'rolling' or 'ewma'")

    enough_history = pd.Series(np.arange(len(weekly)) >= min_history_weeks, index=weekly.index)
    weekly["chronic"] = chronic.round(1)
    weekly["acwr"] = ratio.where(enough_history & ~weekly["partial"]).round(2)
    weekly["acwr_zone"] = weekly["acwr"].map(classify_acwr).where(~weekly["partial"], "Partial week")
    return weekly


def classify_monotony(value: float) -> str:
    if pd.isna(value):
        return "Unknown"
    if value < 1.0:
        return "Low"
    if value < MONOTONY_CAUTION_LEVEL:
        return "Normal"
    return "High — low day-to-day variability"


def weekly_monotony_and_strain(df: pd.DataFrame, load_col: str = "total_distance_m") -> pd.DataFrame:
    """One row per calendar week (``WEEK_FREQ``, the same weeks as ACWR): total
    load, monotony, and strain.

    - **Monotony** = mean daily load ÷ standard deviation of daily load, over
      the week. High monotony means day-to-day load barely varies.
    - **Strain** = weekly total load × monotony (Foster's "big *and* monotonous").

    A week with zero variance gets NaN monotony/strain rather than infinity.
    """
    daily = daily_load(df, load_col)
    if daily.empty:
        return pd.DataFrame(columns=["week_start", "weekly_load", "mean_daily_load", "sd_daily_load", "monotony", "strain"])

    weekly = daily.resample(cfg.WEEK_FREQ)
    rows = []
    for week_end, values in weekly:
        week_start = week_end - pd.Timedelta(days=6)
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
