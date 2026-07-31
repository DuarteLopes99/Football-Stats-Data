"""Turn scraped match-report rows (one row per player per match) into event tables
and per-player season stats. Ported from ``dev_games_stats.ipynb``.
"""

from __future__ import annotations

import re

import pandas as pd

EVENTS_COLUMNS = ["match_url", "team", "player_name", "minute", "event_type"]


def parse_minutes(value) -> list[int]:
    """Parse a minute-events string like "23, 45+2'" into [23, 47]."""
    if pd.isna(value):
        return []
    tokens = re.split(r"[ ,]+", str(value).strip())
    minutes = []
    for token in tokens:
        token = token.strip().replace("'", "")
        if not token:
            continue
        try:
            if "+" in token:
                base, extra = token.split("+")
                minutes.append(int(base) + int(extra))
            else:
                minutes.append(int(token))
        except ValueError:
            continue
    return minutes


def explode_events(match_players: pd.DataFrame, column: str, event_type: str) -> pd.DataFrame:
    """One row per (player, minute) event, exploded from a comma-separated minutes column."""
    rows = []
    for _, row in match_players.iterrows():
        for minute in parse_minutes(row[column]):
            event_row = {
                "match_url": row["match_url"],
                "team": row["team"],
                "player_name": row["name"],
                "minute": minute,
                "event_type": event_type,
            }
            if event_type == "goal":
                note = str(row[column]).lower()
                event_row["goal_type"] = "penalty" if ("g.p" in note or "pen" in note) else "open_play"
            rows.append(event_row)
    return pd.DataFrame(rows)


def build_events_table(match_players: pd.DataFrame) -> pd.DataFrame:
    """Combine goals/assists/cards into one tidy long-format events table."""
    parts = [
        explode_events(match_players, "Goals", "goal"),
        explode_events(match_players, "Assists", "assist"),
        explode_events(match_players, "Yellow Card", "yellow_card"),
        explode_events(match_players, "Red Card", "red_card"),
    ]
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=EVENTS_COLUMNS)


def _first_minute(value) -> int | None:
    minutes = parse_minutes(value)
    return minutes[0] if minutes else None


def estimate_minutes_played(match_players: pd.DataFrame) -> pd.DataFrame:
    """Add sub_in_min / sub_out_min / minutes_played columns.

    Heuristic: starters play until subbed off (else full 90); substitutes play from
    their sub-in minute to 90 (else 0 if they never entered).
    """
    df = match_players.copy()
    df["sub_in_min"] = df["Substitution IN"].apply(_first_minute)
    df["sub_out_min"] = df["Substitution OUT"].apply(_first_minute)

    def minutes_played(row):
        if row["status"] == "Starter":
            return row["sub_out_min"] if pd.notnull(row["sub_out_min"]) else 90
        return 90 - row["sub_in_min"] if pd.notnull(row["sub_in_min"]) else 0

    df["minutes_played"] = df.apply(minutes_played, axis=1)
    return df


def build_player_season_stats(match_players: pd.DataFrame, team_name: str) -> pd.DataFrame:
    """Per-player season totals (goals, assists, cards, minutes, starts/subs) for one team."""
    df = estimate_minutes_played(match_players)
    team_df = df[df["team"] == team_name]

    stats = team_df.groupby("name").agg(
        matches_played=("match_url", "nunique"),
        total_goals=("Goals", lambda values: sum(len(parse_minutes(v)) for v in values)),
        total_assists=("Assists", lambda values: sum(len(parse_minutes(v)) for v in values)),
        total_minutes=("minutes_played", "sum"),
        yellow_cards=("Yellow Card", lambda values: sum(len(parse_minutes(v)) for v in values)),
        red_cards=("Red Card", lambda values: sum(len(parse_minutes(v)) for v in values)),
    ).reset_index()

    starts = team_df[team_df["status"] == "Starter"].groupby("name")["match_url"].nunique()
    subs = team_df[team_df["status"] != "Starter"].groupby("name")["match_url"].nunique()
    stats = stats.merge(starts.rename("starts"), on="name", how="left")
    stats = stats.merge(subs.rename("subs"), on="name", how="left")
    stats["starts"] = stats["starts"].fillna(0).astype(int)
    stats["subs"] = stats["subs"].fillna(0).astype(int)

    stats["G+A"] = stats["total_goals"] + stats["total_assists"]
    stats["goals_per_game"] = (stats["total_goals"] / stats["matches_played"]).round(2)
    stats["contributions_per_game"] = (stats["G+A"] / stats["matches_played"]).round(2)
    stats["contributions_per_90"] = (
        (stats["G+A"] / stats["total_minutes"] * 90).where(stats["total_minutes"] > 0, 0).round(2)
    )

    return stats.sort_values("G+A", ascending=False).reset_index(drop=True)
