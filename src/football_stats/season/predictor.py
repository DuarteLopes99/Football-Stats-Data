"""Monte Carlo season predictor: simulate remaining fixtures with a Poisson model.

Ported from ``dev_model.ipynb``, fixing a bug present there: the original final
merge divided the already-averaged `Points_Predicted`/`GD_Predicted`/etc. columns
by ``N_SIMULATIONS`` a second time (they'd already gone through a `groupby.mean()`),
producing nonsensical values (e.g. `Draws_Predicted: 965.36`). Here every per-team
stat across simulations is summed exactly once and divided by ``n_simulations``
exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import poisson

from football_stats.season.league_table import compute_league_table
from football_stats.season.team_strength import TeamStrength, compute_team_strength

HOME_ADVANTAGE = 1.15
STAT_COLUMNS = ["Points", "Wins", "Draws", "Losses", "Goals Scored", "Goals Conceded", "GD", "Played"]


@dataclass
class SeasonPrediction:
    actual_table: pd.DataFrame
    """Standings from played matches only."""

    predicted_table: pd.DataFrame
    """Expected final standings: actual + remaining fixtures, averaged over all simulations."""

    position_probabilities: pd.DataFrame
    """Per team: probability (%) of finishing 1st, in the top 3, or in the bottom 3."""

    n_simulations: int


def simulate_match(home_team: str, away_team: str, strength: TeamStrength, rng: np.random.Generator) -> tuple[int, int]:
    league_avg_goals = strength.league_avg_goals_per_game / 2
    home_attack = strength.attack.get(home_team, 1.0)
    away_defense = strength.defense.get(away_team, 1.0)
    away_attack = strength.attack.get(away_team, 1.0)
    home_defense = strength.defense.get(home_team, 1.0)

    home_goals = poisson.rvs((home_attack / away_defense) * league_avg_goals * HOME_ADVANTAGE, random_state=rng)
    away_goals = poisson.rvs((away_attack / home_defense) * league_avg_goals, random_state=rng)
    return int(home_goals), int(away_goals)


def _rank_teams(table: pd.DataFrame) -> list[str]:
    return table.sort_values(["Points", "GD"], ascending=[False, False])["Team"].tolist()


def _position_probabilities(position_counts: dict[str, np.ndarray], n_simulations: int, n_teams: int) -> pd.DataFrame:
    rows = []
    top3_span = min(3, n_teams)
    for team, counts in position_counts.items():
        rows.append(
            {
                "Team": team,
                "Title %": round(100 * counts[0] / n_simulations, 1),
                "Top 3 %": round(100 * counts[:top3_span].sum() / n_simulations, 1),
                "Bottom 3 %": round(100 * counts[-top3_span:].sum() / n_simulations, 1),
            }
        )
    return pd.DataFrame(rows).sort_values("Title %", ascending=False).reset_index(drop=True)


def simulate_season(
    played_matches: pd.DataFrame,
    remaining_fixtures: pd.DataFrame,
    n_simulations: int = 1000,
    seed: int | None = None,
) -> SeasonPrediction:
    """Simulate the rest of a season ``n_simulations`` times and average the outcomes."""
    actual_table = compute_league_table(played_matches)
    teams = sorted(actual_table["Team"].tolist())
    n_teams = len(teams)
    rng = np.random.default_rng(seed)

    if remaining_fixtures.empty:
        ranked = _rank_teams(actual_table)
        position_counts = {team: np.zeros(n_teams) for team in teams}
        for pos, team in enumerate(ranked):
            position_counts[team][pos] = n_simulations
        return SeasonPrediction(
            actual_table=actual_table,
            predicted_table=actual_table.copy(),
            position_probabilities=_position_probabilities(position_counts, n_simulations, n_teams),
            n_simulations=n_simulations,
        )

    strength = compute_team_strength(played_matches)
    accumulated = {team: {col: 0.0 for col in STAT_COLUMNS} for team in teams}
    position_counts = {team: np.zeros(n_teams) for team in teams}

    for _ in range(n_simulations):
        simulated_rows = []
        for _, fixture in remaining_fixtures.iterrows():
            home, away = fixture["Home Team"], fixture["Away Team"]
            home_goals, away_goals = simulate_match(home, away, strength, rng)
            simulated_rows.append({"Home Team": home, "Away Team": away, "Home Goals": home_goals, "Away Goals": away_goals})

        full_matches = pd.concat([played_matches, pd.DataFrame(simulated_rows)], ignore_index=True)
        sim_table = compute_league_table(full_matches).set_index("Team")

        for pos, team in enumerate(_rank_teams(sim_table.reset_index())):
            position_counts[team][pos] += 1

        for team in teams:
            row = sim_table.loc[team]
            for col in STAT_COLUMNS:
                accumulated[team][col] += row[col]

    predicted_rows = [
        {"Team": team, **{col: round(accumulated[team][col] / n_simulations, 2) for col in STAT_COLUMNS}}
        for team in teams
    ]
    predicted_table = (
        pd.DataFrame(predicted_rows).sort_values(["Points", "GD"], ascending=[False, False]).reset_index(drop=True)
    )

    return SeasonPrediction(
        actual_table=actual_table,
        predicted_table=predicted_table,
        position_probabilities=_position_probabilities(position_counts, n_simulations, n_teams),
        n_simulations=n_simulations,
    )
