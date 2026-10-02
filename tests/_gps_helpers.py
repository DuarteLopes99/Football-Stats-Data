"""Build small, hand-checkable session logs for the GPS report tests."""

from __future__ import annotations

import pandas as pd

from football_stats.gps.cleaning import prepare_sessions
from football_stats.gps.data_store import SCHEMA_COLUMNS
from football_stats.gps.microcycle import add_md_labels


def training(date: str, distance: float = 6000, **extra) -> dict:
    row = {
        "date": date, "session_kind": "training", "session_type": "Treino", "duration_min": 80,
        "total_distance_m": distance, "high_speed_distance_m": 800, "sprint_distance_m": 200,
        "top_speed_kmh": 28.0, "sprints_total": 8, "accelerations": 40, "decelerations": 50,
    }
    row.update(extra)
    return row


def match(date: str, distance: float = 9000, competition: str = "Campeonato", **extra) -> dict:
    row = {
        "date": date, "session_kind": "game", "session_type": "Jornada 1 - Rival (CASA) 1-0",
        "competition_type": competition, "was_starter": True, "duration_min": 90, "minutes_game_zerozero": 90,
        "total_distance_m": distance, "high_speed_distance_m": 1500, "sprint_distance_m": 500,
        "top_speed_kmh": 32.0, "sprints_total": 20, "accelerations": 50, "decelerations": 70,
    }
    row.update(extra)
    return row


def friendly(date: str, distance: float = 7000, **extra) -> dict:
    return match(date, distance, competition="Treino", session_type="Jogo Treino Rival (CASA) 2-2", **extra)


def unused_sub(date: str) -> dict:
    """An official match exported as a row of zeros — on the bench all game."""
    zeros = {k: 0 for k in ["duration_min", "minutes_game_zerozero", "high_speed_distance_m", "sprint_distance_m",
                            "top_speed_kmh", "sprints_total", "accelerations", "decelerations"]}
    return match(date, distance=0, notes="BANCO", **zeros)


def build(rows: list[dict], labelled: bool = True) -> pd.DataFrame:
    raw = pd.DataFrame(rows).reindex(columns=SCHEMA_COLUMNS)
    prepared = prepare_sessions(raw)
    return add_md_labels(prepared) if labelled else prepared


def row_on(df: pd.DataFrame, date: str, category: str | None = None) -> pd.Series:
    rows = df[df["date"] == pd.Timestamp(date)]
    if category:
        rows = rows[rows["match_category"] == category]
    assert len(rows) == 1, f"expected one row on {date}, got {len(rows)}"
    return rows.iloc[0]
