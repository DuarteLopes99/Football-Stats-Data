"""Weekly Change % — each session against the comparable session before it.

**Default basis: same MD label, previous microcycle.** Tuesday's MD+2 session is
compared with last microcycle's MD+2, a match with the previous match. That is
the comparison the microcycle makes meaningful: an MD-3 (the week's loading
day) is *meant* to be bigger than the MD+2 before it, so comparing consecutive
sessions would flag the plan, not a change in it.

**Fallback: previous session of the same type** (same season), used when the
previous microcycle has no session with that label — after a break, in an 8-day
week, or when that session had no GPS data. Fallback cells are marked
(``fallback=True``) so the reader knows the basis changed.

**Alternative basis: vs Gref** — the session against the match reference, as a
signed % (−35 % = 35 % under one match's demand).

Never across types: training is only compared with training, official matches
with official matches, friendlies with friendlies.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from football_stats.gps import config as cfg
from football_stats.gps.reference import MatchReference


def pct_change(current, base) -> float:
    """(current − base) / base × 100; NaN when either is missing or base is 0."""
    if current is None or base is None or pd.isna(current) or pd.isna(base) or base == 0:
        return float("nan")
    return round((float(current) - float(base)) / float(base) * 100, 1)


def _previous_microcycles(season: pd.DataFrame) -> dict:
    """microcycle_id -> the id of the microcycle before it (by start date)."""
    starts = season.groupby("microcycle_id")["microcycle_start"].first().sort_values(na_position="first")
    ids = list(starts.index)
    return {current: (ids[i - 1] if i > 0 else None) for i, current in enumerate(ids)}


def weekly_change(
    sessions: pd.DataFrame,
    metrics: list[str] | None = None,
    mode: str = cfg.DEFAULT_CHANGE_MODE,
    reference: MatchReference | None = None,
) -> pd.DataFrame:
    """One row per session with ``{metric}``, ``{metric}_base`` and ``{metric}_pct``.

    ``sessions`` must be prepared and MD-labelled (``gps.cleaning`` →
    ``gps.microcycle``) and should be the whole season, not the filtered view:
    the comparison for the first session on screen usually lies before the
    selected range. Filter the result instead.
    """
    metrics = metrics or cfg.REPORT_METRICS
    if mode not in cfg.CHANGE_MODES:
        raise ValueError(f"mode must be one of {list(cfg.CHANGE_MODES)}")
    if mode == "gref" and reference is None:
        raise ValueError("mode='gref' needs a MatchReference")

    rows = []
    for _, season in sessions.groupby("season", sort=False):
        season = season.sort_values("date")
        previous_of = _previous_microcycles(season)
        measured = season[season["has_gps"]]

        for idx, row in season.iterrows():
            record = {"index": idx, "compare_date": pd.NaT, "compare_md_label": None, "fallback": False, "basis": None}
            base = None
            if row["has_gps"] and mode == "previous_microcycle":
                same_type = measured[(measured["match_category"] == row["match_category"]) & (measured["date"] < row["date"])]
                prior_micro = previous_of.get(row["microcycle_id"])
                candidates = same_type[
                    (same_type["microcycle_id"] == prior_micro) & (same_type["md_label"] == row["md_label"])
                ] if prior_micro is not None and row["md_label"] != cfg.PRESEASON_LABEL else same_type.iloc[0:0]
                if not candidates.empty:
                    base = candidates.iloc[-1]
                    record["basis"] = "same MD, previous microcycle"
                elif not same_type.empty:
                    base = same_type.iloc[-1]
                    record.update(fallback=True, basis=f"previous {cfg.SESSION_CATEGORY_LABELS[row['match_category']].lower()}")
                if base is not None:
                    record["compare_date"] = base["date"]
                    record["compare_md_label"] = base["md_label"]
            elif row["has_gps"] and mode == "gref":
                record["basis"] = "Gref"

            for metric in metrics:
                current = row[metric]
                if mode == "gref":
                    base_value = reference.get(metric) if row["has_gps"] else None
                else:
                    base_value = base[metric] if base is not None else None
                record[metric] = current
                record[f"{metric}_base"] = base_value if base_value is not None else np.nan
                record[f"{metric}_pct"] = pct_change(current, base_value) if row["has_gps"] else float("nan")
            rows.append(record)

    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).set_index("index")
    context = ["date", "season", "match_category", "session_type", "md_label", "microcycle_id",
               "minutes_played", "has_gps", "unused_sub", "short_appearance"]
    return sessions[[c for c in context if c in sessions.columns]].join(result).sort_values("date")
