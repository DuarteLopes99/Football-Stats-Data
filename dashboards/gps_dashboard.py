"""Streamlit dashboard: GPS training/match performance analysis.

Run with:
    streamlit run dashboards/gps_dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_stats.gps.analyzer import MATCH_CATEGORIES, PerformanceAnalyzer, add_match_category_column  # noqa: E402
from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, append_session, load_sessions  # noqa: E402
from football_stats.gps.formatting import DISPLAY_LABELS, MATCH_CATEGORY_LABELS, humanize_columns, numeric_column_config  # noqa: E402
from football_stats.gps.gauges import acwr_gauge, intensity_gauge, percentile_gauge, quality_gauge, top_speed_gauge  # noqa: E402
from football_stats.gps.seasons import add_season_column  # noqa: E402
from football_stats.gps.skillcorner_metrics import (  # noqa: E402
    PER90_METRICS,
    add_intensity_ratios,
    add_per90_columns,
    classify_acwr,
    compute_acwr,
    percentile_rank,
    robust_top_speed,
)

st.set_page_config(page_title="GPS Performance", page_icon="🏃", layout="wide")

ALL_SEASONS = "All seasons"
WEEKLY_METRICS = ["duration_min", "total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
WEEKLY_GROUPS = [
    ("training", "Training"),
    ("official_match", "Official Matches"),
    ("practice_match", "Practice Matches"),
    ("total", "Overall (All Categories)"),
]


@st.cache_data
def _load() -> pd.DataFrame:
    sessions = load_sessions(DEFAULT_SESSIONS_PATH)
    if sessions.empty:
        return sessions
    sessions = add_match_category_column(sessions)
    sessions = add_season_column(sessions)
    return sessions


def _show_table(df: pd.DataFrame) -> None:
    display = humanize_columns(df)
    st.dataframe(display, use_container_width=True, hide_index=True, column_config=numeric_column_config(display))


def _metric_label(metric: str) -> str:
    return DISPLAY_LABELS.get(metric, metric)


def _add_session_form() -> None:
    st.subheader("Add a new session")
    with st.form("add_session", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            date = st.date_input("Date")
            session_kind = st.selectbox("Session kind", ["training", "game"])
            session_type = st.text_input("Session type / label", placeholder="e.g. Treino Terça-Feira")
        with col2:
            duration_min = st.number_input("Duration (min)", min_value=0.0, step=1.0)
            total_distance_m = st.number_input("Total distance (m)", min_value=0.0, step=10.0)
            sprint_distance_m = st.number_input("Sprint distance (m)", min_value=0.0, step=10.0)
            high_speed_distance_m = st.number_input("High-speed distance (m)", min_value=0.0, step=10.0)
        with col3:
            top_speed_kmh = st.number_input("Top speed (km/h)", min_value=0.0, step=0.1)
            sprints_total = st.number_input("Sprints (#)", min_value=0.0, step=1.0)
            accelerations = st.number_input("Accelerations (#)", min_value=0.0, step=1.0)
            decelerations = st.number_input("Decelerations (#)", min_value=0.0, step=1.0)

        calories = st.number_input("Calories", min_value=0.0, step=10.0)

        competition_type, was_starter = None, None
        if session_kind == "game":
            st.caption("Competition type decides whether this counts as an official match or a practice match in the analysis.")
            gcol1, gcol2 = st.columns(2)
            with gcol1:
                competition_type = st.selectbox("Competition type", ["Campeonato", "Taça", "Treino"])
            with gcol2:
                was_starter = st.checkbox("Started the match", value=True)

        notes = st.text_area("Notes", placeholder="Optional")
        submitted = st.form_submit_button("Add session")

        if submitted:
            append_session(
                {
                    "date": str(date),
                    "session_kind": session_kind,
                    "session_type": session_type or None,
                    "duration_min": duration_min or None,
                    "total_distance_m": total_distance_m or None,
                    "sprint_distance_m": sprint_distance_m or None,
                    "high_speed_distance_m": high_speed_distance_m or None,
                    "top_speed_kmh": top_speed_kmh or None,
                    "sprints_total": sprints_total or None,
                    "accelerations": accelerations or None,
                    "decelerations": decelerations or None,
                    "calories": calories or None,
                    "competition_type": competition_type,
                    "was_starter": was_starter,
                    "notes": notes or None,
                },
                path=DEFAULT_SESSIONS_PATH,
            )
            st.cache_data.clear()
            st.success("Session added.")
            st.rerun()


def main() -> None:
    st.title("🏃 GPS Performance Analysis")

    sessions = _load()
    if sessions.empty:
        st.warning("No GPS sessions found yet. Add one below to get started.")
        _add_session_form()
        return

    seasons = sorted(sessions["season"].unique())
    season_choice = st.sidebar.selectbox("Season", [ALL_SEASONS, *seasons])

    categories = st.sidebar.multiselect(
        "Match category",
        MATCH_CATEGORIES,
        default=MATCH_CATEGORIES,
        format_func=lambda c: MATCH_CATEGORY_LABELS[c],
    )

    min_date, max_date = sessions["date"].min().date(), sessions["date"].max().date()
    date_range = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)

    category_scope = sessions[sessions["match_category"].isin(categories)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        category_scope = category_scope[(category_scope["date"] >= pd.Timestamp(start)) & (category_scope["date"] <= pd.Timestamp(end))]

    filtered = category_scope if season_choice == ALL_SEASONS else category_scope[category_scope["season"] == season_choice]

    analyzer = PerformanceAnalyzer(filtered)
    # Season Summary always reflects every season in scope, regardless of the Season selector above.
    overall_analyzer = PerformanceAnalyzer(category_scope)

    tabs = st.tabs(
        [
            "Overview",
            "Monthly",
            "Weekly Load",
            "Intensity",
            "Trends",
            "Baseline",
            "Quality",
            "Season Summary",
            "Performance Insights",
            "Add Session",
        ]
    )

    with tabs[0]:
        st.subheader("Sessions")
        _show_table(filtered.sort_values("date", ascending=False))
        col1, col2, col3 = st.columns(3)
        col1.metric("Total sessions", len(filtered))
        col2.metric("Total distance (km)", round(filtered["total_distance_m"].sum() / 1000, 1))
        col3.metric("Season", season_choice)

    with tabs[1]:
        st.subheader("Monthly comparison")
        st.pyplot(analyzer.plot_monthly_comparison())

    with tabs[2]:
        st.subheader("Weekly load")
        if season_choice == ALL_SEASONS and len(seasons) > 1:
            st.info("Week numbers restart every season — pick a specific season above for a meaningful weekly breakdown.")
        weekly = analyzer.weekly_load()
        if weekly.empty:
            st.info("No data for the current filters.")
        else:
            for category, label in WEEKLY_GROUPS:
                st.markdown(f"**{label}**")
                cols = ["week"] + [f"{category}_{metric}" for metric in WEEKLY_METRICS]
                _show_table(weekly[[c for c in cols if c in weekly.columns]])
            fig = analyzer.plot_weekly_load_heatmap()
            if fig is not None:
                st.pyplot(fig)

    with tabs[3]:
        st.subheader("Training vs official vs practice intensity")
        st.pyplot(analyzer.plot_intensity_radar())
        st.subheader("Starter vs substitute (all games)")
        _show_table(analyzer.starter_vs_substitute())

    with tabs[4]:
        st.subheader("Performance trends")
        metric_options = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh"]
        chosen = st.multiselect("Metrics", metric_options, default=["total_distance_m"], format_func=_metric_label)
        if chosen:
            st.pyplot(analyzer.plot_performance_trends(chosen))

        st.subheader("Best / worst sessions")
        col1, col2 = st.columns(2)
        with col1:
            metric = st.selectbox("Metric", metric_options, format_func=_metric_label, key="best_worst_metric")
        with col2:
            category = st.selectbox(
                "Match category", MATCH_CATEGORIES, format_func=lambda c: MATCH_CATEGORY_LABELS[c], key="best_worst_category"
            )
        st.pyplot(analyzer.plot_best_worst(metric=metric, category=category))

    with tabs[5]:
        st.subheader("Baseline comparison")
        category = st.selectbox(
            "Match category", MATCH_CATEGORIES, format_func=lambda c: MATCH_CATEGORY_LABELS[c], key="baseline_category"
        )
        _show_table(analyzer.compare_to_baseline(category))

    with tabs[6]:
        st.subheader("Monthly quality evolution")
        st.caption("Blends training (60%) and official-match (40%) intensity. Practice matches aren't included.")
        fig = analyzer.plot_quality_evolution()
        if fig is not None:
            st.pyplot(fig)
        else:
            st.info("Not enough data to compute a quality trend yet.")

    with tabs[7]:
        st.subheader("Season Summary")
        st.caption("Always covers every season (ignores the Season filter above) — this is the career-wide view.")
        summary = overall_analyzer.season_summary()
        _show_table(summary)
        if len(summary) > 1:
            st.bar_chart(summary.set_index("season")["total_distance_km"])
            st.line_chart(summary.set_index("season")["avg_quality_score"])
        else:
            st.info("Only one season of data so far — this becomes more useful once a second season is added.")

    with tabs[8]:
        st.subheader("Performance Insights")
        st.caption(
            "Per-90 normalization and percentile comparison are adapted from SkillCorner's physical-data "
            "methodology; ACWR is general sports science, not SkillCorner-specific. See the Methodology "
            "section below for exactly what's borrowed vs. adapted."
        )

        scope = analyzer.sessions.sort_values("date")
        gcol1, gcol2, gcol3 = st.columns(3)

        with gcol1:
            acwr_series = compute_acwr(scope).dropna()
            if not acwr_series.empty:
                latest_acwr = acwr_series.iloc[-1]
                st.plotly_chart(acwr_gauge(latest_acwr), use_container_width=True)
                st.caption(f"Zone: **{classify_acwr(latest_acwr)}** — 7-day load vs. 28-day average.")
            else:
                st.info("Not enough data for ACWR yet.")

        with gcol2:
            quality = analyzer.monthly_quality_metric()
            if not quality.empty:
                st.plotly_chart(quality_gauge(quality.iloc[-1]["combined_quality"]), use_container_width=True)
                st.caption(f"Latest month: {quality.iloc[-1]['month_label']}.")
            else:
                st.info("Not enough data for a quality score yet.")

        with gcol3:
            speeds = robust_top_speed(scope).dropna()
            if not speeds.empty:
                personal_best = scope["top_speed_kmh"].max()
                st.plotly_chart(top_speed_gauge(speeds.iloc[-1], personal_best), use_container_width=True)
                st.caption("Rolling 95th-percentile of the last 10 sessions' top speed — see Methodology.")
            else:
                st.info("Not enough data for a robust top speed yet.")

        st.markdown("---")
        st.markdown("**Latest session, ranked against the current filters' history**")
        pcol1, pcol2, pcol3 = st.columns(3)
        rank_metric_options = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh"]
        with pcol1:
            rank_metric = st.selectbox("Metric", rank_metric_options, format_func=_metric_label, key="percentile_metric")
        latest_row = scope.dropna(subset=[rank_metric]).tail(1)
        if not latest_row.empty:
            rank = percentile_rank(scope[rank_metric], latest_row.iloc[0][rank_metric])
            with pcol2:
                st.plotly_chart(percentile_gauge(rank, f"{_metric_label(rank_metric)} Percentile"), use_container_width=True)
            with pcol3:
                intensity = add_intensity_ratios(scope).iloc[-5:]
                avg_hi_pct = intensity["high_speed_pct"].mean()
                st.plotly_chart(intensity_gauge(avg_hi_pct, "High-Speed % (last 5)", max_val=max(avg_hi_pct * 2, 10)), use_container_width=True)
        else:
            st.info(f"No sessions with {_metric_label(rank_metric)} recorded yet.")

        st.markdown("---")
        st.markdown("**Per-90-minute rates** — comparable across sessions regardless of duration")
        per90 = add_per90_columns(scope)
        per90_cols = ["date", "session_kind", "match_category"] + [f"{m}_per90" for m in PER90_METRICS if f"{m}_per90" in per90.columns]
        _show_table(per90[per90_cols].sort_values("date", ascending=False).head(20))

        with st.expander("Methodology — what's SkillCorner, what's adapted, what's general sports science"):
            st.markdown(
                """
**Directly from SkillCorner's methodology** ([skillcornerviz](https://github.com/liamMichaelBailey/skillcornerviz),
their open-source physical-data toolkit):
- **Per-90 normalization** — `add_standard_metrics()` in `skillcorner_physical_utils.py` normalizes distance/accel/decel/sprint
  counts per 90 minutes so sessions of different lengths are comparable. Same idea, applied above.
- **Percentile-based comparison** — their `summary_table.py`/`table_grid.py` color tables by percentile rather than raw value.
  We have no peer group (single player), so this ranks a session against the *player's own* history instead.
- **HI/Sprint thresholds** — SkillCorner defines High-Intensity distance as **>19.8 km/h** and Sprint distance as
  **>25.2 km/h**. We don't recompute these (no raw speed stream to threshold), but this repo's `high_speed_distance_m`/
  `sprint_distance_m` categories already match that convention.

**Inspired by, but explicitly *not*, a SkillCorner metric:**
- **Robust Top Speed** — SkillCorner's real **PSV-99** is the 99th percentile over thousands of raw in-match speed
  *samples*, designed to discount one glitchy sample. We only have one already-aggregated max speed per *session* — over
  a ~10-session window the 99th percentile would just equal "the max of the window" (no noise-robustness gained), so this
  uses the **95th percentile of the last 10 sessions'** top speeds instead. Different granularity, same spirit.

**General sports science, not SkillCorner-specific:**
- **ACWR (Acute:Chronic Workload Ratio)** — Gabbett (2016). 7-day load ÷ 28-day average load. `<0.8` undertrained,
  `0.8–1.3` optimal, `1.3–1.5` elevated risk, `>1.5` high risk. Included because it's the standard injury-risk indicator
  this kind of session-load data is built for, not because SkillCorner invented it.

Full writeup with source links: `docs/skillcorner_metrics.md` in the repo.
                """
            )

    with tabs[9]:
        _add_session_form()


if __name__ == "__main__":
    main()
