"""GPS performance analysis, ported from ``StatsSports/football_performance_analysis.py``.

The original ``FootballPerformanceAnalyzer`` kept training ("Treinos") and match
("Jogos") data as two separate DataFrames with near-duplicate methods for each,
and compared "training vs matches" as if every match were the same. Here:

- Every session lives in one table (see ``gps.data_store``), and a derived
  ``match_category`` column splits it three ways — ``"training"``,
  ``"official_match"`` (Campeonato/Taça) and ``"practice_match"`` (a "Jogo
  Treino" friendly) — so lumping a friendly into official-match stats can't
  happen silently.
- Every session also gets a ``season`` label, and monthly aggregation groups on
  the real calendar month, so a season crossing a year boundary still sorts
  chronologically.

Every plot method returns a ``plotly.graph_objects.Figure`` styled with the
report's dark template (``gps.charts``) — the matplotlib/seaborn charts are gone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from football_stats.gps import config as cfg
from football_stats.gps.charts import TEMPLATE
from football_stats.gps.cleaning import match_category
from football_stats.gps.formatting import DISPLAY_LABELS, MATCH_CATEGORY_LABELS
from football_stats.gps.match_link import official_minutes
from football_stats.gps.position_baselines import get_baseline
from football_stats.gps.seasons import add_season_column

NUMERIC_METRICS = [
    "duration_min",
    "total_distance_m",
    "sprint_distance_m",
    "high_speed_distance_m",
    "distance_per_min",
    "top_speed_kmh",
    "sprints_total",
    "accelerations",
    "decelerations",
    "calories",
]

BASELINE_METRICS = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh", "accelerations", "decelerations"]
"""Compared per 90 minutes against a position baseline, except ``top_speed_kmh``
— a peak, not a cumulative rate — which is compared as the scope's session max."""

MATCH_CATEGORIES = cfg.SESSION_CATEGORIES
CATEGORY_COLORS = cfg.SESSION_COLORS

_QUALITY_WEIGHTS_DEFAULT = {
    "total_distance_m": 0.25,
    "sprint_distance_m": 0.20,
    "high_speed_distance_m": 0.15,
    "top_speed_kmh": 0.15,
    "distance_per_min": 0.15,
    "accelerations": 0.05,
    "decelerations": 0.05,
}


def _label(key: str) -> str:
    return DISPLAY_LABELS.get(key, key)


def add_match_category_column(df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``match_category`` column: "training" / "official_match" / "practice_match"."""
    df = df.copy()
    df["match_category"] = match_category(df)
    return df


class PerformanceAnalyzer:
    def __init__(self, sessions: pd.DataFrame):
        self.sessions = sessions.copy()
        self.sessions["date"] = pd.to_datetime(self.sessions["date"])
        for col in NUMERIC_METRICS:
            self.sessions[col] = pd.to_numeric(self.sessions[col], errors="coerce")
        # The export's own distance_per_min disagrees with distance ÷ duration on
        # several rows; recompute it so every chart and score uses one definition.
        duration = self.sessions["duration_min"]
        self.sessions["distance_per_min"] = (self.sessions["total_distance_m"] / duration.where(duration > 0)).round(2)
        self.sessions = add_match_category_column(self.sessions)
        self.sessions = add_season_column(self.sessions)

    def _filter(self, category: str, month: int | None = None, year: int | None = None) -> pd.DataFrame:
        df = self.sessions[self.sessions["match_category"] == category]
        if month is not None:
            df = df[df["month"] == month]
        if year is not None:
            df = df[df["date"].dt.year == year]
        return df

    # --------------------------------------------------------------- #
    # Tabular analyses
    # --------------------------------------------------------------- #

    def monthly_summary(self, category: str, year: int | None = None) -> pd.DataFrame:
        """Chronological monthly aggregation for one match category, grouped on
        the real calendar month so it sorts correctly across a year boundary."""
        df = self._filter(category, year=year)
        if df.empty:
            return pd.DataFrame()
        grouped = df.groupby(pd.Grouper(key="date", freq="MS"))
        summary = grouped.agg(
            {
                "duration_min": ["count", "mean", "sum"],
                "total_distance_m": ["mean", "sum", "max"],
                "sprint_distance_m": ["mean", "sum", "max"],
                "high_speed_distance_m": ["mean", "sum", "max"],
                "distance_per_min": "mean",
                "top_speed_kmh": "max",
                "sprints_total": ["mean", "sum"],
                "accelerations": ["mean", "sum"],
                "decelerations": ["mean", "sum"],
                "calories": ["mean", "sum"],
            }
        ).round(2)
        summary.columns = ["_".join(col).strip() for col in summary.columns.values]
        summary = summary.reset_index()

        # pd.Grouper pads gaps with empty months — drop those by row count.
        session_counts = grouped.size().reset_index(name="_session_count")
        summary = summary.merge(session_counts, on="date")
        summary = summary[summary["_session_count"] > 0].drop(columns="_session_count")

        summary["month_label"] = summary["date"].dt.strftime("%b %Y")
        return summary.reset_index(drop=True)

    def compare_to_baseline(self, category: str, position: str, month: int | None = None) -> pd.DataFrame:
        """Current performance vs. a researched, position-specific baseline.

        Every metric except ``top_speed_kmh`` is compared **per 90 minutes**.
        For matches the denominator is the match-sheet minutes (falling back to
        GPS runtime) and appearances under ``SHORT_APPEARANCE_MIN`` are left out:
        a cameo's per-90 rate is extrapolation, and a few of them used to put
        sprint distance at +264 % of the baseline. ``top_speed_kmh`` is compared
        as this scope's session max.
        """
        df = self._filter(category, month)
        if df.empty:
            return pd.DataFrame()
        df = official_minutes(df)
        minutes = df["official_minutes"]
        if category != cfg.TRAINING:
            df = df[minutes >= cfg.SHORT_APPEARANCE_MIN]
            minutes = df["official_minutes"]
        safe_minutes = minutes.where(minutes > 0)
        baseline = get_baseline(category, position)

        rows = []
        for col in BASELINE_METRICS:
            if col == "top_speed_kmh":
                current = df[col].max()
            else:
                current = (df[col] / safe_minutes * 90).mean()
            ref = baseline.get(col)
            row = {"Metric": _label(col), "Current": round(current, 2) if pd.notna(current) else None, "Baseline": ref}
            if ref:
                row["Difference"] = round(current - ref, 2) if pd.notna(current) else None
                row["Difference_%"] = round((current - ref) / ref * 100, 2) if pd.notna(current) else None
            rows.append(row)
        return pd.DataFrame(rows)

    def average_minutes(self, category: str) -> float:
        """Average ``duration_min`` for one match category (sessions with minutes only)."""
        df = self._filter(category)
        minutes = df["duration_min"].where(df["duration_min"] > 0)
        if minutes.dropna().empty:
            return float("nan")
        return round(float(minutes.mean()), 1)

    def session_type_analysis(self, category: str) -> pd.DataFrame:
        df = self._filter(category)
        session_col = "session_type" if category == "training" else "competition_type"
        df = df[df[session_col].notna()]
        if df.empty:
            return pd.DataFrame()
        stats = df.groupby(session_col).agg(
            {
                "duration_min": ["count", "mean"],
                "total_distance_m": "mean",
                "sprint_distance_m": "mean",
                "high_speed_distance_m": "mean",
                "distance_per_min": "mean",
                "top_speed_kmh": "max",
                "sprints_total": "mean",
                "accelerations": "mean",
                "decelerations": "mean",
                "calories": "mean",
            }
        ).round(2)
        stats.columns = ["_".join(col).strip() for col in stats.columns.values]
        return stats.reset_index()

    def weekly_load(self, week: int | None = None) -> pd.DataFrame:
        """Weekly load split by match category, on Sunday→Saturday calendar weeks
        (``gps.config.WEEK_FREQ``) — computed from the dates, not the hand-typed
        ``week`` column, so it never merges two seasons' "week 5" together.
        ``week`` filters by that column for backward compatibility.
        """
        df = self.sessions.copy()
        if week is not None:
            df = df[df["week"] == week]
        if df.empty:
            return pd.DataFrame()

        metrics = ["duration_min", "total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
        df["week_start"] = (df["date"] - pd.to_timedelta((df["date"].dt.dayofweek + 1) % 7, unit="D")).dt.normalize()
        pivot = df.groupby(["week_start", "match_category"])[metrics].sum().unstack("match_category", fill_value=0)
        pivot.columns = [f"{category}_{metric}" for metric, category in pivot.columns]
        pivot = pivot.reset_index()

        for metric in metrics:
            for category in MATCH_CATEGORIES:
                col = f"{category}_{metric}"
                if col not in pivot.columns:
                    pivot[col] = 0.0
            pivot[f"total_{metric}"] = sum(pivot[f"{category}_{metric}"] for category in MATCH_CATEGORIES)

        pivot.insert(0, "week", pivot["week_start"].dt.strftime("%d %b %Y"))
        return pivot.drop(columns="week_start").round(2)

    def starter_vs_substitute(self) -> pd.DataFrame:
        """Starter vs substitute across all games that were actually played —
        an unused substitute's 0 minutes would otherwise drag every sub mean down."""
        df = self.sessions[self.sessions["session_kind"] == "game"]
        df = df[df["was_starter"].notna() & (df["duration_min"] > 0)]
        if df.empty:
            return pd.DataFrame()
        stats = df.groupby("was_starter").agg(
            {
                "duration_min": ["count", "mean"],
                "total_distance_m": "mean",
                "sprint_distance_m": "mean",
                "high_speed_distance_m": "mean",
                "top_speed_kmh": "max",
            }
        ).round(2)
        stats.columns = ["_".join(col).strip() for col in stats.columns.values]
        stats = stats.reset_index()
        stats["was_starter"] = stats["was_starter"].map({True: "Starter", False: "Substitute", "True": "Starter", "False": "Substitute"})
        return stats

    QUALITY_COLUMNS = ["date", "month_label", "training_quality", "match_quality", "combined_quality"]

    def monthly_quality_metric(self, weights: dict[str, float] | None = None) -> pd.DataFrame:
        """Composite 0-100 quality score per calendar month, blending training
        and official-match intensity (``QUALITY_TRAINING_WEIGHT`` /
        ``QUALITY_MATCH_WEIGHT``). Practice matches don't factor in.

        A month without measurable official-match data has **no** match score
        (NaN), and its combined score is the training score alone — it used to
        count as 0 and knock 40 % off the month (Dec 2025 read 54.8).
        Empty-but-typed when there are no sessions in scope.
        """
        weights = weights or _QUALITY_WEIGHTS_DEFAULT
        training_monthly = self.monthly_summary("training")
        official_monthly = self.monthly_summary("official_match")

        all_dates = sorted(
            set(training_monthly.get("date", pd.Series(dtype="datetime64[ns]")))
            | set(official_monthly.get("date", pd.Series(dtype="datetime64[ns]")))
        )
        rows = []
        for date in all_dates:
            row = {"date": date, "month_label": date.strftime("%b %Y")}
            for kind, monthly in (("training_quality", training_monthly), ("match_quality", official_monthly)):
                score, total_weight = 0.0, 0.0
                month_row = monthly[monthly["date"] == date] if not monthly.empty else monthly
                if not month_row.empty:
                    month_row = month_row.iloc[0]
                    for metric, weight in weights.items():
                        col = f"{metric}_max" if metric == "top_speed_kmh" else f"{metric}_mean"
                        if col in month_row.index and pd.notna(month_row[col]):
                            reference = monthly[col].dropna()
                            if len(reference) and reference.max() > 0:
                                score += (month_row[col] / reference.max()) * weight
                                total_weight += weight
                row[kind] = round((score / total_weight) * 100, 2) if total_weight else np.nan
            parts = [(row["training_quality"], cfg.QUALITY_TRAINING_WEIGHT), (row["match_quality"], cfg.QUALITY_MATCH_WEIGHT)]
            parts = [(v, w) for v, w in parts if pd.notna(v)]
            row["combined_quality"] = round(sum(v * w for v, w in parts) / sum(w for _, w in parts), 2) if parts else np.nan
            rows.append(row)
        if not rows:
            return pd.DataFrame(columns=self.QUALITY_COLUMNS)
        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    SEASON_SUMMARY_COLUMNS = [
        "season", "total_sessions", "training_sessions", "official_matches", "practice_matches",
        "total_distance_km", "peak_top_speed_kmh", "avg_quality_score",
    ]

    def season_summary(self) -> pd.DataFrame:
        """One row per season: session counts by category, distance, peak speed
        (any session type), quality. Empty-but-typed when nothing is in scope."""
        rows = []
        for season, group in self.sessions.groupby("season"):
            quality = PerformanceAnalyzer(group).monthly_quality_metric()
            rows.append(
                {
                    "season": season,
                    "total_sessions": len(group),
                    "training_sessions": int((group["match_category"] == "training").sum()),
                    "official_matches": int((group["match_category"] == "official_match").sum()),
                    "practice_matches": int((group["match_category"] == "practice_match").sum()),
                    "total_distance_km": round(group["total_distance_m"].sum() / 1000, 1),
                    "peak_top_speed_kmh": round(group["top_speed_kmh"].max(), 2) if group["top_speed_kmh"].notna().any() else None,
                    "avg_quality_score": round(quality["combined_quality"].mean(), 1) if not quality.empty else None,
                }
            )
        if not rows:
            return pd.DataFrame(columns=self.SEASON_SUMMARY_COLUMNS)
        return pd.DataFrame(rows).sort_values("season").reset_index(drop=True)

    # --------------------------------------------------------------- #
    # Charts (Plotly, dark report template)
    # --------------------------------------------------------------- #

    def plot_monthly_comparison(self, metrics: list[str] | None = None) -> go.Figure:
        metrics = metrics or ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
        metrics = metrics[:4]
        monthly_by_category = {category: self.monthly_summary(category) for category in MATCH_CATEGORIES}
        fig = make_subplots(rows=2, cols=2, subplot_titles=[_label(m) for m in metrics], vertical_spacing=0.14)
        for idx, metric in enumerate(metrics):
            col = f"{metric}_max" if metric == "top_speed_kmh" else f"{metric}_mean"
            for category, monthly in monthly_by_category.items():
                if monthly.empty or col not in monthly.columns:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=monthly["date"], y=monthly[col], mode="lines+markers", name=MATCH_CATEGORY_LABELS[category],
                        line={"color": CATEGORY_COLORS[category], "width": 2}, marker={"size": 8},
                        legendgroup=category, showlegend=idx == 0,
                        hovertemplate=f"%{{x|%b %Y}}<br>{_label(metric)}: %{{y:,.0f}}<extra>{MATCH_CATEGORY_LABELS[category]}</extra>",
                    ),
                    row=idx // 2 + 1, col=idx % 2 + 1,
                )
        fig.update_xaxes(tickformat="%b %y")
        fig.update_layout(template=TEMPLATE, height=580, margin={"t": 80}, legend={"y": 1.12})
        return fig

    def plot_best_worst(self, metric: str = "total_distance_m", category: str = "training", top_n: int = 5) -> go.Figure:
        df = self._filter(category).dropna(subset=[metric])
        df = df[df[metric] > 0]
        title = MATCH_CATEGORY_LABELS.get(category, category)
        ordered = df.sort_values(metric, ascending=False)
        best, worst = ordered.head(top_n), ordered.tail(top_n).sort_values(metric)
        fig = make_subplots(rows=1, cols=2, subplot_titles=[f"Top {top_n}", f"Bottom {top_n}"], horizontal_spacing=0.18)
        for col_idx, data in ((1, best), (2, worst)):
            fig.add_trace(
                go.Bar(
                    x=data[metric], y=data["date"].dt.strftime("%d %b %y"), orientation="h",
                    marker={"color": CATEGORY_COLORS.get(category, cfg.GAUGE["fill"]), "cornerradius": 3},
                    text=data[metric].round(0), textposition="outside", textfont={"color": cfg.THEME["text_secondary"]},
                    hovertemplate=f"%{{y}}: %{{x:,.1f}}<extra>{title}</extra>", showlegend=False, cliponaxis=False,
                ),
                row=1, col=col_idx,
            )
            fig.update_yaxes(autorange="reversed", type="category", row=1, col=col_idx)
        fig.update_layout(template=TEMPLATE, height=360, margin={"t": 50})
        return fig

    def plot_weekly_load_heatmap(self) -> go.Figure | None:
        """Weekly load by category as a heatmap (colour = share of that row's
        maximum; hover shows the raw value)."""
        weekly = self.weekly_load()
        if weekly.empty:
            return None

        metrics = [f"{cat}_total_distance_m" for cat in MATCH_CATEGORIES] + ["total_calories", "total_total_distance_m"]
        metrics = [m for m in metrics if m in weekly.columns]
        raw = weekly[["week", *metrics]].set_index("week")
        normalized = raw / raw.max().replace(0, 1)
        row_labels = [_humanize_short(c) for c in raw.columns]

        fig = go.Figure(
            go.Heatmap(
                z=normalized.T.to_numpy(), x=raw.index.astype(str), y=row_labels,
                customdata=raw.T.round(1).to_numpy(),
                colorscale=[[i / (len(cfg.DEMAND_SEQUENTIAL) - 1), c] for i, c in enumerate(cfg.DEMAND_SEQUENTIAL)],
                colorbar={"title": "Share of max", "tickformat": ".0%"}, xgap=2, ygap=2,
                hovertemplate="Week of %{x}<br>%{y}: %{customdata:,.0f}<extra></extra>",
            )
        )
        fig.update_layout(template=TEMPLATE, title="Weekly load (colour = share of the row's busiest week)",
                          xaxis={"type": "category", "title": "Week starting"}, height=340, margin={"l": 150})
        return fig

    def plot_intensity_radar(self) -> go.Figure:
        """Mean intensity by category. Each axis is scaled to its own maximum —
        a single shared maximum squashed sprints and accelerations against m/min."""
        metrics = ["distance_per_min", "sprints_total", "top_speed_kmh", "accelerations", "decelerations"]
        means = pd.DataFrame(
            {category: [self._filter(category)[m].mean() for m in metrics] for category in MATCH_CATEGORIES},
            index=metrics,
        )
        scaled = means.div(means.max(axis=1).replace(0, np.nan), axis=0)
        labels = [_label(m) for m in metrics]
        fig = go.Figure()
        for category in MATCH_CATEGORIES:
            if means[category].isna().all():
                continue
            fig.add_trace(
                go.Scatterpolar(
                    r=list(scaled[category]) + [scaled[category].iloc[0]], theta=labels + [labels[0]],
                    name=MATCH_CATEGORY_LABELS[category], line={"color": CATEGORY_COLORS[category], "width": 2},
                    fill="toself", opacity=0.75,
                    customdata=list(means[category].round(1)) + [round(means[category].iloc[0], 1)],
                    hovertemplate="%{theta}: %{customdata}<extra>" + MATCH_CATEGORY_LABELS[category] + "</extra>",
                )
            )
        fig.update_layout(
            template=TEMPLATE, height=460, margin={"t": 60}, legend={"y": 1.1},
            polar={"bgcolor": cfg.THEME["surface"], "radialaxis": {"range": [0, 1], "showticklabels": False, "gridcolor": cfg.THEME["grid"]},
                   "angularaxis": {"gridcolor": cfg.THEME["grid"], "linecolor": cfg.THEME["axis"]}},
        )
        return fig

    def plot_performance_trends(self, metrics: list[str] | None = None) -> go.Figure:
        metrics = metrics or ["total_distance_m", "sprint_distance_m"]
        fig = make_subplots(rows=len(metrics), cols=1, shared_xaxes=True, subplot_titles=[_label(m) for m in metrics], vertical_spacing=0.08)
        for row, metric in enumerate(metrics, start=1):
            for category in MATCH_CATEGORIES:
                df = self._filter(category).dropna(subset=[metric])
                if df.empty:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=df["date"], y=df[metric], mode="markers", name=MATCH_CATEGORY_LABELS[category],
                        marker={"color": CATEGORY_COLORS[category], "size": 8, "line": {"color": cfg.THEME["surface"], "width": 1}},
                        legendgroup=category, showlegend=row == 1,
                        hovertemplate=f"%{{x|%d %b %Y}}: %{{y:,.1f}}<extra>{MATCH_CATEGORY_LABELS[category]}</extra>",
                    ),
                    row=row, col=1,
                )
            training = self._filter("training").dropna(subset=[metric]).sort_values("date")
            if not training.empty:
                fig.add_trace(
                    go.Scatter(
                        x=training["date"], y=training[metric].rolling(5, min_periods=1).mean(), mode="lines",
                        name="Training, 5-session mean", line={"color": CATEGORY_COLORS["training"], "width": 2, "dash": "dot"},
                        legendgroup="trend", showlegend=row == 1, hoverinfo="skip",
                    ),
                    row=row, col=1,
                )
        fig.update_layout(template=TEMPLATE, height=320 * len(metrics), margin={"t": 80}, legend={"y": 1.0 + 0.12 / len(metrics)})
        return fig

    def plot_quality_evolution(self, weights: dict[str, float] | None = None) -> go.Figure | None:
        quality = self.monthly_quality_metric(weights=weights)
        if quality.empty:
            return None
        fig = go.Figure()
        for column, name, color, width in (
            ("training_quality", "Training", CATEGORY_COLORS["training"], 2),
            ("match_quality", "Official match", CATEGORY_COLORS["official_match"], 2),
            ("combined_quality", "Combined", cfg.THEME["text"], 3),
        ):
            fig.add_trace(go.Scatter(x=quality["date"], y=quality[column], mode="lines+markers", name=name,
                                     line={"color": color, "width": width}, marker={"size": 8}, connectgaps=False,
                                     hovertemplate=f"%{{x|%b %Y}}: %{{y:.1f}}<extra>{name}</extra>"))
        fig.update_layout(template=TEMPLATE, height=400, yaxis={"range": [0, 105], "title": "Quality score (0–100)"},
                          xaxis={"tickformat": "%b %y"})
        return fig


def _humanize_short(col: str) -> str:
    for category in MATCH_CATEGORIES:
        if col == f"{category}_total_distance_m":
            return MATCH_CATEGORY_LABELS[category]
    if col == "total_calories":
        return "Overall Calories"
    if col == "total_total_distance_m":
        return "Overall Distance"
    return col
