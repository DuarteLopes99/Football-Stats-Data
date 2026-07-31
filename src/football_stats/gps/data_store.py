"""Tidy, appendable storage for GPS training/match session data.

``SATS_Football_GPS_Advanced.xlsx`` (the original source file) stores games and
trainings in two separate sheets, each with a leftover merged-header artifact row
(sub-column labels like "1ª Half"/"2ª Half" that landed in the first data row
instead of the header). ``build_from_excel`` is a one-time conversion that cleans
that up and unifies both sheets into one long ``session_kind`` ("game"/"training")
table, which then lives as a plain CSV (``data/gps/gps_sessions.csv``) that new
sessions can simply be appended to — no more merged-header headaches.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from football_stats.config import DATA_ROOT

DEFAULT_SESSIONS_PATH = DATA_ROOT / "gps" / "gps_sessions.csv"

SCHEMA_COLUMNS = [
    "date",
    "session_kind",       # "game" | "training"
    "week",
    "month",
    "session_type",       # free-text label, e.g. "Jogo Taça -Canedo(CASA) 1-0" or "Treino Segunda-Feira"
    "competition_type",   # games only: "Treino" | "Taça" | "Campeonato"
    "was_starter",        # games only: bool
    "duration_min",
    "minutes_game_zerozero",
    "total_distance_m",
    "sprint_distance_m",
    "high_speed_distance_m",
    "distance_per_min",
    "top_speed_kmh",
    "sprints_1st_half",
    "sprints_2nd_half",
    "sprints_total",
    "accelerations",
    "decelerations",
    "calories",
    "notes",
]

_NUMERIC_COLUMNS = [
    "week",
    "month",
    "duration_min",
    "minutes_game_zerozero",
    "total_distance_m",
    "sprint_distance_m",
    "high_speed_distance_m",
    "distance_per_min",
    "top_speed_kmh",
    "sprints_1st_half",
    "sprints_2nd_half",
    "sprints_total",
    "accelerations",
    "decelerations",
    "calories",
]


def _titularidade_to_bool(value) -> bool | None:
    if pd.isna(value):
        return None
    return str(value).strip().upper() == "SIM"


def _clean_jogos(xlsx_path: Path) -> pd.DataFrame:
    raw = pd.read_excel(xlsx_path, sheet_name="Jogos")
    raw = raw.rename(columns={"Nº Sprints": "sprints_1st_half", "Unnamed: 14": "sprints_2nd_half"})
    raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
    # drops the merged-header artifact row plus free-text marker rows (e.g. "FIM DE EPOCA")
    raw = raw[raw["Date"].notna()].copy()

    df = pd.DataFrame(
        {
            "date": raw["Date"],
            "session_kind": "game",
            "week": raw["Week"],
            "month": raw["Month"],
            "session_type": raw["Session Type"],
            "competition_type": raw["Type game"],
            "was_starter": raw["Titularidade"].apply(_titularidade_to_bool),
            "duration_min": raw["Duration (min)"],
            "minutes_game_zerozero": raw["Minutes (Game) -Zerozero"],
            "total_distance_m": raw["Total Distance (m)"],
            "sprint_distance_m": raw["Sprint Distance (m)"],
            "high_speed_distance_m": raw["High-Speed Distance (m)"],
            "distance_per_min": raw["Distance Per Minuto(m/min"],
            "top_speed_kmh": raw["Top Speed (km/h)"],
            "sprints_1st_half": raw["sprints_1st_half"],
            "sprints_2nd_half": raw["sprints_2nd_half"],
            "accelerations": raw["Accelerations (#)"],
            "decelerations": raw["Decelerations (#)"],
            "calories": raw["Calories"],
            "notes": raw["Notes"],
        }
    )
    df["sprints_1st_half"] = pd.to_numeric(df["sprints_1st_half"], errors="coerce")
    df["sprints_2nd_half"] = pd.to_numeric(df["sprints_2nd_half"], errors="coerce")
    df["sprints_total"] = df["sprints_1st_half"].fillna(0) + df["sprints_2nd_half"].fillna(0)
    return df


def _clean_treinos(xlsx_path: Path) -> pd.DataFrame:
    raw = pd.read_excel(xlsx_path, sheet_name="Treinos")
    raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
    raw = raw[raw["Date"].notna()].copy()  # drops the descriptive-label artifact row

    df = pd.DataFrame(
        {
            "date": raw["Date"],
            "session_kind": "training",
            "week": raw["Week"],
            "month": raw["Month"],
            "session_type": raw["Session Type"],
            "competition_type": None,
            "was_starter": None,
            "duration_min": raw["Duration (min)"],
            "minutes_game_zerozero": None,
            "total_distance_m": raw["Total Distance (m)"],
            "sprint_distance_m": raw["Sprint Distance (m)"],
            "high_speed_distance_m": raw["High-Speed Distance (m)"],
            "distance_per_min": raw["Distance Per Minuto(m/min"],
            "top_speed_kmh": raw["Top Speed (km/h)"],
            "sprints_1st_half": None,
            "sprints_2nd_half": None,
            "sprints_total": raw["Nº Sprints"],
            "accelerations": raw["Accelerations (#)"],
            "decelerations": raw["Decelerations (#)"],
            "calories": raw["Calories"],
            "notes": raw["Notes"],
        }
    )
    return df


def build_from_excel(xlsx_path: str | Path) -> pd.DataFrame:
    """One-time conversion of the original SATS_Football_GPS_Advanced.xlsx into the tidy schema."""
    xlsx_path = Path(xlsx_path)
    combined = pd.concat([_clean_jogos(xlsx_path), _clean_treinos(xlsx_path)], ignore_index=True)
    for col in _NUMERIC_COLUMNS:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")
    combined = combined[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)
    return combined


def load_sessions(path: str | Path = DEFAULT_SESSIONS_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def save_sessions(df: pd.DataFrame, path: str | Path = DEFAULT_SESSIONS_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df[SCHEMA_COLUMNS].to_csv(path, index=False)
    return path


def append_session(new_session: dict, path: str | Path = DEFAULT_SESSIONS_PATH) -> pd.DataFrame:
    """Append one new session (dict of column -> value) and persist it.

    Only ``date`` and ``session_kind`` are required; every other field is optional
    and defaults to missing.
    """
    if "date" not in new_session or "session_kind" not in new_session:
        raise ValueError("A session needs at least 'date' and 'session_kind'")
    if new_session["session_kind"] not in ("game", "training"):
        raise ValueError("session_kind must be 'game' or 'training'")

    existing = load_sessions(path)
    row = {col: new_session.get(col) for col in SCHEMA_COLUMNS}
    updated = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    updated["date"] = pd.to_datetime(updated["date"])
    updated = updated.sort_values("date").reset_index(drop=True)
    save_sessions(updated, path)
    return updated
