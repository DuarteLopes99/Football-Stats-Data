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

from football_stats.gps.analyzer import PerformanceAnalyzer  # noqa: E402
from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, append_session, load_sessions  # noqa: E402

st.set_page_config(page_title="GPS Performance", page_icon="🏃", layout="wide")


@st.cache_data
def _load() -> pd.DataFrame:
    return load_sessions(DEFAULT_SESSIONS_PATH)


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

    kinds = st.sidebar.multiselect("Session kind", ["training", "game"], default=["training", "game"])
    min_date, max_date = sessions["date"].min().date(), sessions["date"].max().date()
    date_range = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)

    filtered = sessions[sessions["session_kind"].isin(kinds)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        filtered = filtered[(filtered["date"] >= pd.Timestamp(start)) & (filtered["date"] <= pd.Timestamp(end))]

    analyzer = PerformanceAnalyzer(filtered)

    tabs = st.tabs(
        ["Overview", "Monthly", "Weekly Load", "Intensity", "Trends", "Baseline", "Quality", "Add Session"]
    )

    with tabs[0]:
        st.subheader("Sessions")
        st.dataframe(filtered.sort_values("date", ascending=False), use_container_width=True, hide_index=True)
        st.metric("Total sessions", len(filtered))
        st.metric("Total distance (km)", round(filtered["total_distance_m"].sum() / 1000, 1))

    with tabs[1]:
        st.subheader("Monthly comparison")
        fig = analyzer.plot_monthly_comparison()
        st.pyplot(fig)

    with tabs[2]:
        st.subheader("Weekly load")
        weekly = analyzer.weekly_load()
        st.dataframe(weekly, use_container_width=True, hide_index=True)
        fig = analyzer.plot_weekly_load_heatmap()
        if fig is not None:
            st.pyplot(fig)

    with tabs[3]:
        st.subheader("Training vs match intensity")
        fig = analyzer.plot_intensity_radar()
        st.pyplot(fig)
        st.subheader("Starter vs substitute (matches)")
        st.dataframe(analyzer.starter_vs_substitute(), use_container_width=True, hide_index=True)

    with tabs[4]:
        st.subheader("Performance trends")
        metric_options = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh"]
        chosen = st.multiselect("Metrics", metric_options, default=["total_distance_m"])
        if chosen:
            st.pyplot(analyzer.plot_performance_trends(chosen))

        st.subheader("Best / worst sessions")
        col1, col2 = st.columns(2)
        with col1:
            metric = st.selectbox("Metric", metric_options, key="best_worst_metric")
        with col2:
            kind = st.selectbox("Session kind", ["training", "game"], key="best_worst_kind")
        st.pyplot(analyzer.plot_best_worst(metric=metric, session_kind=kind))

    with tabs[5]:
        st.subheader("Baseline comparison")
        kind = st.selectbox("Session kind", ["training", "game"], key="baseline_kind")
        st.dataframe(analyzer.compare_to_baseline(kind), use_container_width=True, hide_index=True)

    with tabs[6]:
        st.subheader("Monthly quality evolution")
        fig = analyzer.plot_quality_evolution()
        if fig is not None:
            st.pyplot(fig)
        else:
            st.info("Not enough data to compute a quality trend yet.")

    with tabs[7]:
        _add_session_form()


if __name__ == "__main__":
    main()
