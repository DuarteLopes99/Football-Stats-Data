import pandas as pd

from football_stats.season.fixtures import split_played_remaining


def _raw_row(location, team2, result, played, matchweek="J1"):
    return {
        "Result - abv": "V",
        "Date": "2025-01-01",
        "Hour": "15:30",
        "Location": location,
        "Team1": "mansores",
        "Team2": team2,
        "Result": result,
        "Competition": "Test League",
        "Matchweek": matchweek,
        "Played?": played,
    }


def test_result_string_is_always_home_away_not_team1_team2():
    """Regression test: zerozero.pt's "Result" column is always "home score-away score",
    regardless of which side (Team1/Team2) is the home team. An earlier version of this
    pipeline (ported as-is from the exploratory notebooks) swapped the score whenever the
    tracked team played away, silently flipping away wins into home wins.
    """
    away_win = pd.DataFrame([_raw_row("(F)", "Mosteiro", "0-2", True, matchweek="J1")])  # mansores wins away 2-0
    home_win = pd.DataFrame([_raw_row("(C)", "Mosteiro", "3-1", True, matchweek="J2")])  # mansores wins at home 3-1

    played, _ = split_played_remaining({"mansores": pd.concat([away_win, home_win], ignore_index=True)})
    away_match = played[played["Away Team"] == "mansores"].iloc[0]
    home_match = played[played["Home Team"] == "mansores"].iloc[0]

    assert away_match["Home Team"] == "Mosteiro"
    assert away_match["Home Goals"] == 0
    assert away_match["Away Goals"] == 2
    assert away_match["Winner"] == "Away"  # mansores, the away team, won

    assert home_match["Home Goals"] == 3
    assert home_match["Away Goals"] == 1
    assert home_match["Winner"] == "Home"


def test_split_played_remaining_partitions_by_played_flag():
    df = pd.DataFrame(
        [
            _raw_row("(C)", "Mosteiro", "1-0", True),
            _raw_row("(F)", "Espinho", None, False),
        ]
    )
    played, remaining = split_played_remaining({"mansores": df})
    assert len(played) == 1
    assert len(remaining) == 1
    assert remaining.iloc[0]["Away Team"] == "mansores"
