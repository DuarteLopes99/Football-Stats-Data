"""Gauge/meter visualizations for the GPS dashboard, built on
``plotly.graph_objects.Indicator``. Not a SkillCorner chart type (their
standard plots are bar/radar/scatter/violin/table) — matplotlib has no clean
gauge support, so this is a separate, Plotly-based module.

Every function returns a ``go.Figure`` for ``st.plotly_chart(fig)``.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

RISK_COLORS = {"low": "#f1c40f", "good": "#2ecc71", "elevated": "#e67e22", "high": "#e74c3c"}


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
    """Generic gauge. ``zones`` is a list of (low, high, color) colored bands.
    ``target`` draws a threshold line and a delta-from-target readout.
    """
    gauge_spec = {
        "axis": {"range": [min_val, max_val]},
        "bar": {"color": "#2c3e50"},
        "steps": [{"range": [low, high], "color": color} for low, high, color in (zones or [])],
    }
    if target is not None:
        gauge_spec["threshold"] = {"line": {"color": "black", "width": 3}, "thickness": 0.8, "value": target}

    indicator = {
        "mode": "gauge+number" + ("+delta" if target is not None else ""),
        "value": value,
        "number": {"suffix": suffix},
        "title": {"text": title, "font": {"size": 14}},
        "gauge": gauge_spec,
    }
    if target is not None:
        indicator["delta"] = {"reference": target}

    fig = go.Figure(go.Indicator(**indicator))
    fig.update_layout(height=height, margin={"l": 25, "r": 25, "t": 50, "b": 10})
    return fig


def acwr_gauge(value: float) -> go.Figure:
    """Acute:Chronic Workload Ratio — Gabbett (2016) injury-risk zones."""
    zones = [
        (0.0, 0.8, RISK_COLORS["low"]),
        (0.8, 1.3, RISK_COLORS["good"]),
        (1.3, 1.5, RISK_COLORS["elevated"]),
        (1.5, 2.0, RISK_COLORS["high"]),
    ]
    return gauge_figure(value, "ACWR (Injury Risk)", min_val=0, max_val=2.0, zones=zones, target=1.0)


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
    ceiling = max(personal_best * 1.05, value * 1.05 if value else 0, 35)
    warn_at = personal_best * 0.85
    good_at = personal_best * 0.95
    zones = [
        (0, warn_at, RISK_COLORS["high"]),
        (warn_at, good_at, RISK_COLORS["elevated"]),
        (good_at, ceiling, RISK_COLORS["good"]),
    ]
    return gauge_figure(value, "Robust Top Speed (km/h)", min_val=0, max_val=math.ceil(ceiling), zones=zones, target=personal_best)
