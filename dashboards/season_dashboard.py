"""Streamlit dashboard: league table + Monte Carlo prediction for remaining fixtures.

Run with:
    streamlit run dashboards/season_dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_stats.config import list_seasons  # noqa: E402
from football_stats.season.fixtures import load_processed  # noqa: E402
from football_stats.season.league_table import compute_league_table  # noqa: E402
from football_stats.season.predictor import simulate_season  # noqa: E402
from football_stats.season.team_strength import compute_team_strength  # noqa: E402

st.set_page_config(page_title="Season Predictor", page_icon="⚽", layout="wide")


@st.cache_data
def _load_season_data(season_key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    season = next(s for s in list_seasons() if s.key == season_key)
    return load_processed(season)


@st.cache_data(show_spinner="Running Monte Carlo simulation...")
def _run_simulation(season_key: str, n_simulations: int, seed: int):
    played, remaining = _load_season_data(season_key)
    return simulate_season(played, remaining, n_simulations=n_simulations, seed=seed)


def main() -> None:
    st.title("⚽ Season League Table & Prediction")

    seasons = list_seasons()
    season = st.sidebar.selectbox("Season", seasons, format_func=lambda s: s.label)
    n_simulations = st.sidebar.slider("Monte Carlo simulations", 100, 5000, 1000, step=100)
    seed = st.sidebar.number_input("Random seed", min_value=0, value=42, step=1)

    played, remaining = _load_season_data(season.key)

    if played.empty:
        st.warning(
            f"No processed fixtures found for **{season.label}** yet. "
            f"Run `python -m football_stats.scraping.cli {season.key}` to scrape fixtures, "
            "then re-process them into data/seasons/.../processed/."
        )
        return

    n_teams = len(season.teams)
    expected_total_matches = n_teams * (n_teams - 1)  # double round-robin: every pair plays home + away
    matches_involving_only_primary_team = len(played) + len(remaining)
    if n_teams > 1 and matches_involving_only_primary_team < expected_total_matches:
        st.info(
            f"Only {len(played)} recorded match(es) involving {season.primary_team} are loaded — other "
            "teams' results against *each other* haven't been scraped yet, so their standings rows only "
            f"reflect games against {season.primary_team}. {season.primary_team.title()}'s own row is accurate. "
            f"Run `python -m football_stats.scraping.cli {season.key}` for full league coverage."
        )

    tab_table, tab_strength, tab_predict, tab_fixtures = st.tabs(
        ["Current Table", "Team Strength", "Season Prediction", "Upcoming Fixtures"]
    )

    with tab_table:
        st.subheader(f"Current standings — {season.label}")
        st.dataframe(compute_league_table(played), use_container_width=True, hide_index=True)

    with tab_strength:
        st.subheader("Attack / defense strength (relative to league average)")
        strength = compute_team_strength(played)
        st.caption(f"League average goals per game: {strength.league_avg_goals_per_game:.2f}")
        st.dataframe(strength.table, use_container_width=True, hide_index=True)

    with tab_predict:
        st.subheader(f"Projected final table ({n_simulations} simulations)")
        if remaining.empty:
            st.success("Season complete — no remaining fixtures to simulate.")
            st.dataframe(compute_league_table(played), use_container_width=True, hide_index=True)
        else:
            prediction = _run_simulation(season.key, n_simulations, int(seed))
            col1, col2 = st.columns([3, 2])
            with col1:
                st.markdown("**Expected final standings**")
                st.dataframe(prediction.predicted_table, use_container_width=True, hide_index=True)
            with col2:
                st.markdown("**Finish probabilities**")
                st.dataframe(prediction.position_probabilities, use_container_width=True, hide_index=True)
                st.bar_chart(prediction.position_probabilities.set_index("Team")["Title %"])

    with tab_fixtures:
        st.subheader("Remaining fixtures")
        if remaining.empty:
            st.write("No remaining fixtures — season is complete.")
        else:
            st.dataframe(remaining, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
