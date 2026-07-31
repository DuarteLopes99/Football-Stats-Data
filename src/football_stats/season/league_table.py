"""League table computation, ported from ``dev_model.ipynb``'s ``compute_league_table``."""

from __future__ import annotations

import pandas as pd

STANDINGS_COLUMNS = ["Team", "Points", "Wins", "Draws", "Losses", "Goals Scored", "Goals Conceded", "GD", "Played"]


def compute_league_table(matches: pd.DataFrame) -> pd.DataFrame:
    """Compute standings from match results.

    ``matches`` must have columns: Home Team, Away Team, Home Goals, Away Goals.
    Sorted by Points then Goal Difference, both descending.
    """
    if matches.empty:
        return pd.DataFrame(columns=STANDINGS_COLUMNS)

    teams = pd.concat([matches["Home Team"], matches["Away Team"]]).unique()
    table = {
        team: {"Points": 0, "Wins": 0, "Draws": 0, "Losses": 0, "GF": 0, "GA": 0, "GD": 0, "Played": 0}
        for team in teams
    }

    for _, match in matches.iterrows():
        home, away = match["Home Team"], match["Away Team"]
        home_goals, away_goals = match["Home Goals"], match["Away Goals"]

        table[home]["Played"] += 1
        table[away]["Played"] += 1
        table[home]["GF"] += home_goals
        table[home]["GA"] += away_goals
        table[away]["GF"] += away_goals
        table[away]["GA"] += home_goals
        table[home]["GD"] += home_goals - away_goals
        table[away]["GD"] += away_goals - home_goals

        if home_goals > away_goals:
            table[home]["Points"] += 3
            table[home]["Wins"] += 1
            table[away]["Losses"] += 1
        elif home_goals < away_goals:
            table[away]["Points"] += 3
            table[away]["Wins"] += 1
            table[home]["Losses"] += 1
        else:
            table[home]["Points"] += 1
            table[away]["Points"] += 1
            table[home]["Draws"] += 1
            table[away]["Draws"] += 1

    league_table = pd.DataFrame.from_dict(table, orient="index").reset_index()
    league_table = league_table.rename(columns={"index": "Team", "GF": "Goals Scored", "GA": "Goals Conceded"})
    league_table = league_table[STANDINGS_COLUMNS]
    return league_table.sort_values(["Points", "GD"], ascending=[False, False]).reset_index(drop=True)
