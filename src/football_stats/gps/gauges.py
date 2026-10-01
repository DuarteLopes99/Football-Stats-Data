"""Zoned gauges for the "More analysis" page (ACWR, monotony, strain, quality,
percentile, intensity, top speed), built on ``plotly.graph_objects.Indicator``.

The report's own KPI gauges (blue fill, Gref marker) live in ``gps.charts``.
Zone colours are the reserved status colours from ``gps.config``; every gauge
also prints its number, so no zone is read from colour alone.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

from football_stats.gps import config as cfg
from football_stats.gps.charts import TEMPLATE

RISK_COLORS = {
    "low": cfg.STATUS_COLORS["warning"],
    "good": cfg.STATUS_COLORS["good"],
    "elevated": cfg.STATUS_COLORS["serious"],
    "high": cfg.STATUS_COLORS["critical"],
}
_TRACK_ALPHA = "55"  # zones drawn translucent so the value bar stays the loudest mark


def gauge_figure(
    value: float,
    title: str,
    min_val: float = 0,
    max_val: float = 100,
    zones: list[tuple[float, float, str]] | None = None,
    suffix: str = "",
    target: float | None = None,
    height: int = 220,
) -> go.Figure:
    """Generic gauge. ``zones`` is a list of (low, high, color) bands; ``target``
    draws a marker line and a delta-from-target readout."""
    gauge_spec = {
        "axis": {"range": [min_val, max_val], "tickcolor": cfg.THEME["axis"], "tickfont": {"color": cfg.THEME["text_muted"]}},
        "bar": {"color": cfg.THEME["text"], "thickness": 0.28},
        "bgcolor": cfg.THEME["surface_raised"],
        "borderwidth": 0,
        "steps": [{"range": [low, high], "color": color + _TRACK_ALPHA} for low, high, color in (zones or [])],
    }
    if target is not None:
        gauge_spec["threshold"] = {"line": {"color": cfg.THEME["accent"], "width": 3}, "thickness": 0.9, "value": target}

    indicator = {
        "mode": "gauge+number" + ("+delta" if target is not None else ""),
        "value": value,
        "number": {"suffix": suffix, "font": {"color": cfg.THEME["text"]}},
        "title": {"text": title, "font": {"size": 14, "color": cfg.THEME["text_secondary"]}},
        "gauge": gauge_spec,
    }
    if target is not None:
        indicator["delta"] = {"reference": target}

    fig = go.Figure(go.Indicator(**indicator))
    fig.update_layout(template=TEMPLATE, height=height, margin={"l": 25, "r": 25, "t": 50, "b": 10})
    return fig


def acwr_gauge(value: float) -> go.Figure:
    """ACWR against the configured safe band (default 0.8–1.5)."""
    low, high = cfg.ACWR_SAFE_BAND
    zones = [(0.0, low, RISK_COLORS["low"]), (low, high, RISK_COLORS["good"]), (high, 2.0, RISK_COLORS["high"])]
    return gauge_figure(value, "ACWR (latest rated week)", min_val=0, max_val=max(2.0, value or 0), zones=zones, target=1.0)


def monotony_gauge(value: float) -> go.Figure:
    """Foster (1998) Training Monotony — ~2.0+ with a high weekly load is a caution point."""
    caution = cfg.MONOTONY_CAUTION_LEVEL
    zones = [(0.0, caution, RISK_COLORS["good"]), (caution, caution + 1, RISK_COLORS["elevated"]), (caution + 1, caution + 2, RISK_COLORS["high"])]
    return gauge_figure(value, "Training Monotony", min_val=0, max_val=caution + 2, zones=zones, target=caution)


def strain_gauge(value: float, typical: float) -> go.Figure:
    """Foster (1998) Training Strain, scaled to the athlete's own typical week."""
    ceiling = max(typical * 2.0, value * 1.1 if value else 0, 1.0)
    return gauge_figure(value, "Training Strain", min_val=0, max_val=ceiling, zones=None, target=typical)


def quality_gauge(value: float) -> go.Figure:
    zones = [(0, 60, RISK_COLORS["high"]), (60, 80, RISK_COLORS["elevated"]), (80, 100, RISK_COLORS["good"])]
    return gauge_figure(value, "Quality Score", min_val=0, max_val=100, zones=zones)


def intensity_gauge(value: float, label: str, max_val: float = 30) -> go.Figure:
    zones = [
        (0, max_val * 0.4, RISK_COLORS["high"]),
        (max_val * 0.4, max_val * 0.7, RISK_COLORS["elevated"]),
        (max_val * 0.7, max_val, RISK_COLORS["good"]),
    ]
    return gauge_figure(value, label, min_val=0, max_val=max_val, zones=zones, suffix="%")


def percentile_gauge(value: float, label: str) -> go.Figure:
    zones = [(0, 33, RISK_COLORS["high"]), (33, 66, RISK_COLORS["elevated"]), (66, 100, RISK_COLORS["good"])]
    return gauge_figure(value, label, min_val=0, max_val=100, zones=zones)


def top_speed_gauge(value: float, personal_best: float) -> go.Figure:
    ceiling = max(personal_best * 1.05, value * 1.05 if value else 0)
    warn_at = personal_best * (cfg.NEAR_MAX_SPEED_PCT - 0.05)
    good_at = personal_best * (cfg.NEAR_MAX_SPEED_PCT + 0.05)
    zones = [(0, warn_at, RISK_COLORS["high"]), (warn_at, good_at, RISK_COLORS["elevated"]), (good_at, ceiling, RISK_COLORS["good"])]
    return gauge_figure(value, "Robust Top Speed (km/h)", min_val=0, max_val=math.ceil(ceiling), zones=zones, target=personal_best)
