"""Join body-composition assessments to GPS sessions.

The two datasets have very different cadences: GPS records ~140 sessions a
season, body composition is measured every 3-9 weeks (22 assessments over three
seasons). They are joined **as-of**, not on equal footing — a session is tagged
with the most recent assessment at or before its date, because that is the body
that ran it. A session that happens to fall a week before an assessment is
still described by the *previous* one; using the nearest assessment in either
direction would let a later measurement explain an earlier session.

What this can and cannot support:

- **Can**: describe the body state a block of training was performed in; show
  how composition moved across a block and what the training load in that block
  looked like; give a rough daily energy cost of football to sit next to a
  nutrition plan.
- **Cannot**: attribute a composition change to training load, or to diet. The
  intake side is not measured at all, mass moves with hydration and glycogen as
  much as with fat, and with 22 assessments any correlation between a GPS
  metric and a body metric is a description of this dataset, not a finding.

Calorie figures are the GPS unit's own estimate of the *football* energy cost —
they exclude resting metabolism and everything done off the pitch, and
device-estimated expenditure is itself approximate. Treat them as a relative
signal ("this block was heavier than that one"), not as a kcal budget.
"""

from __future__ import annotations

import re

import pandas as pd

DEFAULT_BODY_METRICS = [
    "Peso",
    "Massa Gorda",
    "Massa Isenta de Gordura",
    "Massa Isenta de Gordura / Peso",
    "Massa Muscular",
    "Perímetro Coxa corrigido",
    "Coxa corrigida / peso",
]
"""Body metrics most relevant to running output, drawn from both the raw and
derived files: total mass and its fat/lean split, plus the two the extraction
script itself flags as football-facing (corrected thigh girth, and thigh
musculature relative to the mass it has to accelerate)."""

WINDOW_LOAD_COLUMNS = ["total_distance_m", "calories", "duration_min"]

_UNIT_SUFFIX = re.compile(r"\s*\([^()]*\)$")


def strip_unit_suffix(column: str) -> str:
    """``"Peso (kg)"`` -> ``"Peso"``.

    ``body_wide.csv`` appends the unit to each column header, while
    ``body_derived.csv`` and ``body_changes.csv`` keep metric and unit in
    separate columns. Callers name metrics the way the long files do, so the
    wide file's headers are normalized to match.
    """
    return _UNIT_SUFFIX.sub("", column).strip()


_NOT_A_METRIC = {"date", "season", "season_reported", "phase", "source", "assessment_id"}


def available_metrics(wide: pd.DataFrame, derived: pd.DataFrame) -> list[str]:
    """Every body metric present in the data, raw and derived, unit suffixes stripped.

    Read off the files rather than hardcoded. The dashboard previously carried a
    hand-written list of the raw metrics it knew about, because ``body_wide.csv``
    appends units to its headers ("Peso (kg)") and a metric therefore can't be
    looked up there by name. Stripping the suffix here instead means the eight
    individual skinfold sites and the raw girths — never in that hand-written
    list, and the measurements every fat estimate is actually built from —
    become selectable, and a metric added to the extraction script appears
    without this repo changing.
    """
    names = set()
    if not wide.empty:
        names.update(strip_unit_suffix(c) for c in wide.columns)
    if not derived.empty and "metric" in derived.columns:
        names.update(derived["metric"].dropna().unique())
    return sorted(names - _NOT_A_METRIC)


def body_long(
    wide: pd.DataFrame, derived: pd.DataFrame, metrics: list[str] | None = None
) -> pd.DataFrame:
    """One tidy ``date``/``metric``/``value`` table spanning raw and derived metrics.

    A metric can live in either file (``Peso`` is measured, ``Massa Gorda`` is
    computed), so callers shouldn't have to know which — this looks in both and
    prefers the raw file when a name appears in both.
    """
    wanted = metrics or DEFAULT_BODY_METRICS
    frames = []

    if not wide.empty:
        renamed = wide.rename(columns={c: strip_unit_suffix(c) for c in wide.columns})
        present = [m for m in wanted if m in renamed.columns]
        if present:
            id_vars = [c for c in ["date", "season", "phase"] if c in renamed.columns]
            melted = renamed.melt(
                id_vars=id_vars, value_vars=present, var_name="metric", value_name="value"
            )
            frames.append(melted.assign(source="measured"))

    if not derived.empty:
        already = set(frames[0]["metric"]) if frames else set()
        rows = derived[derived["metric"].isin([m for m in wanted if m not in already])]
        if not rows.empty:
            columns = [c for c in ["date", "season", "phase", "metric", "value"] if c in rows.columns]
            frames.append(rows[columns].assign(source="derived"))

    if not frames:
        return pd.DataFrame(columns=["date", "season", "phase", "metric", "value", "source"])

    out = pd.concat(frames, ignore_index=True)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.dropna(subset=["value"]).sort_values(["metric", "date"]).reset_index(drop=True)


def assessment_table(
    wide: pd.DataFrame, derived: pd.DataFrame, metrics: list[str] | None = None
) -> pd.DataFrame:
    """One row per assessment date, one column per requested body metric."""
    long = body_long(wide, derived, metrics)
    if long.empty:
        return pd.DataFrame(columns=["date"])
    index = [c for c in ["date", "season", "phase"] if c in long.columns]
    table = long.pivot_table(index=index, columns="metric", values="value", aggfunc="last")
    return table.reset_index().rename_axis(None, axis=1).sort_values("date").reset_index(drop=True)


def attach_body_state(
    sessions: pd.DataFrame,
    wide: pd.DataFrame,
    derived: pd.DataFrame,
    metrics: list[str] | None = None,
    max_staleness_days: int | None = 120,
) -> pd.DataFrame:
    """Tag each GPS session with the most recent assessment at or before its date.

    ``days_since_assessment`` is kept so a stale tag is visible rather than
    implied. Beyond ``max_staleness_days`` the body columns are blanked: an
    assessment four months old describes a different athlete, and carrying it
    forward indefinitely would invent a measurement that was never taken. Pass
    ``None`` to carry it forward regardless.
    """
    if sessions.empty:
        return sessions.copy()

    assessments = assessment_table(wide, derived, metrics)
    out = sessions.sort_values("date").copy()
    if assessments.empty:
        out["assessment_date"] = pd.NaT
        out["days_since_assessment"] = pd.NA
        return out

    body = assessments.drop(columns=[c for c in ["season", "phase"] if c in assessments.columns]).rename(
        columns={"date": "assessment_date"}
    )
    merged = pd.merge_asof(
        out,
        body.sort_values("assessment_date"),
        left_on="date",
        right_on="assessment_date",
        direction="backward",
    )
    merged.index = out.index
    merged["days_since_assessment"] = (merged["date"] - merged["assessment_date"]).dt.days

    if max_staleness_days is not None:
        stale = merged["days_since_assessment"] > max_staleness_days
        body_columns = [c for c in body.columns if c != "assessment_date"]
        merged.loc[stale, [*body_columns, "assessment_date"]] = pd.NA
        merged.loc[stale, "days_since_assessment"] = pd.NA
    return merged


def assessment_windows(
    sessions: pd.DataFrame,
    wide: pd.DataFrame,
    derived: pd.DataFrame,
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """One row per gap between consecutive assessments: training done, body change.

    This is the closest this data comes to a nutrition view — what the body did
    over a block, next to how much football was played in that block. The
    columns are deliberately side by side and not divided into each other: with
    no intake data and a handful of windows, a "kcal per kg lost" figure would
    read as a calculation when it is a coincidence.
    """
    assessments = assessment_table(wide, derived, metrics)
    if len(assessments) < 2:
        return pd.DataFrame(columns=["window_start", "window_end", "days"])

    metric_columns = [c for c in assessments.columns if c not in {"date", "season", "phase"}]
    dated = sessions.copy()
    dated["date"] = pd.to_datetime(dated["date"])

    rows = []
    for (_, start), (_, end) in zip(assessments.iloc[:-1].iterrows(), assessments.iloc[1:].iterrows()):
        window = dated[(dated["date"] > start["date"]) & (dated["date"] <= end["date"])]
        days = int((end["date"] - start["date"]).days)
        row = {
            "window_start": start["date"],
            "window_end": end["date"],
            "season": end["season"],
            "phase": end.get("phase"),
            "days": days,
            "sessions": len(window),
            "sessions_per_week": round(len(window) / days * 7, 2) if days else None,
        }
        for column in WINDOW_LOAD_COLUMNS:
            if column in window.columns:
                total = pd.to_numeric(window[column], errors="coerce").sum()
                row[f"total_{column}"] = round(float(total), 1)
        if days and "total_total_distance_m" in row:
            row["km_per_week"] = round(row["total_total_distance_m"] / 1000 / days * 7, 1)
        if days and "total_calories" in row:
            row["football_kcal_per_day"] = round(row["total_calories"] / days)
        for metric in metric_columns:
            before, after = start.get(metric), end.get(metric)
            row[f"{metric} (start)"] = before
            row[f"{metric} (end)"] = after
            if pd.notna(before) and pd.notna(after):
                row[f"{metric} (Δ)"] = round(float(after) - float(before), 2)
        rows.append(row)

    out = pd.DataFrame(rows)
    return out.rename(columns={"total_total_distance_m": "total_distance_m"})
