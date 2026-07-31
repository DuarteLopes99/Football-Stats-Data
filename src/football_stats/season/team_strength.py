"""Attack/defense strength relative to league average, ported from ``dev_model.ipynb``."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFENSE_SMOOTHING = 0.1
"""Added to average goals conceded before dividing, so a perfect defense (0 conceded)
doesn't produce an unbounded defense strength."""


@dataclass
class TeamStrength:
    attack: dict[str, float]
    defense: dict[str, float]
    league_avg_goals_per_game: float
    table: pd.DataFrame


def compute_team_strength(matches: pd.DataFrame) -> TeamStrength:
    """Attack strength = team's avg goals scored / league avg.
    Defense strength = league avg / (team's avg goals conceded + smoothing).
    Both center around 1.0 for an average team.
    """
    teams = pd.concat([matches["Home Team"], matches["Away Team"]]).unique()
    stats = {team: {"GF": 0, "GA": 0, "Matches": 0} for team in teams}

    total_goals = 0
    total_matches = 0
    for _, row in matches.iterrows():
        home, away, home_goals, away_goals = row["Home Team"], row["Away Team"], row["Home Goals"], row["Away Goals"]
        stats[home]["GF"] += home_goals
        stats[home]["GA"] += away_goals
        stats[home]["Matches"] += 1
        stats[away]["GF"] += away_goals
        stats[away]["GA"] += home_goals
        stats[away]["Matches"] += 1
        total_goals += home_goals + away_goals
        total_matches += 1

    league_avg_goals_per_game = total_goals / (2 * total_matches) if total_matches else 0.0

    attack: dict[str, float] = {}
    defense: dict[str, float] = {}
    rows = []
    for team, s in stats.items():
        avg_gf = s["GF"] / s["Matches"] if s["Matches"] else 0.0
        avg_ga = s["GA"] / s["Matches"] if s["Matches"] else 0.0
        team_attack = avg_gf / league_avg_goals_per_game if league_avg_goals_per_game else 0.0
        team_defense = league_avg_goals_per_game / (avg_ga + DEFENSE_SMOOTHING) if league_avg_goals_per_game else 0.0
        attack[team] = team_attack
        defense[team] = team_defense
        rows.append(
            {
                "Team": team,
                "Goals Scored": s["GF"],
                "Goals Conceded": s["GA"],
                "Avg Goals Scored": round(avg_gf, 2),
                "Avg Goals Conceded": round(avg_ga, 2),
                "Attack Strength": round(team_attack, 3),
                "Defense Strength": round(team_defense, 3),
            }
        )

    table = pd.DataFrame(rows).sort_values("Goals Scored", ascending=False).reset_index(drop=True)
    return TeamStrength(attack=attack, defense=defense, league_avg_goals_per_game=league_avg_goals_per_game, table=table)
