"""Aggregate scraped per-competition player stats. Ported from ``dev_player_URL.ipynb``."""

from __future__ import annotations

import pandas as pd


def totals_by_player(player_competition_stats: pd.DataFrame) -> pd.DataFrame:
    """Keep only each player's aggregated 'Total' row across all competitions."""
    if "Competition" not in player_competition_stats.columns:
        raise ValueError("Expected a 'Competition' column (see scrape_player_team_stats)")
    return player_competition_stats.loc[player_competition_stats["Competition"] == "Total"].reset_index(drop=True)
