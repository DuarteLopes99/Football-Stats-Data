"""Single source of truth for the GPS report: column mapping, units, thresholds,
colours and fonts.

Nothing in the chart, metric or layout code hardcodes a threshold or a colour —
it reads it from here. Changing a cut-off, a band or a colour is a one-line edit
in this file, and ``tests/test_gps_config.py`` checks that the Streamlit theme
file (``.streamlit/config.toml``) still agrees with ``THEME`` below.

**Data provenance.** The GPS unit is a STATSports device. Its export lives in a
workbook that always sits *outside* the repo (``SOURCE_XLSX``);
``data/gps/gps_sessions.csv`` is a tidy sub-product of that workbook, rebuilt with
``python -m football_stats.gps.sync``. The dashboard only ever reads the CSV.

**Speed and acceleration bands follow the STATSports definitions**, which the
workbook's own sub-header row confirms for accelerations (``Acc + 3m/s``):

- High-Speed Running distance = distance above 19.8 km/h (5.5 m/s), **sprinting
  included** — so ``high_speed_distance_m`` already *is* "HSR & Sprint".
- Sprint distance = distance above 25.2 km/h (7 m/s).
- Accelerations / decelerations = efforts above +3 / below −3 m/s².

These are the device's bands. The export holds per-session totals only, so the
bands can be documented but not recomputed with a different threshold.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from football_stats.config import REPO_ROOT

# --------------------------------------------------------------------------- #
# Data source
# --------------------------------------------------------------------------- #

SOURCE_XLSX = Path(
    os.environ.get("FOOTBALL_GPS_XLSX", REPO_ROOT.parent / "SATS_Football_GPS_Advanced.xlsx")
)
"""The STATSports export workbook. Outside the repo by design; override the
location with the ``FOOTBALL_GPS_XLSX`` environment variable."""

PLAYER = {
    "name": "Duarte",
    "position": "Right Back / Right Wing Back",
    "baseline_position": "full_back",  # key into gps.position_baselines.POSITIONS
}

# --------------------------------------------------------------------------- #
# Session types
# --------------------------------------------------------------------------- #

TRAINING = "training"
OFFICIAL_MATCH = "official_match"
PRACTICE_MATCH = "practice_match"
SESSION_CATEGORIES = [TRAINING, OFFICIAL_MATCH, PRACTICE_MATCH]

OFFICIAL_COMPETITION_TYPES = ("Campeonato", "Taça")
"""``competition_type`` values that make a game an official match. Everything
else with ``session_kind == "game"`` (``"Treino"``) is a friendly."""

SESSION_CATEGORY_LABELS = {
    TRAINING: "Training",
    OFFICIAL_MATCH: "Official match",
    PRACTICE_MATCH: "Practice match",
}

SESSION_TYPE_FILTERS = {
    "All sessions": SESSION_CATEGORIES,
    "Official matches": [OFFICIAL_MATCH],
    "Training": [TRAINING],
    "Practice matches (friendlies)": [PRACTICE_MATCH],
}
"""The report's global session-type filter. Friendlies get their own option
rather than being folded into "Matches": they are practice with a scoreline, and
pooling them with official matches would mix the two loads the report is built
to keep apart."""

# --------------------------------------------------------------------------- #
# Metrics — column mapping, units and how each one aggregates
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MetricSpec:
    key: str
    """Column name in the prepared session frame (see ``gps.cleaning``)."""
    label: str
    short: str
    unit: str
    period_agg: str
    """How a period (a week, a filter range) aggregates it: ``"sum"`` for
    volumes and counts, ``"max"`` for peaks, ``"mean"`` for rates."""
    decimals: int = 0
    rate: bool = False
    """Rates (per-minute values) are inflated by very short appearances, so
    Gref ignores appearances under ``SHORT_APPEARANCE_MIN`` for them."""


METRICS: dict[str, MetricSpec] = {
    m.key: m
    for m in [
        MetricSpec("total_distance_m", "Total Distance", "TD", "m", "sum"),
        MetricSpec("hsr_sprint_m", "HSR & Sprint", "HSR+SPR", "m", "sum"),
        MetricSpec("hsr_m", "HSR (19.8–25.2 km/h)", "HSR", "m", "sum"),
        MetricSpec("sprint_distance_m", "Sprint Distance", "SPR", "m", "sum"),
        MetricSpec("top_speed_kmh", "Max Speed", "Vmax", "km/h", "max", decimals=1),
        MetricSpec("accelerations", "Accelerations", "Acc", "#", "sum"),
        MetricSpec("decelerations", "Decelerations", "Dec", "#", "sum"),
        MetricSpec("sprints_total", "Sprints", "Spr #", "#", "sum"),
        MetricSpec("hia", "High-Intensity Actions", "HIA", "#", "sum"),
        MetricSpec("m_per_min", "Distance per Minute", "m/min", "m/min", "mean", decimals=1, rate=True),
        MetricSpec("duration_min", "Duration", "Min", "min", "sum"),
    ]
}

REPORT_METRICS = ["total_distance_m", "hsr_sprint_m", "top_speed_kmh", "hia", "m_per_min"]
"""Columns of the Weekly Change % table and the KPI cards, in display order.

The reference report's fifth column is Training Load. This export has no load
metric (no Player Load, DSL or HML — only a calorie estimate, which is not one),
so the slot goes to Distance per Minute: the brief's intensity metric, and the
one thing the four volume/peak columns cannot show."""

BIG_NUMBER_METRICS = {"top_speed_kmh"}
"""KPI cards that show a big plain number instead of a gauge."""

FOCUS_METRICS = ["total_distance_m", "hsr_sprint_m", "sprint_distance_m", "hia", "accelerations", "decelerations"]
"""Options for the sidebar's focus-metric selector (load chart, microcycle
profile, per-session demand). Only summable metrics — weekly load and ACWR are
defined over sums."""

HIA_COMPONENTS = ("accelerations", "decelerations", "sprints_total")
"""High-Intensity Actions = accelerations + decelerations + sprint count."""

CORE_GPS_COLUMNS = (
    "total_distance_m", "high_speed_distance_m", "sprint_distance_m",
    "top_speed_kmh", "accelerations", "decelerations",
)
"""A session with none of these recorded has no GPS data, whatever its duration."""

# --------------------------------------------------------------------------- #
# Device bands (STATSports) — documented, not recomputable from session totals
# --------------------------------------------------------------------------- #

HSR_MIN_KMH = 19.8
SPRINT_MIN_KMH = 25.2
HSR_INCLUDES_SPRINT = True
"""STATSports' high-speed distance is everything above 19.8 km/h, sprinting
included. True means ``hsr_sprint_m = high_speed_distance_m`` and the
19.8–25.2 band is ``high_speed_distance_m − sprint_distance_m``. Set False only
if a future export reports the bands disjointly."""
ACC_THRESHOLD_MS2 = 3.0
DEC_THRESHOLD_MS2 = -3.0

# --------------------------------------------------------------------------- #
# Appearances
# --------------------------------------------------------------------------- #

SHORT_APPEARANCE_MIN = 20.0
"""Official minutes below which a per-minute or per-90 rate is extrapolation.
A 9-minute cameo covering 2070 m is 20 700 m per 90 — a match nobody plays."""

SECOND_HALF_MIN_MINUTES = 50.0
"""Minutes on the pitch before a second-half sprint count means anything —
three 45-minute appearances otherwise read as total second-half collapse."""

LARGE_OVERHANG_MIN = 10.0
UNDER_RECORDING_MIN = -5.0

# --------------------------------------------------------------------------- #
# Match-day (MD) labelling — Ravé et al. (2020) microcycle convention
# --------------------------------------------------------------------------- #

MD_ANCHOR_CATEGORIES = (OFFICIAL_MATCH,)
"""Only official matches anchor a microcycle. Friendlies sit inside the week
like any other session and get an MD label from the official matches around
them."""

MD_PLUS_MAX_DAYS = 2
"""Sessions up to this many days after a match are labelled from it (MD+1,
MD+2 — the recovery days). Every later session is labelled by the days left to
the next match (MD-4 … MD-1), as in Ravé et al.'s Figure 1."""

PRESEASON_LABEL = "PRE"
PRESEASON_LEAD_DAYS = 6
"""Before a season's first official match, sessions within this many days of it
are its MD-n build-up; earlier ones are pre-season and labelled ``PRE``."""

EXTENDED_MICROCYCLE_DAYS = 10
"""A microcycle longer than this (a winter break, a free weekend) is flagged:
its MD-n labels count down from much further out than a normal week's."""

# --------------------------------------------------------------------------- #
# Match reference (Gref)
# --------------------------------------------------------------------------- #

GREF_TOP_N = 5
"""Gref = mean of the best ``GREF_TOP_N`` official-match values, per metric."""

# --------------------------------------------------------------------------- #
# Weekly change %
# --------------------------------------------------------------------------- #

CHANGE_MODES = {
    "previous_microcycle": "vs same MD day, previous microcycle",
    "gref": "vs match reference (Gref)",
}
DEFAULT_CHANGE_MODE = "previous_microcycle"

HEATMAP_STOPS = [
    (0.0, "#22B14C"),   # green  — within the ~10 %/week progression guideline
    (5.0, "#22B14C"),
    (15.0, "#E9C21B"),  # amber  — 10–20 %
    (25.0, "#EE8A2A"),  # orange — 20–30 %
    (35.0, "#D9433F"),  # red    — above 30 %
]
"""Cell colour by **absolute** % change. Anchors sit at the band centres, so the
scale interpolates continuously between them (10 % reads halfway green→amber).
``HEATMAP_CONTINUOUS = False`` snaps to the four flat bands instead."""
HEATMAP_CONTINUOUS = True
HEATMAP_BANDS = [(10.0, "#22B14C"), (20.0, "#E9C21B"), (30.0, "#EE8A2A"), (float("inf"), "#D9433F")]
HEATMAP_EMPTY = "#1F1F1F"

WEEKLY_PROGRESSION_GUIDE_PCT = 10.0
"""Ravé et al. (2020): week-on-week load increases of about 10 % keep
progression safe. Larger weekly increases are highlighted on the load chart."""

# --------------------------------------------------------------------------- #
# Weekly load and ACWR
# --------------------------------------------------------------------------- #

WEEK_FREQ = "W-SAT"
"""Calendar weeks running Sunday → Saturday. Microcycles here range from 6 to
21 days, which would distort an acute:chronic ratio, so ACWR uses fixed weeks —
and Sunday starts line them up with the usual Sunday match day."""

ACWR_METHOD = "rolling"
"""``"rolling"``: acute = this week's load, chronic = mean of the previous
``ACWR_CHRONIC_WEEKS`` weeks (uncoupled — the acute week is not inside its own
baseline). ``"ewma"``: exponentially weighted daily loads (Williams et al.
2017), acute span 7 days, chronic span 28, read at the end of each week."""
ACWR_CHRONIC_WEEKS = 4
ACWR_EWMA_ACUTE_DAYS = 7
ACWR_EWMA_CHRONIC_DAYS = 28
ACWR_MIN_HISTORY_WEEKS = 4
"""No ratio until this many full weeks precede the week being rated."""
ACWR_SAFE_BAND = (0.8, 1.5)
ACWR_CAPTION = "ACWR is a monitoring indicator, not an injury predictor."

ACWR_ZONES = [
    (0.0, ACWR_SAFE_BAND[0], "Below range"),
    (ACWR_SAFE_BAND[0], ACWR_SAFE_BAND[1], "Within range"),
    (ACWR_SAFE_BAND[1], float("inf"), "Above range"),
]

MONOTONY_CAUTION_LEVEL = 2.0

# --------------------------------------------------------------------------- #
# Other analysis thresholds (Physical Profile / Performance Insights)
# --------------------------------------------------------------------------- #

BALANCED_ACCEL_DECEL = (0.8, 1.25)
NEAR_MAX_SPEED_PCT = 0.90
ROBUST_SPEED_WINDOW = 10
ROBUST_SPEED_PERCENTILE = 95
QUALITY_TRAINING_WEIGHT = 0.6
QUALITY_MATCH_WEIGHT = 0.4

# --------------------------------------------------------------------------- #
# Theme — colours and fonts
# --------------------------------------------------------------------------- #

THEME = {
    "background": "#000000",
    "surface": "#0B0B0B",
    "surface_raised": "#141414",
    "text": "#FFFFFF",
    "text_secondary": "#C3C2B7",
    "text_muted": "#898781",
    "text_on_light": "#0B0B0B",
    "accent": "#3ADBC8",
    "accent_text": "#04201D",
    "grid": "#262626",
    "axis": "#383835",
    "border": "rgba(255,255,255,0.10)",
}

FONT_FAMILY = '"DIN Alternate", "DIN Condensed", "Barlow", "Helvetica Neue", Arial, sans-serif'
"""System fonts only (DIN ships with macOS) — no web-font request leaves the
machine."""
TITLE_FONT_FAMILY = '"DIN Condensed", "DIN Alternate", "Barlow Condensed", "Helvetica Neue", Arial, sans-serif'

SESSION_COLORS = {
    TRAINING: "#3987E5",        # blue
    OFFICIAL_MATCH: "#D95926",  # orange
    PRACTICE_MATCH: "#199E70",  # aqua
}
"""One colour per session type, used everywhere they are distinguished. The
first three dark-mode slots of the validated reference palette (all pairs
separable under colour-vision deficiency on a dark surface); every chart that
uses them also labels the type in its legend or tooltip."""

GAUGE = {
    "fill": "#3987E5",
    "track": "#E6E6E6",
    "marker": SESSION_COLORS[OFFICIAL_MATCH],
}
"""Semicircle gauges: blue fill on a light-grey track. The Gref marker wears the
official-match colour because Gref *is* the official-match reference."""
GAUGE_MAX_MULTIPLIER = 2.0
"""Gauge range = 0 … max(GAUGE_MAX_MULTIPLIER × Gref, value)."""

ACWR_COLORS = {
    "band": "rgba(12,163,12,0.22)",
    "line": THEME["text"],
    "in_band": "#0CA30C",
    "out_of_band": "#D03B3B",
}
LOAD_BAR_COLOR = "#5A6B7D"
"""Weekly load bars: neutral, so the 10 % flag (below) is the only thing that pops."""
LOAD_SPIKE_COLOR = "#FAB219"
"""Weeks whose load rose more than ``WEEKLY_PROGRESSION_GUIDE_PCT`` on the previous week."""
REFERENCE_LINE_COLOR = THEME["text_secondary"]
DEMAND_SEQUENTIAL = ["#0D366B", "#1C5CAB", "#3987E5", "#86B6EF", "#CDE2FB"]
"""Session table: % of Gref, one-hue blue ramp, dark (low) → light (≥100 %)."""

STATUS_COLORS = {"good": "#0CA30C", "warning": "#FAB219", "serious": "#EC835A", "critical": "#D03B3B"}
VERDICT_COLORS = {
    "better": "rgba(12,163,12,0.22)",
    "worse": "rgba(208,59,59,0.22)",
    "noise": "rgba(137,135,129,0.14)",
    "neutral": "",
}
