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
from football_stats.gps.seasons import add_season_column  # noqa: E402

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
        ["Overview", "Monthly", "Weekly Load", "Intensity", "Trends", "Baseline", "Quality", "Season Summary", "Add Session"]
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
        _add_session_form()


if __name__ == "__main__":
    main()
