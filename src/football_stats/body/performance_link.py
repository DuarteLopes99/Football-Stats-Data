"""Does body composition relate to running output? — with the statistics needed
to answer "no" honestly.

This module exists to test a question, not to decorate one. The tempting
version of this analysis correlates every GPS metric against every body metric
and reports the strongest few; with ~20 body metrics against ~8 performance
metrics that is 160 tests, and at n≈20 assessments several will clear p<0.05
from noise alone. Everything here is built to stop that:

- **Spearman, not Pearson.** Body composition moves in small monotonic drifts
  with occasional step changes; rank correlation doesn't assume linearity and
  isn't dragged by one pre-season outlier.
- **Multiplicity is corrected for.** ``correlate_body_vs_performance`` reports
  a Benjamini-Hochberg adjusted q-value beside every raw p-value, computed over
  the whole grid that was actually tested.
- **n is on every row**, and every row carries a ``reliability`` tier derived
  from it. Pairs are analysed at whatever n exists rather than withheld: the
  binding constraint here is how many assessments have training behind them,
  and a floor set above that number turns the whole tab into a blank page.
  ``MIN_PAIRS`` therefore marks where a coefficient becomes *worth trusting*,
  not where it becomes visible — ``ABSOLUTE_MIN_PAIRS`` is the only hard floor,
  and it is simply the point below which a rank correlation does not exist.
- **The verdict is stated in words.** ``summarise_findings`` says "nothing
  survived correction" when that is the answer, which — on a single player's
  season — is the result to expect.

Even a surviving correlation is not causal here. Body composition, training
load and match minutes all move together across a season: fat mass falls
through pre-season while running volume rises, so the two correlate without
either driving the other. Read anything found as *"these moved together"*, and
go no further.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from football_stats.body.data_store import metric_direction

MIN_PAIRS = 8
"""Observations at which a coefficient starts being worth acting on.

Not a gate. Below this a rank correlation is weakly constrained — with 5 points
a coefficient of 0.9 is unremarkable — but withholding the result entirely, as
an earlier version of this module did, answered a question nobody asked: with
this dataset *every* pair sat below the line, so the tab showed nothing at all.
The analysis now runs at whatever n is available and labels the strength of the
evidence per row (see ``reliability_tier``), which is the honest version of
"limited by data availability"."""

ABSOLUTE_MIN_PAIRS = 4
"""The only hard floor: fewer points than this and a rank correlation is not a
statistic, it is a drawing. With 3 points Spearman takes one of a handful of
discrete values and |rho| = 1.0 occurs by chance about a third of the time."""

RELIABILITY_TIERS = [
    (MIN_PAIRS, "worth acting on"),
    (6, "indicative"),
    (ABSOLUTE_MIN_PAIRS, "anecdotal"),
]
"""``(minimum n, label)`` from strongest to weakest, checked in order."""


def reliability_tier(n: int) -> str:
    """How much weight one pair's coefficient can carry, from its sample size.

    Stated per row rather than as a single caveat over the table, because the
    pairs genuinely differ: a body metric measured at every assessment has more
    points behind it than one the nutritionist recorded twice.
    """
    for threshold, label in RELIABILITY_TIERS:
        if n >= threshold:
            return label
    return "not testable"

STRONG_RHO = 0.5
"""|rho| at or above which a surviving correlation is called strong. A
convention for wording the summary, not a significance test."""

DEFAULT_PERFORMANCE_METRICS = [
    "total_distance_m",
    "distance_per_min",
    "high_speed_distance_m",
    "sprint_distance_m",
    "top_speed_kmh",
    "sprints_total",
    "accelerations",
    "decelerations",
]


def performance_per_assessment(
    sessions: pd.DataFrame,
    assessments: pd.DataFrame,
    metrics: list[str] | None = None,
    lookback_days: int = 28,
) -> pd.DataFrame:
    """Average GPS output over the ``lookback_days`` **before** each assessment.

    The alignment is the whole analysis. A body measurement describes the state
    an athlete arrived in, so it is paired with the training that came *before*
    it, never after. A 28-day window matches the chronic-load window used by
    ACWR and is long enough to cover a normal training microcycle without
    reaching back into a different block.

    Sessions are averaged, not summed: a window containing 12 sessions and one
    containing 6 would otherwise differ on volume alone, which is a fact about
    the fixture list rather than about the player.
    """
    if sessions.empty or assessments.empty:
        return pd.DataFrame()

    wanted = [m for m in (metrics or DEFAULT_PERFORMANCE_METRICS) if m in sessions.columns]
    dated = sessions.copy()
    dated["date"] = pd.to_datetime(dated["date"])

    rows = []
    for _, assessment in assessments.iterrows():
        end = assessment["date"]
        window = dated[(dated["date"] > end - pd.Timedelta(days=lookback_days)) & (dated["date"] <= end)]
        row = {
            "date": end,
            "season": assessment.get("season"),
            "phase": assessment.get("phase"),
            "sessions_in_window": len(window),
        }
        for metric in wanted:
            values = pd.to_numeric(window[metric], errors="coerce").dropna()
            row[metric] = round(float(values.mean()), 2) if len(values) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _spearman(x: pd.Series, y: pd.Series) -> tuple[float, float, int]:
    """Spearman rho and a two-sided p-value, falling back to NaN when degenerate."""
    paired = pd.concat([x, y], axis=1).dropna()
    n = len(paired)
    if n < 3:
        return np.nan, np.nan, n
    left, right = paired.iloc[:, 0], paired.iloc[:, 1]
    if left.nunique() < 2 or right.nunique() < 2:
        return np.nan, np.nan, n
    try:
        from scipy import stats

        result = stats.spearmanr(left, right)
        return float(result.statistic), float(result.pvalue), n
    except Exception:
        # scipy is a declared dependency; this keeps the table renderable if the
        # import ever fails rather than taking the whole tab down.
        return float(left.corr(right, method="spearman")), np.nan, n


def _benjamini_hochberg(pvalues: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted q-values, preserving the input's order.

    Controls the false-discovery rate across the whole grid of tests, which is
    the honest denominator: the question asked was "does anything here relate to
    anything", not "does this one pair relate", and only correcting for the
    tests you liked is how a grid search becomes a finding.
    """
    clean = pvalues.dropna()
    if clean.empty:
        return pd.Series(np.nan, index=pvalues.index)

    ordered = clean.sort_values()
    n = len(ordered)
    ranks = np.arange(1, n + 1)
    adjusted = np.minimum.accumulate((ordered.to_numpy() * n / ranks)[::-1])[::-1]
    return pd.Series(np.minimum(adjusted, 1.0), index=ordered.index).reindex(pvalues.index)


def correlate_body_vs_performance(
    body: pd.DataFrame,
    performance: pd.DataFrame,
    body_metrics: list[str] | None = None,
    performance_metrics: list[str] | None = None,
    min_pairs: int = ABSOLUTE_MIN_PAIRS,
) -> pd.DataFrame:
    """Spearman correlation for every body × performance pair, FDR-corrected.

    ``body`` and ``performance`` are both indexed by assessment date (the output
    of ``assessment_table`` and ``performance_per_assessment``). Returns one row
    per tested pair, strongest first, with ``n``, ``rho``, ``p_value``, the
    adjusted ``q_value`` and a ``reliability`` tier.

    ``min_pairs`` defaults to ``ABSOLUTE_MIN_PAIRS``, which lets the analysis
    run on the data that exists instead of on the data it would prefer. Raise it
    to ``MIN_PAIRS`` to see only the pairs that carry real weight. Either way
    ``reliability`` and ``n`` stay on every row, so a thin pair is labelled
    rather than laundered.
    """
    if body.empty or performance.empty:
        return pd.DataFrame(
            columns=["body_metric", "performance_metric", "n", "rho", "p_value", "q_value", "reliability"]
        )

    merged = body.merge(performance, on="date", suffixes=("", "_perf"))
    body_names = [
        m for m in (body_metrics or [c for c in body.columns if c not in {"date", "season", "phase"}])
        if m in merged.columns
    ]
    performance_names = [
        m for m in (performance_metrics or DEFAULT_PERFORMANCE_METRICS) if m in merged.columns
    ]

    rows = []
    for body_metric in body_names:
        for performance_metric in performance_names:
            rho, p_value, n = _spearman(
                pd.to_numeric(merged[body_metric], errors="coerce"),
                pd.to_numeric(merged[performance_metric], errors="coerce"),
            )
            if n < min_pairs or pd.isna(rho):
                continue
            rows.append(
                {
                    "body_metric": body_metric,
                    "performance_metric": performance_metric,
                    "n": n,
                    "rho": round(rho, 3),
                    "p_value": round(p_value, 4) if pd.notna(p_value) else np.nan,
                    "reliability": reliability_tier(n),
                    "body_direction": metric_direction(body_metric),
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=["body_metric", "performance_metric", "n", "rho", "p_value", "q_value", "reliability"]
        )

    out = pd.DataFrame(rows)
    out["q_value"] = _benjamini_hochberg(out["p_value"]).round(4)
    out["survives_fdr"] = out["q_value"] < 0.05
    return out.reindex(out["rho"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def summarise_findings(correlations: pd.DataFrame) -> dict:
    """A plain-language verdict on the whole grid, for the dashboard to print.

    Deliberately reports the number of tests alongside the number of survivors:
    "2 of 160" and "2 of 4" are very different claims, and only the first one is
    visible without the denominator.
    """
    if correlations.empty:
        return {
            "tested": 0,
            "survivors": 0,
            "best_n": 0,
            "underpowered": True,
            "suspect_survivors": 0,
            "verdict": "No assessment has enough training behind it to correlate anything.",
            "detail": (
                f"A pair needs at least {ABSOLUTE_MIN_PAIRS} assessments with sessions in the "
                "lookback window before a rank correlation exists at all. Widening the window "
                "above will pull more assessments into range."
            ),
        }

    tested = len(correlations)
    best_n = int(correlations["n"].max())
    survivors = correlations[correlations["survives_fdr"]]
    strongest = correlations.iloc[0]
    underpowered = best_n < MIN_PAIRS

    # The power caveat leads, because at these sample sizes it dominates both
    # possible outcomes: "nothing survived" is unsurprising when nothing could
    # have survived, and a survivor at n=6 is a weaker claim than the same
    # q-value at n=20 would be.
    power_note = (
        f"Every pair here rests on at most {best_n} paired assessments, below the "
        f"{MIN_PAIRS} at which a coefficient starts carrying real weight. At this size the "
        "test has little power to detect a true relationship, so a null is weak evidence of "
        "absence — and any coefficient that does clear correction deserves to be treated as a "
        "lead to re-check next season rather than as a result."
        if underpowered
        else ""
    )

    if survivors.empty:
        return {
            "tested": tested,
            "survivors": 0,
            "best_n": best_n,
            "underpowered": underpowered,
            "suspect_survivors": 0,
            "verdict": "Nothing here separates from chance.",
            "detail": (
                f"{tested} pairs tested; none survives false-discovery correction. The strongest "
                f"raw association is {strongest['body_metric']} vs. "
                f"{strongest['performance_metric']} (rho = {strongest['rho']:+.2f}, "
                f"n = {int(strongest['n'])}, {strongest['reliability']}) — about what the largest "
                f"of {tested} correlations looks like when there is nothing to find. " + power_note
            ),
        }

    strong = survivors[survivors["rho"].abs() >= STRONG_RHO]

    # A coefficient at or near +/-1.0 on a handful of points is the signature of
    # too few points, not of a strong relationship: with n = 6 there are only
    # 720 possible rank orderings, and one of them is the perfect one. It clears
    # FDR precisely because its p-value is computed as though the sample size
    # were adequate, so it has to be named rather than left to look like the
    # strongest finding on the page.
    perfect = survivors[(survivors["rho"].abs() >= 0.99) & (survivors["n"] < MIN_PAIRS)]
    perfect_note = (
        f" {len(perfect)} of the survivors sit at |rho| >= 0.99 on fewer than {MIN_PAIRS} points — "
        "a perfect rank order over a handful of assessments, which is what too few points looks "
        "like rather than a strong relationship."
        if not perfect.empty
        else ""
    )

    return {
        "tested": tested,
        "survivors": len(survivors),
        "best_n": best_n,
        "underpowered": underpowered,
        "suspect_survivors": len(perfect),
        "verdict": f"{len(survivors)} of {tested} pairs survive false-discovery correction.",
        "detail": (
            f"{len(strong)} of those reach |rho| >= {STRONG_RHO}. Body composition, training load "
            "and match minutes all drift together across a season, so a surviving correlation "
            "still means 'these moved together', not that one drove the other." + perfect_note
            + " " + power_note
        ),
    }


def phase_profile(
    performance: pd.DataFrame, metrics: list[str] | None = None
) -> pd.DataFrame:
    """Mean performance per season phase — the comparison the calendar supports.

    Grouping by phase asks a question a correlation can't: pre-season, first
    half, second half and run-in are different training blocks, and comparing
    them is more defensible than fitting a trend through dates that span two
    off-seasons.
    """
    if performance.empty or "phase" not in performance.columns:
        return pd.DataFrame()

    wanted = [m for m in (metrics or DEFAULT_PERFORMANCE_METRICS) if m in performance.columns]
    if not wanted:
        return pd.DataFrame()

    aggregations = {"assessments": ("date", "size"), "sessions": ("sessions_in_window", "sum")}
    aggregations.update({metric: (metric, "mean") for metric in wanted})
    grouped = performance.groupby("phase").agg(**aggregations).round(1).reset_index()

    from football_stats.body.data_store import PHASE_ORDER

    order = {phase: index for index, phase in enumerate(PHASE_ORDER)}
    return grouped.sort_values("phase", key=lambda s: s.map(order).fillna(99)).reset_index(drop=True)


def coverage(performance: pd.DataFrame) -> dict:
    """How much of the body record actually has training behind it.

    The limiting factor on this whole analysis is usually overlap, not method:
    the body record starts a year before the GPS record, so most assessments
    have no sessions in their lookback window and cannot be paired with
    anything. Reporting that explicitly is the difference between "no
    relationship found" and "no relationship testable", which are opposite
    conclusions.
    """
    if performance.empty:
        return {
            "assessments": 0,
            "paired": 0,
            "shortfall": MIN_PAIRS,
            "analysable": False,
            "well_powered": False,
            "first_paired": None,
        }

    paired = int((performance["sessions_in_window"] > 0).sum())
    return {
        "assessments": len(performance),
        "paired": paired,
        "shortfall": max(0, MIN_PAIRS - paired),
        # Two separate questions, kept apart on purpose: whether the analysis can
        # run at all, and whether its output carries weight. Collapsing them into
        # one "testable" flag is what previously suppressed the entire tab.
        "analysable": paired >= ABSOLUTE_MIN_PAIRS,
        "well_powered": paired >= MIN_PAIRS,
        "first_paired": performance.loc[performance["sessions_in_window"] > 0, "date"].min()
        if paired
        else None,
    }


def paired_observations(
    body: pd.DataFrame,
    performance: pd.DataFrame,
    body_metric: str,
    performance_metric: str,
) -> pd.DataFrame:
    """The actual (body, performance) points behind one pair, for plotting.

    Always available even when the pair is too small to test — looking at six
    points is a legitimate thing to do, as long as nothing calls the line
    through them a result.
    """
    if body.empty or performance.empty:
        return pd.DataFrame(columns=["date", "phase", body_metric, performance_metric])

    merged = body.merge(performance, on="date", suffixes=("", "_perf"))
    columns = [c for c in ["date", "phase", "sessions_in_window"] if c in merged.columns]
    for metric in (body_metric, performance_metric):
        if metric not in merged.columns:
            return pd.DataFrame(columns=columns)
        columns.append(metric)
    return merged[columns].dropna(subset=[body_metric, performance_metric]).reset_index(drop=True)
