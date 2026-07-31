"""Regression checks against the real seeded season data in data/seasons/."""

from football_stats.config import get_season
from football_stats.season.fixtures import load_processed
from football_stats.season.league_table import compute_league_table


def test_mansores_actual_record_matches_known_result():
    season = get_season("mansores_2025_26")
    played, remaining = load_processed(season)
    table = compute_league_table(played).set_index("Team")

    mansores = table.loc["mansores"]
    assert mansores["Played"] == 11
    assert mansores["Wins"] == 10
    assert mansores["Draws"] == 0
    assert mansores["Losses"] == 1
    assert mansores["Points"] == 30
    assert len(remaining) == 11


def test_fermedo_season_is_fully_played():
    season = get_season("fermedo_2024_25")
    played, remaining = load_processed(season)
    table = compute_league_table(played)

    assert remaining.empty
    assert (table["Played"] == 30).all()
    assert table.iloc[0]["Team"] == "sanguedo"  # league winners, highest points
