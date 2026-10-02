"""Streamlit dashboard: GPS Report (weekly change, load, match demand) and More analysis.

Run from the repo root (that is where Streamlit finds the .streamlit/ theme):
    streamlit run dashboards/gps_dashboard.py

This file holds the shell only — page setup, the global sidebar filters and
navigation. The report layout is ``gps_report.py``, the deeper tabs are
``gps_analysis.py``, and every calculation lives in ``football_stats.gps``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_HERE = Path(__file__).resolve().parent
# Runs from a fresh clone without `pip install -e .`.
sys.path.insert(0, str(_HERE.parent / "src"))
sys.path.insert(0, str(_HERE))

from football_stats.gps import charts  # noqa: E402
from football_stats.gps import config as cfg  # noqa: E402
from football_stats.gps.cleaning import prepare_sessions  # noqa: E402
from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, load_sessions  # noqa: E402
from football_stats.gps.microcycle import add_md_labels  # noqa: E402
from football_stats.gps.sync import source_is_newer  # noqa: E402

import gps_analysis  # noqa: E402
import gps_report  # noqa: E402

st.set_page_config(page_title="GPS Report", page_icon="📊", layout="wide", initial_sidebar_state="expanded")


@st.cache_data
def load_report_data(_csv_mtime: float) -> pd.DataFrame:
    """Prepared, MD-labelled sessions. Keyed on the CSV's mtime so a sync
    invalidates the cache without a restart."""
    raw = load_sessions(DEFAULT_SESSIONS_PATH)
    if raw.empty:
        return raw
    return add_md_labels(prepare_sessions(raw))


def _default_season(sessions: pd.DataFrame, seasons: list[str]) -> str:
    """Latest season with an official match — a brand-new pre-season holding a
    single friendly makes a thin report to open on."""
    with_matches = sessions.loc[sessions["match_category"] == cfg.OFFICIAL_MATCH, "season"]
    return with_matches.max() if not with_matches.empty else seasons[0]


def _sync_from_inputs() -> None:
    state = st.session_state
    start, end = state["date_from"], state["date_to"]
    if start > end:
        start, end = end, start
        state["date_from"], state["date_to"] = start, end
    state["date_range"] = (start, end)


def _sync_from_slider() -> None:
    state = st.session_state
    state["date_from"], state["date_to"] = state["date_range"]


def sidebar(sessions: pd.DataFrame) -> gps_report.ReportScope:
    body_seasons = set(gps_analysis._load_body()[0].get("season", pd.Series(dtype=str)).dropna().unique())
    seasons = sorted(set(sessions["season"].unique()) | body_seasons, reverse=True)
    default = _default_season(sessions, seasons)

    player_slot = st.sidebar.container()  # player block sits above the filters, as in the reference
    season = st.sidebar.selectbox("Season", seasons, index=seasons.index(default), key="season")
    player = cfg.PLAYER
    player_slot.html(
        f'<div class="gps-player"><div class="name">{player["name"]}</div>'
        f'<div class="meta">{player["position"]}<br>Season {season}</div></div>'
    )

    season_dates = sessions.loc[sessions["season"] == season, "date"]
    if season_dates.empty:
        start_year = int(season[:4])
        low = high = pd.Timestamp(year=start_year, month=7, day=1).date()
    else:
        low, high = season_dates.min().date(), season_dates.max().date()

    state = st.session_state
    if state.get("_range_season") != season:
        state["date_from"], state["date_to"], state["date_range"] = low, high, (low, high)
        state["_range_season"] = season

    st.sidebar.html('<div class="gps-sidebar-label">Date</div>')
    left, right = st.sidebar.columns(2)
    left.date_input("From", key="date_from", min_value=low, max_value=high, on_change=_sync_from_inputs, format="DD/MM/YYYY")
    right.date_input("To", key="date_to", min_value=low, max_value=high, on_change=_sync_from_inputs, format="DD/MM/YYYY")
    if low < high:
        st.sidebar.slider("Date range", min_value=low, max_value=high, key="date_range", on_change=_sync_from_slider,
                          format="DD MMM", label_visibility="collapsed")

    type_label = st.sidebar.radio("Session type", list(cfg.SESSION_TYPE_FILTERS), key="session_type")
    focus = st.sidebar.selectbox(
        "Focus metric", cfg.FOCUS_METRICS, format_func=lambda m: cfg.METRICS[m].label, key="focus_metric",
        help="Drives the load/ACWR chart, the % of match demand bars and the microcycle profile.",
    )
    with st.sidebar.expander("Report settings"):
        change_mode = st.radio("Weekly change basis", list(cfg.CHANGE_MODES), format_func=cfg.CHANGE_MODES.get,
                               index=list(cfg.CHANGE_MODES).index(cfg.DEFAULT_CHANGE_MODE), key="change_mode")
        acwr_method = st.radio("ACWR method", ["rolling", "ewma"], index=["rolling", "ewma"].index(cfg.ACWR_METHOD),
                               format_func={"rolling": "Rolling 4-week mean", "ewma": "EWMA"}.get, key="acwr_method")

    if not sessions.empty:
        st.sidebar.caption(f"Data to {sessions['date'].max():%d %b %Y} · {len(sessions)} sessions in the log.")
    if source_is_newer():
        st.sidebar.warning("The STATSports workbook is newer than the CSV — run `python -m football_stats.gps.sync`.", icon="🔄")

    start, end = state["date_from"], state["date_to"]
    return gps_report.ReportScope(
        sessions=sessions, season=season, start=pd.Timestamp(start), end=pd.Timestamp(end),
        categories=cfg.SESSION_TYPE_FILTERS[type_label], type_label=type_label,
        focus_metric=focus, change_mode=change_mode, acwr_method=acwr_method,
    )


def main() -> None:
    st.html(charts.page_css())
    sessions = load_report_data(DEFAULT_SESSIONS_PATH.stat().st_mtime if DEFAULT_SESSIONS_PATH.exists() else 0.0)
    if sessions.empty:
        st.warning("No GPS sessions found. Run `python -m football_stats.gps.sync` to build the log from the workbook.")
        return

    scope_holder: dict[str, gps_report.ReportScope] = {}

    def report_page() -> None:
        gps_report.render(scope_holder["scope"])

    def analysis_page() -> None:
        scope = scope_holder["scope"]
        gps_analysis.render(scope.filtered, scope.sessions, scope.season, scope.start, scope.end)

    navigation = st.navigation(
        [
            st.Page(report_page, title="GPS Report", icon="📊", default=True),
            st.Page(analysis_page, title="More analysis", icon="🔬", url_path="analysis"),
        ]
    )
    scope_holder["scope"] = sidebar(sessions)
    navigation.run()


main()
