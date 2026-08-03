"""Position-specific physical performance baselines, replacing the old flat
`DEFAULT_BASELINE` (which came from the source spreadsheet's `Reference_Baseline`
sheet — a single set of numbers with no stated source and no position split).

**Every number here is sourced from published research, not invented** — see
`docs/gps_analysis.md` for the full citation list and, importantly, which parts
are directly-measured vs. an estimate where the literature didn't have a clean
answer. Short version:

- **Official match** distance metrics (total/high-speed/sprint distance) are
  Di Salvo et al. (2007), *Int J Sports Med* 28(3):222-227 — 300 elite outfield
  players, Spanish La Liga + Champions League. Their 5 speed zones are combined
  to approximate our `high_speed_distance_m` (>19.8 km/h) / `sprint_distance_m`
  (>25.2 km/h) thresholds.
- **Official match** accelerations/decelerations are a separate GPS study
  (high-intensity, >3 m/s², by position) — see docs for the exact reference;
  Di Salvo (2007) predates modern accel/decel GPS metrics entirely.
- **Goalkeeper** numbers are a rough estimate — GK physical demands are
  consistently reported as understudied in the position-specific literature
  (multiple papers explicitly exclude goalkeepers), so there's no comparable
  study to cite here. Treat these as directional, not a precise target.
- **Top speed** is NOT split by position — no reliable published per-position
  peak-speed dataset was found (most published "fastest players" data is
  individual records, not position averages), so one reference value is used
  for all outfield positions, and a lower one for goalkeepers.
- **Training** baselines are *derived*, not directly cited: literature
  consistently shows training sessions are meaningfully lower-intensity than
  matches (especially for high-speed running and sprinting), but no
  position-specific training-vs-match ratio study was found. `TRAINING_RATIO`
  applies one flat, documented estimate per metric to the match baseline. This
  is the least rigorous part of this module — flagged as such deliberately.
"""

from __future__ import annotations

POSITIONS = ["goalkeeper", "center_back", "full_back", "central_midfielder", "wide_midfielder", "forward"]

POSITION_LABELS = {
    "goalkeeper": "Goalkeeper",
    "center_back": "Center Back",
    "full_back": "Full Back / Wing Back",
    "central_midfielder": "Central Midfielder",
    "wide_midfielder": "Wide Midfielder / Winger",
    "forward": "Forward",
}

BASELINE_METRICS_KEYS = frozenset(
    {"total_distance_m", "high_speed_distance_m", "sprint_distance_m", "accelerations", "decelerations", "top_speed_kmh"}
)

_OUTFIELD_TOP_SPEED_KMH = 32.0
_GOALKEEPER_TOP_SPEED_KMH = 26.0

# Official-match, per-90-minute (i.e. per full match) baselines.
# total_distance_m / high_speed_distance_m / sprint_distance_m: Di Salvo et al. (2007).
# accelerations / decelerations (high-intensity, >3 m/s^2, per match): see docs/gps_analysis.md.
OFFICIAL_MATCH_BASELINES: dict[str, dict[str, float]] = {
    "goalkeeper": {
        "total_distance_m": 5000,  # rough estimate -- see module docstring
        "high_speed_distance_m": 30,
        "sprint_distance_m": 10,
        "accelerations": 15,
        "decelerations": 15,
        "top_speed_kmh": _GOALKEEPER_TOP_SPEED_KMH,
    },
    "center_back": {
        "total_distance_m": 10627,
        "high_speed_distance_m": 612,  # 397 (19.1-23 km/h) + 215 (>23 km/h)
        "sprint_distance_m": 215,
        "accelerations": 26.5,
        "decelerations": 50.9,
        "top_speed_kmh": _OUTFIELD_TOP_SPEED_KMH,
    },
    "full_back": {
        "total_distance_m": 11410,
        "high_speed_distance_m": 1054,  # 652 + 402
        "sprint_distance_m": 402,
        "accelerations": 30.4,
        "decelerations": 54.1,
        "top_speed_kmh": _OUTFIELD_TOP_SPEED_KMH,
    },
    "central_midfielder": {
        "total_distance_m": 12027,
        "high_speed_distance_m": 875,  # 627 + 248
        "sprint_distance_m": 248,
        "accelerations": 27.1,
        "decelerations": 54.8,
        "top_speed_kmh": _OUTFIELD_TOP_SPEED_KMH,
    },
    "wide_midfielder": {
        "total_distance_m": 11990,
        "high_speed_distance_m": 1184,  # 738 + 446
        "sprint_distance_m": 446,
        "accelerations": 34.9,
        "decelerations": 64.5,
        "top_speed_kmh": _OUTFIELD_TOP_SPEED_KMH,
    },
    "forward": {
        "total_distance_m": 11254,
        "high_speed_distance_m": 1025,  # 621 + 404
        "sprint_distance_m": 404,
        "accelerations": 29.9,
        "decelerations": 55.2,
        "top_speed_kmh": _OUTFIELD_TOP_SPEED_KMH,
    },
}

# Estimated training-vs-match intensity ratio, applied uniformly across positions
# (see module docstring — this is the least rigorous part; no position-specific
# training/match study was found).
TRAINING_RATIO: dict[str, float] = {
    "total_distance_m": 0.70,
    "high_speed_distance_m": 0.45,
    "sprint_distance_m": 0.35,
    "accelerations": 0.75,
    "decelerations": 0.75,
    "top_speed_kmh": 0.95,
}


def training_baseline(position: str) -> dict[str, float]:
    match = OFFICIAL_MATCH_BASELINES[position]
    return {metric: round(value * TRAINING_RATIO[metric], 1) for metric, value in match.items()}


def get_baseline(category: str, position: str) -> dict[str, float]:
    """``category``: "training" / "official_match" / "practice_match".

    Practice matches ("Jogo Treino" friendlies) fall back to the official-match
    baseline for the position — a friendly's physical demands are closer to a
    real match than to a training session, even if the opposition is weaker.
    """
    if position not in OFFICIAL_MATCH_BASELINES:
        raise ValueError(f"Unknown position '{position}'. Choose from: {', '.join(POSITIONS)}")
    if category == "training":
        return training_baseline(position)
    return dict(OFFICIAL_MATCH_BASELINES[position])
