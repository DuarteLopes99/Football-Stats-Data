"""Fatigue, mechanical load and speed-exposure metrics.

Three columns in the GPS schema were being parsed, summed and given display
labels without any analysis ever reading them: ``sprints_1st_half``,
``sprints_2nd_half`` and — as an independent load axis rather than a per-90 rate
— ``accelerations`` / ``decelerations``. This module uses them.

The unifying idea is that ``total_distance_m`` measures only one kind of cost.
It is a **metabolic** proxy: how much running was done. It says nothing about
the **mechanical** cost of changing speed, which is what actually damages
muscle, and nothing about whether output held up across a match. A player can
cover the same distance in two matches while accelerating half as often in one
of them, and distance-based load monitoring will call those identical.
"""

from __future__ import annotations

import pandas as pd

from football_stats.gps import config as cfg

MECHANICAL_LOAD_COLUMN = "mechanical_load"
"""Accelerations + decelerations. A count of speed *changes*, standing in for
the eccentric/neuromuscular cost that distance can't see. It is a proxy, not a
measured force: the device's own thresholds decide what counts as an
acceleration, and those are not in this dataset."""

BALANCED_ACCEL_DECEL = cfg.BALANCED_ACCEL_DECEL
"""Range within which the accel:decel ratio is treated as balanced.

Decelerating is eccentric and is the more damaging half of the pair, so a ratio
persistently below this band means braking is outpacing accelerating. Treat it
as a prompt to look at soreness, not as a diagnostic — the band is a reasonable
symmetry interval, **not** a validated threshold from the literature."""

NEAR_MAX_SPEED_PCT = cfg.NEAR_MAX_SPEED_PCT
"""Share of the reference top speed above which a session counts as high-speed
exposure. Regular near-maximal sprinting is widely used as a hamstring-injury
prevention target in team sport; 90% is the common working figure, and the
reference speed here is the player's own best in the current scope."""


SECOND_HALF_MIN_MINUTES = cfg.SECOND_HALF_MIN_MINUTES
"""Minutes a player must have been on the pitch for before a second-half sprint
count means anything.

This is not a tuning knob, it is a correctness guard. Three matches in the
current data show 18-25 first-half sprints followed by **zero** in the second,
and all three are 45-minute appearances — the player was substituted at half
time. Read naively those look like total second-half collapse and drag the
median retention from 0.55 to 0.45. A player who wasn't on the pitch didn't
fade; he left."""


def second_half_retention(
    sessions: pd.DataFrame, min_minutes: float = SECOND_HALF_MIN_MINUTES
) -> pd.DataFrame:
    """Second-half sprint count as a share of the first half, per match.

    The most direct fatigue signal this dataset holds, and the one it had never
    been asked for. A retention of 1.0 means the same number of sprints in both
    halves; 0.5 means output halved after the break.

    Two exclusions, both about not mistaking absence for fatigue:

    - **Matches with a zero first half** — a 0 -> 3 match is a substitute who
      came on at half time, and dividing by zero would present that as infinite
      improvement.
    - **Matches shorter than ``min_minutes``** — see ``SECOND_HALF_MIN_MINUTES``.
      Official match-sheet minutes are used where recorded, since the GPS unit's
      runtime includes warm-down and would let a 45-minute appearance pass.
    """
    columns = ["date", "session_type", "match_category", "was_starter", "minutes_played",
               "sprints_1st_half", "sprints_2nd_half", "second_half_retention"]
    if sessions.empty or "sprints_1st_half" not in sessions.columns:
        return pd.DataFrame(columns=columns)

    df = sessions.copy()
    first = pd.to_numeric(df["sprints_1st_half"], errors="coerce")
    second = pd.to_numeric(df["sprints_2nd_half"], errors="coerce")

    sheet = pd.to_numeric(df.get("minutes_game_zerozero"), errors="coerce")
    runtime = pd.to_numeric(df.get("duration_min"), errors="coerce")
    df["minutes_played"] = sheet.where(sheet > 0, runtime)

    eligible = first.notna() & second.notna() & (first > 0) & (df["minutes_played"] >= min_minutes)
    if not eligible.any():
        return pd.DataFrame(columns=columns)

    df = df[eligible].copy()
    df["second_half_retention"] = (second[eligible] / first[eligible]).round(2)
    return df[[c for c in columns if c in df.columns]].sort_values("date", ascending=False).reset_index(drop=True)


def retention_summary(retention: pd.DataFrame) -> pd.DataFrame:
    """Median retention by match category, with the observed range.

    Split by category because official matches and friendlies are different
    tests: opponent quality, tempo and the consequences of easing off all
    differ, and pooling them hides the only comparison the data supports.

    Median rather than mean, and ``min``/``max`` alongside it: with a handful of
    matches per bucket a single value shouldn't be read as a level, and showing
    the spread makes that hard to forget.
    """
    columns = ["match_category", "matches", "median_retention", "min_retention", "max_retention"]
    if retention.empty or "match_category" not in retention.columns:
        return pd.DataFrame(columns=columns)
    return (
        retention.groupby("match_category")
        .agg(
            matches=("second_half_retention", "size"),
            median_retention=("second_half_retention", "median"),
            min_retention=("second_half_retention", "min"),
            max_retention=("second_half_retention", "max"),
        )
        .round(2)
        .reset_index()
    )


def add_mechanical_load(sessions: pd.DataFrame) -> pd.DataFrame:
    """Add ``mechanical_load``, ``mechanical_load_per_min`` and ``accel_decel_ratio``.

    ``mechanical_load`` is the count of speed changes; the per-minute version
    makes sessions of different lengths comparable; the ratio says whether the
    two halves of that count are balanced.
    """
    df = sessions.copy()
    accelerations = pd.to_numeric(df.get("accelerations"), errors="coerce")
    decelerations = pd.to_numeric(df.get("decelerations"), errors="coerce")
    minutes = pd.to_numeric(df.get("duration_min"), errors="coerce")

    df[MECHANICAL_LOAD_COLUMN] = accelerations.fillna(0) + decelerations.fillna(0)
    df.loc[accelerations.isna() & decelerations.isna(), MECHANICAL_LOAD_COLUMN] = pd.NA

    df["mechanical_load_per_min"] = (
        pd.to_numeric(df[MECHANICAL_LOAD_COLUMN], errors="coerce") / minutes.where(minutes > 0)
    ).round(2)
    df["accel_decel_ratio"] = (accelerations / decelerations.where(decelerations > 0)).round(2)
    return df


def classify_accel_decel_ratio(value: float) -> str:
    """Where one accel:decel ratio sits relative to ``BALANCED_ACCEL_DECEL``."""
    if pd.isna(value):
        return "Unknown"
    low, high = BALANCED_ACCEL_DECEL
    if value < low:
        return "Deceleration-dominant"
    if value > high:
        return "Acceleration-dominant"
    return "Balanced"


def high_speed_exposure(
    sessions: pd.DataFrame, reference_speed: float | None = None, threshold_pct: float = NEAR_MAX_SPEED_PCT
) -> pd.DataFrame:
    """Sessions per month that reached ``threshold_pct`` of the reference top speed.

    "How often do I actually get near top gear?" — a training-quality question
    that volume metrics cannot answer, and one where the honest denominator is
    the number of sessions in the month, since a month with 8 sessions and one
    with 18 are not comparable on counts alone.

    ``reference_speed`` defaults to the fastest session in scope, so the measure
    is always relative to what this player has actually produced rather than to
    an external benchmark that doesn't exist for amateur football.
    """
    columns = ["month_label", "sessions", "near_max_sessions", "near_max_pct", "best_speed_kmh"]
    if sessions.empty or "top_speed_kmh" not in sessions.columns:
        return pd.DataFrame(columns=columns)

    df = sessions.copy()
    df["date"] = pd.to_datetime(df["date"])
    speeds = pd.to_numeric(df["top_speed_kmh"], errors="coerce")
    df = df[speeds.notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=columns)

    df["top_speed_kmh"] = speeds[speeds.notna()]
    reference = reference_speed if reference_speed else float(df["top_speed_kmh"].max())
    if not reference:
        return pd.DataFrame(columns=columns)

    df["near_max"] = df["top_speed_kmh"] >= reference * threshold_pct
    df["month_label"] = df["date"].dt.to_period("M").astype(str)

    grouped = (
        df.groupby("month_label")
        .agg(sessions=("near_max", "size"), near_max_sessions=("near_max", "sum"),
             best_speed_kmh=("top_speed_kmh", "max"))
        .reset_index()
    )
    grouped["near_max_pct"] = (grouped["near_max_sessions"] / grouped["sessions"] * 100).round(1)
    grouped["best_speed_kmh"] = grouped["best_speed_kmh"].round(2)
    return grouped[columns]


def training_match_intensity_gap(sessions: pd.DataFrame) -> pd.DataFrame:
    """Training intensity as a share of official-match intensity, per month.

    The classic coaching question — *am I training at the intensity I have to
    play at?* — expressed as a tracked number rather than a snapshot radar. A
    value of 100% means training reaches match intensity; 60% means it does not.

    Uses intensity *shares* (high-speed and sprint distance as a fraction of
    total), not absolute distances, so a shorter training session isn't
    penalised for being shorter. Months without both a training session and an
    official match are dropped rather than compared against nothing.
    """
    columns = ["month_label", "training_sessions", "official_matches",
               "high_speed_gap_pct", "sprint_gap_pct"]
    required = {"match_category", "total_distance_m", "high_speed_distance_m", "sprint_distance_m"}
    if sessions.empty or not required.issubset(sessions.columns):
        return pd.DataFrame(columns=columns)

    df = sessions.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month_label"] = df["date"].dt.to_period("M").astype(str)

    total = pd.to_numeric(df["total_distance_m"], errors="coerce")
    safe_total = total.where(total > 0)
    df["high_speed_pct"] = pd.to_numeric(df["high_speed_distance_m"], errors="coerce") / safe_total * 100
    df["sprint_pct"] = pd.to_numeric(df["sprint_distance_m"], errors="coerce") / safe_total * 100

    rows = []
    for month, block in df.groupby("month_label"):
        training = block[block["match_category"] == "training"]
        matches = block[block["match_category"] == "official_match"]
        if training.empty or matches.empty:
            continue
        row = {"month_label": month, "training_sessions": len(training), "official_matches": len(matches)}
        for metric, label in [("high_speed_pct", "high_speed_gap_pct"), ("sprint_pct", "sprint_gap_pct")]:
            match_level = matches[metric].mean()
            row[label] = (
                round(training[metric].mean() / match_level * 100, 1)
                if pd.notna(match_level) and match_level > 0
                else None
            )
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)
