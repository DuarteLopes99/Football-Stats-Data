"""Turn raw per-team zerozero.pt fixture exports into tidy season fixture tables.

Ported and simplified from ``dev_model.ipynb`` (StatsSports): each team's raw
export lists the same inter-team matches from its own point of view, so every
match shows up twice (once per team) once all teams are combined — ``dedupe_fixtures``
collapses that.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from football_stats.config import SeasonConfig

PLAYED_COLUMNS = ["Numeric Matchweek", "Matchweek", "Home Team", "Away Team", "Home Goals", "Away Goals"]
REMAINING_COLUMNS = ["Numeric Matchweek", "Matchweek", "Home Team", "Away Team"]


def load_raw_team_fixtures(season: SeasonConfig) -> dict[str, pd.DataFrame]:
    """Load previously-scraped `{team}_fixtures.csv` files from a season's raw dir."""
    fixtures = {}
    for team_slug in season.teams:
        path = season.raw_dir / f"{team_slug}_fixtures.csv"
        if path.exists():
            fixtures[team_slug] = pd.read_csv(path)
    return fixtures


def _add_home_away(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Home Team"] = df.apply(lambda r: r["Team1"] if r["Location"] == "(C)" else r["Team2"], axis=1)
    df["Away Team"] = df.apply(lambda r: r["Team2"] if r["Location"] == "(C)" else r["Team1"], axis=1)
    return df


def _numeric_matchweek(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d+)")[0].astype(int)


def _build_played(raw_team_fixtures: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for df in raw_team_fixtures.values():
        played = df[df["Played?"] == True].copy()  # noqa: E712
        if played.empty:
            continue
        played[["Score1", "Score2"]] = played["Result"].str.split("-", expand=True).astype(int)
        played = _add_home_away(played)
        # "Result" is always "home score-away score" regardless of which side Team1 is on
        # (Location only tells us whether Team1 *is* the home team, not how to read the score).
        played["Home Goals"] = played["Score1"]
        played["Away Goals"] = played["Score2"]
        played["Numeric Matchweek"] = _numeric_matchweek(played["Matchweek"])
        frames.append(played[PLAYED_COLUMNS])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PLAYED_COLUMNS)


def _build_remaining(raw_team_fixtures: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for df in raw_team_fixtures.values():
        not_played = df[df["Played?"] == False].copy()  # noqa: E712
        if not_played.empty:
            continue
        not_played = _add_home_away(not_played)
        not_played["Numeric Matchweek"] = _numeric_matchweek(not_played["Matchweek"])
        frames.append(not_played[REMAINING_COLUMNS])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=REMAINING_COLUMNS)


def dedupe_fixtures(df: pd.DataFrame) -> pd.DataFrame:
    """Each match appears once per team's raw export — keep a single row per match."""
    if df.empty:
        return df
    match_key = df.apply(lambda r: (r["Matchweek"], tuple(sorted([r["Home Team"], r["Away Team"]]))), axis=1)
    deduped = df.loc[~match_key.duplicated()].copy()
    return deduped.sort_values("Numeric Matchweek").reset_index(drop=True)


def _add_winner(played: pd.DataFrame) -> pd.DataFrame:
    played = played.copy()
    played["Winner"] = played.apply(
        lambda r: "Home" if r["Home Goals"] > r["Away Goals"] else ("Away" if r["Home Goals"] < r["Away Goals"] else "Draw"),
        axis=1,
    )
    return played


def split_played_remaining(raw_team_fixtures: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build deduped (played, remaining) fixture tables from each team's raw export."""
    played = dedupe_fixtures(_build_played(raw_team_fixtures))
    remaining = dedupe_fixtures(_build_remaining(raw_team_fixtures))
    if not played.empty:
        played = _add_winner(played)
    return played, remaining


def save_processed(season: SeasonConfig, played: pd.DataFrame, remaining: pd.DataFrame) -> tuple[Path, Path]:
    played_path = season.processed_dir / "fixtures_played.csv"
    remaining_path = season.processed_dir / "fixtures_remaining.csv"
    played.to_csv(played_path, index=False)
    remaining.to_csv(remaining_path, index=False)
    return played_path, remaining_path


def load_processed(season: SeasonConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    played_path = season.processed_dir / "fixtures_played.csv"
    remaining_path = season.processed_dir / "fixtures_remaining.csv"
    played = pd.read_csv(played_path) if played_path.exists() else pd.DataFrame(columns=[*PLAYED_COLUMNS, "Winner"])
    remaining = pd.read_csv(remaining_path) if remaining_path.exists() else pd.DataFrame(columns=REMAINING_COLUMNS)
    return played, remaining
