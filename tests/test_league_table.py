import pandas as pd

from football_stats.season.league_table import compute_league_table


def test_compute_league_table_points_and_gd():
    matches = pd.DataFrame(
        [
            {"Home Team": "A", "Away Team": "B", "Home Goals": 2, "Away Goals": 0},
            {"Home Team": "B", "Away Team": "A", "Home Goals": 1, "Away Goals": 1},
            {"Home Team": "A", "Away Team": "C", "Home Goals": 0, "Away Goals": 3},
        ]
    )
    table = compute_league_table(matches).set_index("Team")

    assert table.loc["A", "Points"] == 4  # win + draw
    assert table.loc["A", "Wins"] == 1
    assert table.loc["A", "Draws"] == 1
    assert table.loc["A", "Losses"] == 1
    assert table.loc["A", "GD"] == 2 - 0 + 1 - 1 + 0 - 3

    assert table.loc["B", "Points"] == 1  # draw only (still has the loss to A)
    assert table.loc["C", "Points"] == 3  # single win

    # sorted by Points desc
    assert table.index.tolist()[0] == "A"


def test_compute_league_table_empty_input():
    empty = pd.DataFrame(columns=["Home Team", "Away Team", "Home Goals", "Away Goals"])
    table = compute_league_table(empty)
    assert table.empty
