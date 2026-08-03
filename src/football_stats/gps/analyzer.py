"""GPS performance analysis, ported from ``StatsSports/football_performance_analysis.py``.

The original ``FootballPerformanceAnalyzer`` kept training ("Treinos") and match
("Jogos") data as two separate DataFrames with near-duplicate methods for each,
and compared "training vs matches" as if every match were the same. Here:

- Every session lives in one table (see ``gps.data_store``), and a derived
  ``match_category`` column splits it three ways — ``"training"``,
  ``"official_match"`` (Campeonato/Taça) and ``"practice_match"`` (a "Jogo
  Treino" friendly, which is a `session_kind == "game"` row but not a real
  competitive fixture) — so lumping a friendly into official-match stats can't
  happen silently.
- Every session also gets a ``season`` label (``gps.seasons.season_label``, a
  Jul-Jun football season), and monthly aggregation groups on the actual
  calendar date (``pd.Grouper(freq="MS")``) instead of a bare 1-12 month
  number, so a season that crosses a calendar-year boundary (Sep 2025 -> May
  2026) still sorts and displays chronologically instead of Jan-before-Sep.

Plot methods return a ``matplotlib.figure.Figure`` (for ``st.pyplot(fig)``)
instead of calling ``plt.show()`` — except ``plot_weekly_load_heatmap``, which
returns a ``plotly.graph_objects.Figure`` (for ``st.plotly_chart(fig)``): a
season can span 30+ weeks, and cramming an on-cell number into that many
narrow matplotlib columns made the text unreadable regardless of font size.
Plotly's hover tooltip replaces the on-cell annotation instead.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import seaborn as sns

from football_stats.gps.formatting import DISPLAY_LABELS, MATCH_CATEGORY_LABELS
from football_stats.gps.seasons import add_season_column

sns.set_style("whitegrid")

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

DEFAULT_BASELINE = {
    "total_distance_m": 9000,
    "high_speed_distance_m": 1200,
    "sprint_distance_m": 300,
    "top_speed_kmh": 31,
    "accelerations": 40,
    "decelerations": 40,
}

MATCH_CATEGORIES = ["training", "official_match", "practice_match"]
CATEGORY_COLORS = {"training": "#2ecc71", "official_match": "#e74c3c", "practice_match": "#f39c12"}
CATEGORY_MARKERS = {"training": "o", "official_match": "s", "practice_match": "^"}

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
    """Add a ``match_category`` column: "training" / "official_match" / "practice_match".

    Public so callers (the dashboard) can filter on it before ever constructing
    a ``PerformanceAnalyzer`` — the same pattern already used for `date`/`season`.
    """
    df = df.copy()
    competition_type = df.get("competition_type", pd.Series(index=df.index))
    is_official = competition_type.isin(["Campeonato", "Taça"])
    df["match_category"] = np.select(
        [df["session_kind"] == "training", is_official],
        ["training", "official_match"],
        default="practice_match",
    )
    return df


class PerformanceAnalyzer:
    def __init__(self, sessions: pd.DataFrame, baseline: dict[str, float] | None = None):
        self.sessions = sessions.copy()
        self.sessions["date"] = pd.to_datetime(self.sessions["date"])
        for col in NUMERIC_METRICS:
            self.sessions[col] = pd.to_numeric(self.sessions[col], errors="coerce")
        self.sessions = add_match_category_column(self.sessions)
        self.sessions = add_season_column(self.sessions)
        self.baseline = baseline or DEFAULT_BASELINE

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
        """Chronological monthly aggregation for one match category.

        Grouped on the real calendar month (``pd.Grouper(freq="MS")``), not the
        bare 1-12 month number, so a season spanning a calendar-year boundary
        (or multiple seasons at once) still sorts and reads chronologically.
        """
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

        # pd.Grouper(freq="MS") pads gaps between the first and last session with
        # empty months — drop those (by actual row count, not duration_min_count,
        # since a real session missing just its duration shouldn't disappear too).
        session_counts = grouped.size().reset_index(name="_session_count")
        summary = summary.merge(session_counts, on="date")
        summary = summary[summary["_session_count"] > 0].drop(columns="_session_count")

        summary["month_label"] = summary["date"].dt.strftime("%b %Y")
        return summary.reset_index(drop=True)

    def compare_to_baseline(self, category: str, month: int | None = None) -> pd.DataFrame:
        df = self._filter(category, month)
        if df.empty:
            return pd.DataFrame()
        rows = []
        for col in BASELINE_METRICS:
            current = df[col].max() if col == "top_speed_kmh" else df[col].mean()
            baseline = self.baseline.get(col)
            row = {"Metric": _label(col), "Current_Avg": round(current, 2), "Baseline": baseline}
            if baseline:
                row["Difference"] = round(current - baseline, 2)
                row["Difference_%"] = round((current - baseline) / baseline * 100, 2)
            rows.append(row)
        return pd.DataFrame(rows)

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
        """Weekly load split by match category.

        ``week`` is a season-relative counter in the source data (it restarts
        at 1 each season), so this only produces meaningful totals when
        ``self.sessions`` is already scoped to a single season — the dashboard
        enforces that via its season selector before constructing the analyzer.
        """
        df = self.sessions.copy()
        if week is not None:
            df = df[df["week"] == week]
        if df.empty:
            return pd.DataFrame()

        metrics = ["duration_min", "total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
        pivot = df.groupby(["week", "match_category"])[metrics].sum().unstack("match_category", fill_value=0)
        pivot.columns = [f"{category}_{metric}" for metric, category in pivot.columns]
        pivot = pivot.reset_index()

        for metric in metrics:
            for category in MATCH_CATEGORIES:
                col = f"{category}_{metric}"
                if col not in pivot.columns:
                    pivot[col] = 0.0
            pivot[f"total_{metric}"] = sum(pivot[f"{category}_{metric}"] for category in MATCH_CATEGORIES)

        pivot["week"] = pivot["week"].astype(int)
        return pivot.round(2)

    def starter_vs_substitute(self) -> pd.DataFrame:
        """Starter vs substitute performance across all games (official + practice)."""
        df = self.sessions[self.sessions["session_kind"] == "game"]
        df = df[df["was_starter"].notna()]
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
        stats["was_starter"] = stats["was_starter"].map({True: "Starter", False: "Substitute"})
        return stats

    def monthly_quality_metric(self, weights: dict[str, float] | None = None) -> pd.DataFrame:
        """Composite 0-100 quality score per calendar month, blending training
        (60%) and official-match (40%) intensity. Practice matches don't factor
        in — they're not a reliable read on competitive readiness.
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
                row[kind] = round((score / total_weight) * 100, 2) if total_weight else 0.0
            row["combined_quality"] = round(0.6 * row["training_quality"] + 0.4 * row["match_quality"], 2)
            rows.append(row)
        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    def season_summary(self) -> pd.DataFrame:
        """One row per season: session counts by category, distance, peak speed, quality."""
        rows = []
        for season, group in self.sessions.groupby("season"):
            quality = PerformanceAnalyzer(group).monthly_quality_metric()
            official = group[group["match_category"] == "official_match"]
            rows.append(
                {
                    "season": season,
                    "total_sessions": len(group),
                    "training_sessions": int((group["match_category"] == "training").sum()),
                    "official_matches": int((group["match_category"] == "official_match").sum()),
                    "practice_matches": int((group["match_category"] == "practice_match").sum()),
                    "total_distance_km": round(group["total_distance_m"].sum() / 1000, 1),
                    "peak_top_speed_kmh": round(official["top_speed_kmh"].max(), 2) if not official.empty else None,
                    "avg_quality_score": round(quality["combined_quality"].mean(), 1) if not quality.empty else None,
                }
            )
        return pd.DataFrame(rows).sort_values("season").reset_index(drop=True)

    # --------------------------------------------------------------- #
    # Charts (return a Figure; caller renders with st.pyplot(fig))
    # --------------------------------------------------------------- #

    def plot_monthly_comparison(self, metrics: list[str] | None = None):
        metrics = metrics or ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
        monthly_by_category = {category: self.monthly_summary(category) for category in MATCH_CATEGORIES}

        fig, axes = plt.subplots(2, 2, figsize=(14, 9))
        fig.suptitle("Monthly Performance Comparison", fontsize=15, fontweight="bold")
        axes = axes.flatten()

        for idx, metric in enumerate(metrics[:4]):
            ax = axes[idx]
            col = f"{metric}_max" if metric == "top_speed_kmh" else f"{metric}_mean"
            for category, monthly in monthly_by_category.items():
                if not monthly.empty and col in monthly.columns:
                    ax.plot(
                        monthly["date"],
                        monthly[col],
                        marker=CATEGORY_MARKERS[category],
                        label=MATCH_CATEGORY_LABELS[category],
                        color=CATEGORY_COLORS[category],
                    )
            ax.set_title(_label(metric), fontsize=11, fontweight="bold")
            ax.set_xlabel("Month")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)
            ax.tick_params(axis="x", rotation=45)

        fig.tight_layout()
        return fig

    def plot_best_worst(self, metric: str = "total_distance_m", category: str = "training", top_n: int = 5):
        df = self._filter(category).dropna(subset=[metric])
        title = MATCH_CATEGORY_LABELS.get(category, category)

        df_sorted = df.sort_values(metric, ascending=False)
        best = df_sorted.head(top_n)
        worst = df_sorted.tail(top_n).sort_values(metric)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"Best & Worst {title} — {_label(metric)}", fontsize=14, fontweight="bold")

        for ax, data, cmap, label in ((ax1, best, plt.cm.Greens, "Best"), (ax2, worst, plt.cm.Reds, "Worst")):
            dates = data["date"].dt.strftime("%d/%m/%y")
            values = data[metric].values
            colors = cmap(np.linspace(0.5, 0.9, max(len(values), 1)))
            ax.barh(range(len(dates)), values, color=colors)
            ax.set_yticks(range(len(dates)))
            ax.set_yticklabels(dates)
            ax.invert_yaxis()
            ax.set_title(f"Top {top_n} {label}", fontsize=11, fontweight="bold")
            for i, val in enumerate(values):
                ax.text(val, i, f"  {val:.0f}", va="center", fontsize=9)

        fig.tight_layout()
        return fig

    def plot_weekly_load_heatmap(self):
        """Interactive Plotly heatmap — the one chart method that isn't
        matplotlib (see the module docstring). A season can span 30+ weeks;
        cramming an on-cell number into each of 30+ narrow matplotlib columns
        made the text overlap and become unreadable regardless of font size.
        Plotly's hover tooltip shows the exact raw value instead, so no
        on-cell text is needed at all.
        """
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
                z=normalized.T.to_numpy(),
                x=raw.index.astype(str),
                y=row_labels,
                customdata=raw.T.round(1).to_numpy(),
                colorscale="YlOrRd",
                colorbar={"title": "Normalized"},
                hovertemplate="Week %{x}<br>%{y}: %{customdata}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Weekly Load Heatmap (color = normalized load; hover for the raw value)",
            xaxis_title="Week",
            xaxis={"type": "category"},
            margin={"l": 140, "r": 20, "t": 50, "b": 40},
            height=320,
        )
        return fig

    def plot_intensity_radar(self):
        metrics = ["distance_per_min", "sprints_total", "top_speed_kmh", "accelerations", "decelerations"]
        means_by_category = {}
        for category in MATCH_CATEGORIES:
            df = self._filter(category)
            means_by_category[category] = [df[m].mean() if m in df.columns and not df.empty else 0 for m in metrics]

        max_val = max([*(v for values in means_by_category.values() for v in values), 1])
        norm_by_category = {cat: [v / max_val for v in values] for cat, values in means_by_category.items()}

        angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"projection": "polar"})
        for category, norm in norm_by_category.items():
            values = norm + norm[:1]
            ax.plot(angles, values, "o-", linewidth=2, label=MATCH_CATEGORY_LABELS[category], color=CATEGORY_COLORS[category])
            ax.fill(angles, values, alpha=0.2, color=CATEGORY_COLORS[category])

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([_label(m) for m in metrics], fontsize=9)
        ax.set_title("Intensity: Training vs Official vs Practice", fontsize=13, fontweight="bold", pad=20)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
        fig.tight_layout()
        return fig

    def plot_performance_trends(self, metrics: list[str] | None = None):
        metrics = metrics or ["total_distance_m", "sprint_distance_m"]
        by_category = {category: self._filter(category) for category in MATCH_CATEGORIES}

        fig, axes = plt.subplots(len(metrics), 1, figsize=(12, 4.5 * len(metrics)))
        axes = [axes] if len(metrics) == 1 else axes
        fig.suptitle("Performance Trends Over Time", fontsize=14, fontweight="bold")

        for ax, metric in zip(axes, metrics):
            for category, df in by_category.items():
                if metric in df.columns and not df.empty:
                    marker = "o" if category == "training" else CATEGORY_MARKERS[category]
                    size = 50 if category == "training" else 80
                    alpha = 0.6 if category == "training" else 0.85
                    ax.scatter(
                        df["date"], df[metric], alpha=alpha, label=MATCH_CATEGORY_LABELS[category],
                        color=CATEGORY_COLORS[category], s=size, marker=marker,
                    )
            training = by_category["training"]
            if metric in training.columns and not training.empty:
                training_sorted = training.sort_values("date")
                rolling = training_sorted[metric].rolling(5, min_periods=1).mean()
                ax.plot(training_sorted["date"], rolling, color="#27ae60", alpha=0.6, label="Training trend")
            ax.set_title(_label(metric), fontsize=11, fontweight="bold")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)

        fig.tight_layout()
        return fig

    def plot_quality_evolution(self, weights: dict[str, float] | None = None):
        quality = self.monthly_quality_metric(weights=weights)
        if quality.empty:
            return None

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(quality["date"], quality["training_quality"], marker="o", label="Training Quality", color=CATEGORY_COLORS["training"])
        ax.plot(quality["date"], quality["match_quality"], marker="s", label="Official Match Quality", color=CATEGORY_COLORS["official_match"])
        ax.plot(quality["date"], quality["combined_quality"], marker="D", linewidth=3, label="Combined Quality", color="#3498db")
        ax.axhspan(80, 100, alpha=0.08, color="green")
        ax.axhspan(60, 80, alpha=0.08, color="orange")
        ax.axhspan(0, 60, alpha=0.08, color="red")
        ax.set_ylim(0, 105)
        ax.set_xlabel("Month")
        ax.set_ylabel("Quality Score (0-100)")
        ax.set_title("Monthly Quality Evolution", fontsize=14, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
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
