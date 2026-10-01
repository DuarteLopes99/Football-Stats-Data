"""At-a-glance body-composition summaries: what moved, which way, and whether
the move was big enough to mean anything.

Everything here funnels through ``data_store.change_verdict``, so a metric is
only ever called better or worse when two conditions hold together: the change
cleared that metric's smallest-worthwhile-change threshold, **and** the metric
has a direction worth having an opinion about. Body mass moving 1.5 kg is a
real change with no verdict attached — for a footballer, neither direction is
the goal — and it is reported as ``neutral`` rather than coloured green because
the number went up.
"""

from __future__ import annotations

import pandas as pd

from football_stats.body.data_store import (
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    MEANINGFUL_CHANGE,
    change_verdict,
    metric_direction,
)

HEADLINE_METRICS = [
    "Peso",
    "Massa Gorda",
    "Massa Isenta de Gordura",
    "Massa Muscular",
    "Massa Isenta de Gordura / Peso",
    "Soma de Pregas",
    "Perímetro Coxa corrigido",
    "Coxa corrigida / peso",
]
"""The short list worth putting at the top of the tab: total mass and its
fat/lean/muscle split, the lean fraction, the skinfold sum that drives the fat
estimates, and the two thigh measures the extraction script itself flags as
football-facing."""

VERDICT_ORDER = ["worse", "better", "noise", "neutral"]
"""Sort order for change tables — regressions first, because those are what a
summary exists to surface."""


def evolution(
    assessments: pd.DataFrame, metrics: list[str] | None = None, baseline: str = "first"
) -> pd.DataFrame:
    """Per-metric movement across the assessments in scope, with a verdict.

    ``baseline`` picks what "change" is measured against:

    - ``"first"`` — the earliest assessment in scope, i.e. movement across the
      whole period being viewed.
    - ``"previous"`` — the second-to-last assessment, i.e. the most recent step.

    Both are offered because they answer different questions and routinely
    disagree: fat mass can be down across a season while up since the last
    check. Reporting only one of them is how a summary becomes misleading.
    """
    columns = ["metric", "unit_direction", "baseline_value", "latest_value", "change", "pct_change",
               "threshold", "verdict"]
    if assessments.empty or len(assessments) < 1:
        return pd.DataFrame(columns=columns)

    available = [
        m for m in (metrics or _all_metric_columns(assessments)) if m in assessments.columns
    ]
    if not available:
        return pd.DataFrame(columns=columns)

    latest = assessments.iloc[-1]
    if len(assessments) == 1:
        reference = latest
    else:
        reference = assessments.iloc[0] if baseline == "first" else assessments.iloc[-2]

    rows = []
    for metric in available:
        start, end = pd.to_numeric(reference.get(metric), errors="coerce"), pd.to_numeric(
            latest.get(metric), errors="coerce"
        )
        if pd.isna(end):
            continue
        change = None if pd.isna(start) else round(float(end) - float(start), 2)
        rows.append(
            {
                "metric": metric,
                "unit_direction": metric_direction(metric),
                "baseline_value": None if pd.isna(start) else round(float(start), 2),
                "latest_value": round(float(end), 2),
                "change": change,
                "pct_change": (
                    round(change / float(start) * 100, 1)
                    if change is not None and start not in (0, None) and not pd.isna(start)
                    else None
                ),
                "threshold": MEANINGFUL_CHANGE.get(metric),
                "verdict": change_verdict(metric, change),
            }
        )

    out = pd.DataFrame(rows, columns=columns)
    order = {verdict: index for index, verdict in enumerate(VERDICT_ORDER)}
    return out.sort_values(
        ["verdict", "metric"], key=lambda s: s.map(order) if s.name == "verdict" else s
    ).reset_index(drop=True)


def _all_metric_columns(assessments: pd.DataFrame) -> list[str]:
    return [c for c in assessments.columns if c not in {"date", "season", "phase", "season_reported"}]


def headline(assessments: pd.DataFrame, metrics: list[str] | None = None) -> pd.DataFrame:
    """``evolution`` restricted to ``HEADLINE_METRICS``, in that fixed order.

    Fixed order rather than sorted by verdict: this row sits at the top of the
    tab on every visit, and a summary whose tiles move around between loads is
    harder to read at a glance than one that is always laid out the same way.
    """
    wanted = metrics or HEADLINE_METRICS
    rows = evolution(assessments, wanted, baseline="previous")
    if rows.empty:
        return rows
    order = {metric: index for index, metric in enumerate(wanted)}
    return rows.sort_values("metric", key=lambda s: s.map(order)).reset_index(drop=True)


def verdict_counts(evolution_table: pd.DataFrame) -> dict:
    """How many metrics improved, regressed, or didn't move enough to say.

    ``directional`` is the denominator that matters: only metrics with a
    direction can be better or worse at all, so quoting "3 improved" against a
    total that includes body mass and height would understate it.
    """
    if evolution_table.empty:
        return {"better": 0, "worse": 0, "noise": 0, "neutral": 0, "directional": 0}
    counts = evolution_table["verdict"].value_counts().to_dict()
    return {
        "better": int(counts.get("better", 0)),
        "worse": int(counts.get("worse", 0)),
        "noise": int(counts.get("noise", 0)),
        "neutral": int(counts.get("neutral", 0)),
        "directional": int(evolution_table["unit_direction"].isin({"up", "down"}).sum()),
    }


def phase_averages(assessments: pd.DataFrame, metrics: list[str] | None = None) -> pd.DataFrame:
    """Mean of each metric by season phase, in football-calendar order.

    The comparison the calendar actually supports: pre-season, first half,
    second half and run-in are different training states, and reading a body
    metric against the phase it was measured in is more meaningful than reading
    it against a date.
    """
    from football_stats.body.data_store import PHASE_ORDER

    if assessments.empty or "phase" not in assessments.columns:
        return pd.DataFrame()

    available = [m for m in (metrics or HEADLINE_METRICS) if m in assessments.columns]
    if not available:
        return pd.DataFrame()

    grouped = (
        assessments.groupby("phase")
        .agg(assessments=("date", "size"), **{m: (m, "mean") for m in available})
        .round(2)
        .reset_index()
    )
    order = {phase: index for index, phase in enumerate(PHASE_ORDER)}
    return grouped.sort_values("phase", key=lambda s: s.map(order).fillna(99)).reset_index(drop=True)


def direction_legend() -> pd.DataFrame:
    """Which metrics are read as better going up, better going down, or neither.

    Exposed so the dashboard can show the classification rather than asking the
    reader to infer it from the colours — a green arrow means nothing without
    knowing which way the metric is supposed to move.
    """
    rows = [{"metric": m, "better_when": "lower"} for m in sorted(LOWER_IS_BETTER)]
    rows += [{"metric": m, "better_when": "higher"} for m in sorted(HIGHER_IS_BETTER)]
    return pd.DataFrame(rows).sort_values("metric").reset_index(drop=True)
