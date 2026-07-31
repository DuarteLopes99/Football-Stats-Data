"""GPS performance analysis, ported from ``StatsSports/football_performance_analysis.py``.

The original ``FootballPerformanceAnalyzer`` kept training ("Treinos") and match
("Jogos") data as two separate DataFrames with near-duplicate methods for each.
Here both live in the one tidy ``gps_sessions.csv`` table (see ``gps.data_store``),
distinguished by a ``session_kind`` column, so each analysis is one method
parameterized by ``session_kind`` instead of two near-identical methods. Plot
methods return a ``matplotlib.figure.Figure`` (for ``st.pyplot(fig)``) instead of
calling ``plt.show()``.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

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

METRIC_LABELS = {
    "duration_min": "Duration (min)",
    "total_distance_m": "Total Distance (m)",
    "sprint_distance_m": "Sprint Distance (m)",
    "high_speed_distance_m": "High-Speed Distance (m)",
    "distance_per_min": "Distance per Minute (m/min)",
    "top_speed_kmh": "Top Speed (km/h)",
    "sprints_total": "Sprints (#)",
    "accelerations": "Accelerations (#)",
    "decelerations": "Decelerations (#)",
    "calories": "Calories",
}

BASELINE_METRICS = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh", "accelerations", "decelerations"]

DEFAULT_BASELINE = {
    "total_distance_m": 9000,
    "high_speed_distance_m": 1200,
    "sprint_distance_m": 300,
    "top_speed_kmh": 31,
    "accelerations": 40,
    "decelerations": 40,
}


class PerformanceAnalyzer:
    def __init__(self, sessions: pd.DataFrame, baseline: dict[str, float] | None = None):
        self.sessions = sessions.copy()
        self.sessions["date"] = pd.to_datetime(self.sessions["date"])
        for col in NUMERIC_METRICS:
            self.sessions[col] = pd.to_numeric(self.sessions[col], errors="coerce")
        self.baseline = baseline or DEFAULT_BASELINE

    def _filter(self, session_kind: str, month: int | None = None, year: int | None = None) -> pd.DataFrame:
        df = self.sessions[self.sessions["session_kind"] == session_kind]
        if month is not None:
            df = df[df["month"] == month]
        if year is not None:
            df = df[df["date"].dt.year == year]
        return df

    # --------------------------------------------------------------- #
    # Tabular analyses
    # --------------------------------------------------------------- #

    def monthly_summary(self, session_kind: str, month: int | None = None, year: int | None = None) -> pd.DataFrame:
        df = self._filter(session_kind, month, year)
        if df.empty:
            return pd.DataFrame()
        summary = df.groupby("month").agg(
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
        return summary.reset_index()

    def compare_to_baseline(self, session_kind: str, month: int | None = None) -> pd.DataFrame:
        df = self._filter(session_kind, month)
        if df.empty:
            return pd.DataFrame()
        rows = []
        for col in BASELINE_METRICS:
            current = df[col].max() if col == "top_speed_kmh" else df[col].mean()
            baseline = self.baseline.get(col)
            row = {"Metric": METRIC_LABELS[col], "Current_Avg": round(current, 2), "Baseline": baseline}
            if baseline:
                row["Difference"] = round(current - baseline, 2)
                row["Difference_%"] = round((current - baseline) / baseline * 100, 2)
            rows.append(row)
        return pd.DataFrame(rows)

    def session_type_analysis(self, session_kind: str) -> pd.DataFrame:
        df = self._filter(session_kind)
        session_col = "session_type" if session_kind == "training" else "competition_type"
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

    def weekly_load(self, week: int | None = None, month: int | None = None) -> pd.DataFrame:
        df = self.sessions.copy()
        if week is not None:
            df = df[df["week"] == week]
        if month is not None:
            df = df[df["month"] == month]
        if df.empty:
            return pd.DataFrame()

        metrics = ["duration_min", "total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
        pivot = df.groupby(["week", "session_kind"])[metrics].sum().unstack("session_kind", fill_value=0)
        pivot.columns = [f"{kind}_{metric}" for metric, kind in pivot.columns]
        pivot = pivot.reset_index()

        for metric in metrics:
            training_col, game_col = f"training_{metric}", f"game_{metric}"
            if training_col not in pivot.columns:
                pivot[training_col] = 0.0
            if game_col not in pivot.columns:
                pivot[game_col] = 0.0
            pivot[f"total_{metric}"] = pivot[training_col] + pivot[game_col]

        return pivot.round(2)

    def starter_vs_substitute(self) -> pd.DataFrame:
        df = self._filter("game")
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
        """Composite 0-100 quality score per month, blending training (60%) and match (40%) intensity."""
        weights = weights or {
            "total_distance_m": 0.25,
            "sprint_distance_m": 0.20,
            "high_speed_distance_m": 0.15,
            "top_speed_kmh": 0.15,
            "distance_per_min": 0.15,
            "accelerations": 0.05,
            "decelerations": 0.05,
        }
        training_monthly = self.monthly_summary("training")
        game_monthly = self.monthly_summary("game")

        all_months = sorted(set(training_monthly.get("month", pd.Series(dtype=int))) | set(game_monthly.get("month", pd.Series(dtype=int))))
        rows = []
        for month in all_months:
            row = {"month": month}
            for kind, monthly in (("training_quality", training_monthly), ("match_quality", game_monthly)):
                month_row = monthly[monthly["month"] == month]
                score, total_weight = 0.0, 0.0
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
        return pd.DataFrame(rows)

    # --------------------------------------------------------------- #
    # Charts (return a Figure; caller renders with st.pyplot(fig))
    # --------------------------------------------------------------- #

    def plot_monthly_comparison(self, metrics: list[str] | None = None):
        metrics = metrics or ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
        training_monthly = self.monthly_summary("training")
        game_monthly = self.monthly_summary("game")

        fig, axes = plt.subplots(2, 2, figsize=(14, 9))
        fig.suptitle("Monthly Performance Comparison", fontsize=15, fontweight="bold")
        axes = axes.flatten()

        for idx, metric in enumerate(metrics[:4]):
            ax = axes[idx]
            col = f"{metric}_max" if metric == "top_speed_kmh" else f"{metric}_mean"
            if not training_monthly.empty and col in training_monthly.columns:
                ax.plot(training_monthly["month"], training_monthly[col], marker="o", label="Training", color="#2ecc71")
            if not game_monthly.empty and col in game_monthly.columns:
                ax.plot(game_monthly["month"], game_monthly[col], marker="s", label="Matches", color="#e74c3c")
            ax.set_title(METRIC_LABELS.get(metric, metric), fontsize=11, fontweight="bold")
            ax.set_xlabel("Month")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)

        fig.tight_layout()
        return fig

    def plot_best_worst(self, metric: str = "total_distance_m", session_kind: str = "training", top_n: int = 5):
        df = self._filter(session_kind).dropna(subset=[metric])
        title = "Training Sessions" if session_kind == "training" else "Matches"

        df_sorted = df.sort_values(metric, ascending=False)
        best = df_sorted.head(top_n)
        worst = df_sorted.tail(top_n).sort_values(metric)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"Best & Worst {title} — {METRIC_LABELS.get(metric, metric)}", fontsize=14, fontweight="bold")

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
        weekly = self.weekly_load()
        if weekly.empty:
            return None

        metrics = ["training_total_distance_m", "game_total_distance_m", "training_calories", "game_calories", "total_total_distance_m"]
        metrics = [m for m in metrics if m in weekly.columns]
        heatmap_data = weekly[["week", *metrics]].set_index("week")
        heatmap_data = heatmap_data / heatmap_data.max().replace(0, 1)

        fig, ax = plt.subplots(figsize=(12, 6))
        sns.heatmap(heatmap_data.T, annot=True, fmt=".2f", cmap="YlOrRd", cbar_kws={"label": "Normalized Load"}, ax=ax)
        ax.set_title("Weekly Load Heatmap (Normalized)", fontsize=14, fontweight="bold")
        ax.set_xlabel("Week")
        fig.tight_layout()
        return fig

    def plot_intensity_radar(self):
        metrics = ["distance_per_min", "sprints_total", "top_speed_kmh", "accelerations", "decelerations"]
        training = self._filter("training")
        games = self._filter("game")

        training_means = [training[m].mean() if m in training.columns else 0 for m in metrics]
        game_means = [games[m].mean() if m in games.columns else 0 for m in metrics]
        max_val = max([*training_means, *game_means, 1])
        training_norm = [v / max_val for v in training_means]
        game_norm = [v / max_val for v in game_means]

        angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
        training_norm += training_norm[:1]
        game_norm += game_norm[:1]
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"projection": "polar"})
        ax.plot(angles, training_norm, "o-", linewidth=2, label="Training", color="#2ecc71")
        ax.fill(angles, training_norm, alpha=0.25, color="#2ecc71")
        ax.plot(angles, game_norm, "o-", linewidth=2, label="Matches", color="#e74c3c")
        ax.fill(angles, game_norm, alpha=0.25, color="#e74c3c")
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([METRIC_LABELS[m] for m in metrics], fontsize=9)
        ax.set_title("Intensity: Training vs Matches", fontsize=13, fontweight="bold", pad=20)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
        fig.tight_layout()
        return fig

    def plot_performance_trends(self, metrics: list[str] | None = None):
        metrics = metrics or ["total_distance_m", "sprint_distance_m"]
        training = self._filter("training")
        games = self._filter("game")

        fig, axes = plt.subplots(len(metrics), 1, figsize=(12, 4.5 * len(metrics)))
        axes = [axes] if len(metrics) == 1 else axes
        fig.suptitle("Performance Trends Over Time", fontsize=14, fontweight="bold")

        for ax, metric in zip(axes, metrics):
            if metric in training.columns and not training.empty:
                ax.scatter(training["date"], training[metric], alpha=0.6, label="Training", color="#2ecc71", s=50)
                rolling = training.sort_values("date")[metric].rolling(5, min_periods=1).mean()
                ax.plot(training.sort_values("date")["date"], rolling, color="#27ae60", alpha=0.6, label="Training trend")
            if metric in games.columns and not games.empty:
                ax.scatter(games["date"], games[metric], alpha=0.8, label="Matches", color="#e74c3c", s=80, marker="s")
            ax.set_title(METRIC_LABELS.get(metric, metric), fontsize=11, fontweight="bold")
            ax.legend(fontsize=9)
            ax.grid(alpha=0.3)

        fig.tight_layout()
        return fig

    def plot_quality_evolution(self, weights: dict[str, float] | None = None):
        quality = self.monthly_quality_metric(weights=weights)
        if quality.empty:
            return None

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(quality["month"], quality["training_quality"], marker="o", label="Training Quality", color="#2ecc71")
        ax.plot(quality["month"], quality["match_quality"], marker="s", label="Match Quality", color="#e74c3c")
        ax.plot(quality["month"], quality["combined_quality"], marker="D", linewidth=3, label="Combined Quality", color="#3498db")
        ax.axhspan(80, 100, alpha=0.08, color="green")
        ax.axhspan(60, 80, alpha=0.08, color="orange")
        ax.axhspan(0, 60, alpha=0.08, color="red")
        ax.set_ylim(0, 105)
        ax.set_xlabel("Month")
        ax.set_ylabel("Quality Score (0-100)")
        ax.set_title("Monthly Quality Evolution", fontsize=14, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        return fig
