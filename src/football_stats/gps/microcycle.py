"""Match-day (MD) labels and microcycles, following Ravé et al. (2020).

**Labelling rule** (all day counts are calendar days, per season):

1. An official-match date is ``MD``.
2. A session up to ``MD_PLUS_MAX_DAYS`` after the previous official match is
   ``MD+k`` (the recovery days).
3. Any other session is ``MD-n``, *n* = days left to the next official match.
4. Before a season's first official match: ``MD-n`` within
   ``PRESEASON_LEAD_DAYS`` of it, ``PRE`` (pre-season) earlier than that.
5. After a season's last official match: ``MD+k`` whatever *k* is.

With the usual Sunday match and Tue/Thu/Fri training that gives MD+2, MD-3 and
MD-2. **Friendlies never anchor** — a Thursday friendly before a Sunday match
is an MD-3 session that happens to have a scoreline.

**Microcycle**: from one official match day to the day before the next (Ravé's
"starts on MD, ends on MD-1"). Each session's microcycle is identified by the
match that opened it. A microcycle longer than ``EXTENDED_MICROCYCLE_DAYS``
(winter break, free weekend) is flagged, because its MD-n labels count down
from much further away than a normal week's.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from football_stats.gps import config as cfg

MD_COLUMNS = [
    "md_label", "md_offset", "md_order", "microcycle_id", "microcycle_start",
    "microcycle_end", "microcycle_days", "microcycle_extended",
]


def md_label(offset: int | None) -> str:
    """``0 -> "MD"``, ``2 -> "MD+2"``, ``-3 -> "MD-3"``, ``None -> "PRE"``."""
    if offset is None or pd.isna(offset):
        return cfg.PRESEASON_LABEL
    offset = int(offset)
    return "MD" if offset == 0 else f"MD{offset:+d}"


def md_order(label: str) -> int:
    """Sort key that reads like a week: MD, MD+1, MD+2, MD-5 … MD-1, PRE."""
    if label == "MD":
        return 0
    if label == cfg.PRESEASON_LABEL:
        return 1000
    offset = int(label[2:])
    return offset if offset > 0 else 100 + offset


def _season_labels(season: pd.DataFrame) -> pd.DataFrame:
    dates = season["date"]
    anchors = np.sort(
        season.loc[season["match_category"].isin(cfg.MD_ANCHOR_CATEGORIES), "date"].unique()
    )
    out = pd.DataFrame(index=season.index, columns=MD_COLUMNS)
    last_session = dates.max()

    for idx, day in dates.items():
        day64 = np.datetime64(day)
        position = np.searchsorted(anchors, day64, side="right")  # anchors[:position] <= day
        previous = pd.Timestamp(anchors[position - 1]) if position > 0 else None
        upcoming = pd.Timestamp(anchors[position]) if position < len(anchors) else None

        since = (day - previous).days if previous is not None else None
        until = (upcoming - day).days if upcoming is not None else None

        if since == 0:
            offset = 0
        elif since is not None and (since <= cfg.MD_PLUS_MAX_DAYS or until is None):
            offset = since
        elif until is not None and (previous is not None or until <= cfg.PRESEASON_LEAD_DAYS):
            offset = -until
        else:
            offset = None

        start = previous
        end = (upcoming - pd.Timedelta(days=1)) if upcoming is not None else last_session
        if start is None:
            micro_id = f"{cfg.PRESEASON_LABEL} {season['season'].iloc[0]}"
            days = None
        else:
            micro_id = f"MD {start:%Y-%m-%d}"
            days = (end - start).days + 1

        label = md_label(offset)
        out.loc[idx] = [
            label, offset, md_order(label), micro_id, start, end, days,
            bool(days is not None and days > cfg.EXTENDED_MICROCYCLE_DAYS),
        ]
    return out


def add_md_labels(sessions: pd.DataFrame) -> pd.DataFrame:
    """Add ``md_label``, ``md_offset`` and the microcycle columns to every row.

    Expects ``date``, ``season`` and ``match_category`` (see
    ``gps.cleaning.prepare_sessions``). Labelled per season, so the summer
    break never stretches one season's last match into the next pre-season.
    """
    df = sessions.copy()
    if df.empty:
        for column in MD_COLUMNS:
            df[column] = pd.Series(dtype=object)
        return df
    labelled = pd.concat([_season_labels(group) for _, group in df.groupby("season", sort=False)])
    for column in MD_COLUMNS:
        df[column] = labelled[column]
    df["md_offset"] = pd.to_numeric(df["md_offset"], errors="coerce").astype("Int64")
    df["md_order"] = df["md_order"].astype(int)
    df["microcycle_start"] = pd.to_datetime(df["microcycle_start"])
    df["microcycle_end"] = pd.to_datetime(df["microcycle_end"])
    df["microcycle_days"] = pd.to_numeric(df["microcycle_days"], errors="coerce").astype("Int64")
    df["microcycle_extended"] = df["microcycle_extended"].astype(bool)
    return df


def ordered_labels(labels) -> list[str]:
    """Unique MD labels in week order."""
    return sorted(set(labels), key=md_order)
