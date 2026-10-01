"""Chart builders for the GPS report — Plotly figures and small HTML pieces.

Every colour, threshold and font comes from ``gps.config``. Builders take
already-computed frames (from ``weekly_change``, ``load_monitoring``,
``reference``) and only draw; no metric is calculated here.

Design rules applied throughout: one y-axis per panel (load and ACWR are two
stacked panels sharing the date axis, not one dual-axis plot), hairline grid,
session type always named in a legend or tooltip as well as coloured, and a
hover tooltip on every mark.
"""

from __future__ import annotations

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from football_stats.gps import config as cfg
from football_stats.gps.microcycle import md_order, ordered_labels

T = cfg.THEME

pio.templates["gps_dark"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=T["surface"],
        plot_bgcolor=T["surface"],
        font={"family": cfg.FONT_FAMILY, "color": T["text_secondary"], "size": 13},
        colorway=[cfg.SESSION_COLORS[c] for c in cfg.SESSION_CATEGORIES],
        xaxis={"gridcolor": T["grid"], "linecolor": T["axis"], "zerolinecolor": T["axis"], "tickcolor": T["axis"], "showgrid": False},
        yaxis={"gridcolor": T["grid"], "linecolor": T["axis"], "zerolinecolor": T["axis"], "tickcolor": T["axis"]},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0, "bgcolor": "rgba(0,0,0,0)",
                "font": {"color": T["text_secondary"]}},
        hoverlabel={"bgcolor": T["surface_raised"], "bordercolor": T["axis"], "font": {"family": cfg.FONT_FAMILY, "color": T["text"]}},
        margin={"l": 56, "r": 20, "t": 36, "b": 40},
        bargap=0.25,
        separators=". ",
    )
)
TEMPLATE = "gps_dark"
PLOTLY_CONFIG = {"displayModeBar": False}


# --------------------------------------------------------------------------- #
# Colour helpers
# --------------------------------------------------------------------------- #


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(round(c)) for c in rgb))


def _interpolate(stops: list[tuple[float, str]], x: float) -> str:
    if x <= stops[0][0]:
        return stops[0][1]
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x <= x1:
            t = (x - x0) / (x1 - x0) if x1 > x0 else 0
            a, b = np.array(_rgb(c0)), np.array(_rgb(c1))
            return _hex(a + (b - a) * t)
    return stops[-1][1]


def heat_color(pct: float) -> str:
    """Weekly-change cell colour for a signed % change (coloured on |pct|)."""
    if pct is None or pd.isna(pct):
        return cfg.HEATMAP_EMPTY
    magnitude = abs(float(pct))
    if cfg.HEATMAP_CONTINUOUS:
        return _interpolate(cfg.HEATMAP_STOPS, magnitude)
    for upper, color in cfg.HEATMAP_BANDS:
        if magnitude <= upper:
            return color
    return cfg.HEATMAP_BANDS[-1][1]


def demand_color(pct_of_gref: float) -> str:
    """Sequential blue for % of Gref: dark (low) → light (≥ 100 %)."""
    if pct_of_gref is None or pd.isna(pct_of_gref):
        return cfg.HEATMAP_EMPTY
    ramp = cfg.DEMAND_SEQUENTIAL
    stops = [(i * 100 / (len(ramp) - 1), c) for i, c in enumerate(ramp)]
    return _interpolate(stops, min(max(float(pct_of_gref), 0.0), 100.0))


def readable_text(background: str) -> str:
    """Dark or light ink, whichever has more contrast on ``background``."""
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(background))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    contrast_white = 1.05 / (luminance + 0.05)
    contrast_dark = (luminance + 0.05) / 0.05
    return T["text"] if contrast_white >= contrast_dark else T["text_on_light"]


def _fmt(value, spec: cfg.MetricSpec) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{spec.decimals}f}".replace(",", " ")


def _category_label(category: str) -> str:
    return cfg.SESSION_CATEGORY_LABELS.get(category, category)


# --------------------------------------------------------------------------- #
# Weekly Change % table (HTML)
# --------------------------------------------------------------------------- #


def weekly_change_table_html(rows: pd.DataFrame, metrics: list[str], mode: str, max_height: int = 420) -> str:
    """The hero table: one row per session, one heat-coloured % cell per metric.

    Fallback comparisons carry a small dot and say so in the cell tooltip.
    Rows without GPS data stay in the table with empty cells, so the log is
    complete and the gap is visible.
    """
    header_cells = "".join(f"<th>{html.escape(cfg.METRICS[m].label)}</th>" for m in metrics)
    body = []
    for _, row in rows.sort_values("date", ascending=False).iterrows():
        category = row["match_category"]
        chip = (
            f'<span class="gps-chip"><i style="background:{cfg.SESSION_COLORS[category]}"></i>'
            f"{html.escape(_category_label(category))}</span>"
        )
        status = ""
        if row.get("unused_sub"):
            status = '<span class="gps-note">unused sub</span>'
        elif not row.get("has_gps", True):
            status = '<span class="gps-note">no GPS data</span>'
        elif row.get("short_appearance"):
            status = f'<span class="gps-note">{row["minutes_played"]:.0f} min</span>'

        cells = []
        for metric in metrics:
            spec = cfg.METRICS[metric]
            pct = row.get(f"{metric}_pct")
            bg = heat_color(pct)
            ink = readable_text(bg) if pd.notna(pct) else T["text_muted"]
            text = "—" if pd.isna(pct) else f"{pct:+.0f}%"
            base_value = row.get(f"{metric}_base")
            if mode == "gref":
                basis = f"vs Gref {_fmt(base_value, spec)} {spec.unit}"
            elif pd.notna(row.get("compare_date")):
                basis = f"vs {row['compare_date']:%d %b} ({row['compare_md_label']}) {_fmt(base_value, spec)} {spec.unit}"
            else:
                basis = f"no earlier {_category_label(category).lower()} to compare with"
            tip = f"{spec.label}: {_fmt(row.get(metric), spec)} {spec.unit} · {basis}"
            marker = '<sup class="gps-fallback">●</sup>' if row.get("fallback") and pd.notna(pct) else ""
            cells.append(f'<td style="background:{bg};color:{ink}" title="{html.escape(tip)}">{text}{marker}</td>')

        body.append(
            f'<tr><td class="gps-date">{row["date"]:%d %b %Y}</td><td class="gps-md">{html.escape(str(row["md_label"]))}</td>'
            f"<td>{chip}{status}</td>{''.join(cells)}</tr>"
        )

    if not body:
        body.append(f'<tr><td colspan="{3 + len(metrics)}" class="gps-empty">No sessions in the selected range.</td></tr>')

    return (
        f'<div class="gps-card"><div class="gps-card-header">Weekly Change % GPS Report</div>'
        f'<div class="gps-table-wrap" style="max-height:{max_height}px"><table class="gps-table">'
        f"<thead><tr><th>Date</th><th>MD</th><th>Session</th>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div></div>"
    )


def heat_legend_html() -> str:
    swatches = []
    edges = [0] + [b for b, _ in cfg.HEATMAP_BANDS[:-1]]
    for i, (upper, _) in enumerate(cfg.HEATMAP_BANDS):
        lower = edges[i]
        mid = (lower + (upper if np.isfinite(upper) else lower + 10)) / 2
        label = f"≤ {upper:.0f}%" if i == 0 else (f"> {lower:.0f}%" if not np.isfinite(upper) else f"{lower:.0f}–{upper:.0f}%")
        swatches.append(f'<span class="gps-swatch"><i style="background:{heat_color(mid)}"></i>{label}</span>')
    return '<div class="gps-legend">|change| ' + "".join(swatches) + '<span class="gps-swatch"><sup class="gps-fallback">●</sup> fallback basis</span></div>'


# --------------------------------------------------------------------------- #
# KPI gauge cards
# --------------------------------------------------------------------------- #


def gauge_figure(value: float | None, gref: float | None, spec: cfg.MetricSpec, height: int = 190) -> go.Figure:
    """Semicircle gauge: blue fill on a grey track, Gref marker, 0/max under the ends.

    Range is ``0 … max(GAUGE_MAX_MULTIPLIER × Gref, value)`` so a value above
    twice the match reference still fits.
    """
    value = None if value is None or pd.isna(value) else float(value)
    ceiling = max((gref or 0) * cfg.GAUGE_MAX_MULTIPLIER, value or 0) or 1.0
    gauge = {
        "shape": "angular",
        "axis": {"range": [0, ceiling], "visible": False},
        "bar": {"color": cfg.GAUGE["fill"], "thickness": 1.0},
        "bgcolor": cfg.GAUGE["track"],
        "borderwidth": 0,
    }
    if gref:
        gauge["threshold"] = {"line": {"color": cfg.GAUGE["marker"], "width": 4}, "thickness": 1.0, "value": gref}
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value if value is not None else 0,
            number={"valueformat": f",.{spec.decimals}f", "font": {"size": 34, "color": T["text"], "family": cfg.FONT_FAMILY}},
            gauge=gauge,
            domain={"x": [0.06, 0.94], "y": [0.12, 1]},
        )
    )
    for x, text in ((0.08, "0"), (0.92, _fmt(ceiling, spec))):
        fig.add_annotation(x=x, y=0.0, xref="paper", yref="paper", text=text, showarrow=False,
                           font={"color": T["text_secondary"], "size": 14})
    fig.update_layout(template=TEMPLATE, height=height, margin={"l": 8, "r": 8, "t": 8, "b": 8},
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def kpi_caption_html(value, gref, spec: cfg.MetricSpec, basis: str) -> str:
    share = f"{value / gref * 100:.0f}% of Gref" if gref and value is not None and pd.notna(value) else "no Gref"
    unit = "" if spec.unit == "#" else f" {spec.unit}"
    gref_text = f"Gref {_fmt(gref, spec)}{unit}" if gref else "Gref —"
    return (
        f'<div class="gps-kpi-foot"><span>{basis}</span>'
        f'<span><i class="gps-marker"></i>{gref_text} · {share}</span></div>'
    )


def big_number_html(value, spec: cfg.MetricSpec, gref=None) -> str:
    gref_text = f"Gref {_fmt(gref, spec)} {spec.unit}" if gref else ""
    return (
        f'<div class="gps-bignum">{_fmt(value, spec)}<small>{spec.unit}</small></div>'
        f'<div class="gps-kpi-foot"><span>peak in range</span><span>{gref_text}</span></div>'
    )


# --------------------------------------------------------------------------- #
# Weekly load + ACWR (two panels, shared date axis)
# --------------------------------------------------------------------------- #


def load_acwr_figure(weekly: pd.DataFrame, spec: cfg.MetricSpec, categories: list[str], height: int = 520) -> go.Figure:
    """Top: weekly load stacked by session type, >10 % rises flagged.
    Bottom: ACWR with the safe band shaded and out-of-band weeks in red.

    Session types outside the current filter are drawn faded rather than
    removed: ACWR is computed on the whole load, so the bars stay whole too.
    """
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4], vertical_spacing=0.08)
    x = weekly["week_start"]
    hover_week = weekly["week_start"].dt.strftime("%d %b") + " – " + weekly["week_end"].dt.strftime("%d %b")

    for category in cfg.SESSION_CATEGORIES:
        column = f"load_{category}"
        if column not in weekly or weekly[column].sum() == 0:
            continue
        fig.add_trace(
            go.Bar(
                x=x, y=weekly[column], name=_category_label(category),
                marker={"color": cfg.SESSION_COLORS[category], "line": {"color": T["surface"], "width": 1}},
                opacity=1.0 if category in categories else 0.25,
                customdata=np.stack([hover_week, weekly["load"]], axis=-1),
                hovertemplate=f"%{{customdata[0]}}<br>{_category_label(category)}: %{{y:,.0f}} {spec.unit}"
                              f"<br>Week total: %{{customdata[1]:,.0f}} {spec.unit}<extra></extra>",
            ),
            row=1, col=1,
        )

    spikes = weekly[weekly["spike"]]
    if not spikes.empty:
        fig.add_trace(
            go.Scatter(
                x=spikes["week_start"], y=spikes["load"], mode="markers+text", name=f"> +{cfg.WEEKLY_PROGRESSION_GUIDE_PCT:.0f}% on previous week",
                marker={"symbol": "triangle-up", "size": 9, "color": cfg.LOAD_SPIKE_COLOR},
                text=[f"+{v:.0f}%" for v in spikes["wow_pct"]], textposition="top center",
                textfont={"color": T["text_secondary"], "size": 11}, cliponaxis=False,
                hovertemplate="%{x|%d %b}: +%{text} week on week<extra></extra>",
            ),
            row=1, col=1,
        )

    incomplete = weekly[weekly["incomplete"]]
    if not incomplete.empty:
        fig.add_trace(
            go.Scatter(
                x=incomplete["week_start"], y=[0] * len(incomplete), mode="markers", name="Week with sessions lacking GPS data",
                marker={"symbol": "x-thin", "size": 9, "color": T["text_muted"], "line": {"width": 2, "color": T["text_muted"]}},
                customdata=incomplete["missing_sessions"],
                hovertemplate="%{x|%d %b}: %{customdata} session(s) without GPS data — total is a lower bound<extra></extra>",
            ),
            row=1, col=1,
        )

    low, high = cfg.ACWR_SAFE_BAND
    # exclude_empty_subplots=False: the band is drawn before the ACWR traces,
    # and Plotly otherwise skips shapes on a subplot that has no traces yet.
    fig.add_hrect(y0=low, y1=high, fillcolor=cfg.ACWR_COLORS["band"], line_width=0, layer="below", row=2, col=1,
                  exclude_empty_subplots=False)
    rated = weekly.dropna(subset=["acwr"])
    if not rated.empty:
        in_band = rated["acwr"].between(low, high)
        fig.add_trace(
            go.Scatter(
                x=weekly["week_start"], y=weekly["acwr"], mode="lines", name="ACWR",
                line={"color": cfg.ACWR_COLORS["line"], "width": 2}, connectgaps=False, hoverinfo="skip", showlegend=False,
            ),
            row=2, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=rated["week_start"], y=rated["acwr"], mode="markers", name="ACWR outside 0.8–1.5",
                marker={"size": 9, "color": np.where(in_band, cfg.ACWR_COLORS["in_band"], cfg.ACWR_COLORS["out_of_band"]),
                        "line": {"color": T["surface"], "width": 2}},
                customdata=np.stack([rated["acwr_zone"], rated["chronic"]], axis=-1),
                hovertemplate=f"%{{x|%d %b}}<br>ACWR %{{y:.2f}} — %{{customdata[0]}}<br>Chronic (4-wk mean): %{{customdata[1]:,.0f}} {spec.unit}<extra></extra>",
                showlegend=False,
            ),
            row=2, col=1,
        )
    if not weekly.empty and pd.isna(weekly["acwr"].iloc[0]):
        fig.add_annotation(x=weekly["week_start"].iloc[0], y=(low + high) / 2, xref="x2", yref="y2", text="insufficient history",
                           showarrow=False, xanchor="left", font={"color": T["text_muted"], "size": 11})
    partial = weekly[weekly.get("partial", pd.Series(False, index=weekly.index))]
    for _, row in partial.iterrows():
        fig.add_annotation(x=row["week_start"], y=row["load"], xref="x", yref="y", text="partial week", showarrow=False,
                           yshift=12, font={"color": T["text_muted"], "size": 10})
    y_max = max(2.0, float(rated["acwr"].max()) + 0.2) if not rated.empty else 2.0
    fig.update_yaxes(title_text=f"{spec.label} ({spec.unit})", row=1, col=1)
    fig.update_yaxes(title_text="ACWR", range=[0, y_max], row=2, col=1)
    fig.update_xaxes(tickformat="%d %b", row=2, col=1)
    fig.update_layout(template=TEMPLATE, barmode="stack", height=height, hovermode="closest")
    return fig


# --------------------------------------------------------------------------- #
# % of match demand, microcycle profile
# --------------------------------------------------------------------------- #


def match_demand_figure(sessions: pd.DataFrame, metric: str, gref: float | None, height: int = 380) -> go.Figure:
    """Each session's ``metric`` as % of Gref, chronological, with a 100 % line.

    Dots rather than bars: a season holds 130 sessions, and bars that thin
    overlap into a wall."""
    spec = cfg.METRICS[metric]
    fig = go.Figure()
    if gref:
        for category in cfg.SESSION_CATEGORIES:
            part = sessions[(sessions["match_category"] == category) & sessions[metric].notna()]
            if part.empty:
                continue
            pct = part[metric] / gref * 100
            fig.add_trace(
                go.Scatter(
                    x=part["date"], y=pct, name=_category_label(category), mode="markers",
                    marker={"color": cfg.SESSION_COLORS[category], "size": 9, "line": {"color": T["surface"], "width": 1.5}},
                    customdata=np.stack([part["md_label"], part[metric]], axis=-1),
                    hovertemplate=f"%{{x|%d %b %Y}} · %{{customdata[0]}}<br>{spec.label}: %{{customdata[1]:,.0f}} {spec.unit}"
                                  f"<br>%{{y:.0f}}% of Gref<extra>{_category_label(category)}</extra>",
                )
            )
        fig.add_hline(y=100, line={"color": cfg.REFERENCE_LINE_COLOR, "width": 1, "dash": "dash"},
                      annotation_text="100% = Gref", annotation_position="top left",
                      annotation_font={"color": T["text_secondary"], "size": 11})
    fig.update_layout(template=TEMPLATE, height=height, yaxis={"title": f"% of Gref · {spec.label}", "ticksuffix": "%", "rangemode": "tozero"},
                      xaxis={"tickformat": "%d %b"})
    return fig


def microcycle_profile_figure(profile: pd.DataFrame, metric: str, gref: float | None, height: int = 380) -> go.Figure:
    """Mean ``metric`` per MD label (bars) with the session range (whiskers).

    ``profile`` comes from ``microcycle_profile()``.
    """
    spec = cfg.METRICS[metric]
    fig = go.Figure()
    if not profile.empty:
        is_match = profile["md_label"] == "MD"
        colors = np.where(is_match, cfg.SESSION_COLORS[cfg.OFFICIAL_MATCH], cfg.SESSION_COLORS[cfg.TRAINING])
        pct = (profile["mean"] / gref * 100).round(0) if gref else pd.Series([np.nan] * len(profile))
        fig.add_trace(
            go.Bar(
                x=profile["md_label"], y=profile["mean"], marker={"color": colors, "cornerradius": 3}, name=spec.label,
                error_y={"type": "data", "symmetric": False, "array": profile["max"] - profile["mean"],
                         "arrayminus": profile["mean"] - profile["min"], "color": T["text_muted"], "thickness": 1, "width": 4},
                text=[f"{p:.0f}%" if pd.notna(p) else "" for p in pct], textposition="inside", insidetextanchor="end",
                textfont={"color": T["text"], "size": 11},
                customdata=np.stack([profile["n"], profile["min"], profile["max"], pct], axis=-1),
                hovertemplate=f"%{{x}}<br>Mean {spec.label}: %{{y:,.0f}} {spec.unit} (%{{customdata[3]:.0f}}% of Gref)"
                              f"<br>Range %{{customdata[1]:,.0f}}–%{{customdata[2]:,.0f}} · n = %{{customdata[0]}}<extra></extra>",
                showlegend=False,
            )
        )
        if gref:
            fig.add_hline(y=gref, line={"color": cfg.REFERENCE_LINE_COLOR, "width": 1, "dash": "dash"},
                          annotation_text="Gref", annotation_position="top right",
                          annotation_font={"color": T["text_secondary"], "size": 11})
    fig.update_layout(template=TEMPLATE, height=height, yaxis={"title": f"{spec.label} ({spec.unit})"},
                      xaxis={"type": "category", "title": "Session position in the microcycle"})
    return fig


def microcycle_profile(sessions: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Mean / min / max / n of ``metric`` per MD label, regular microcycles only.

    Pre-season and extended microcycles (breaks) are left out: their MD-n
    labels count down from much further out and would blur the week's shape.
    Official matches give the MD bar; training gives every other label.
    Friendlies are excluded here and analysed on their own.
    """
    df = sessions[
        sessions["has_gps"]
        & ~sessions["microcycle_extended"]
        & (sessions["md_label"] != cfg.PRESEASON_LABEL)
        & sessions["match_category"].isin([cfg.TRAINING, cfg.OFFICIAL_MATCH])
    ]
    df = df[(df["md_label"] == "MD") == (df["match_category"] == cfg.OFFICIAL_MATCH)]
    if df.empty:
        return pd.DataFrame(columns=["md_label", "mean", "min", "max", "n"])
    grouped = df.groupby("md_label")[metric].agg(["mean", "min", "max", "count"]).rename(columns={"count": "n"}).reset_index()
    grouped = grouped[grouped["n"] > 0]
    grouped["order"] = grouped["md_label"].map(md_order)
    return grouped.sort_values("order").drop(columns="order").reset_index(drop=True)


def md_demand_table(sessions: pd.DataFrame, metrics: list[str], reference) -> pd.DataFrame:
    """Mean % of Gref per MD label (rows) and metric (columns) — Ravé's MD profile."""
    rows = []
    labels = ordered_labels(sessions["md_label"])
    for label in labels:
        part = sessions[sessions["md_label"] == label]
        row = {"MD": label, "n": int(len(part))}
        for metric in metrics:
            gref = reference.get(metric)
            row[cfg.METRICS[metric].label] = round(float(part[metric].mean() / gref * 100), 0) if gref and part[metric].notna().any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Speed / sprint
# --------------------------------------------------------------------------- #


def speed_trend_figure(sessions: pd.DataFrame, season_best: float | None, height: int = 360) -> go.Figure:
    """Max speed per session by type, with the season best as a dashed line."""
    spec = cfg.METRICS["top_speed_kmh"]
    fig = go.Figure()
    ordered = sessions.dropna(subset=["top_speed_kmh"]).sort_values("date")
    for category in cfg.SESSION_CATEGORIES:
        part = ordered[ordered["match_category"] == category]
        if part.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=part["date"], y=part["top_speed_kmh"], mode="markers", name=_category_label(category),
                marker={"color": cfg.SESSION_COLORS[category], "size": 9, "line": {"color": T["surface"], "width": 2}},
                customdata=part["md_label"],
                hovertemplate=f"%{{x|%d %b %Y}} · %{{customdata}}<br>Max speed %{{y:.1f}} km/h<extra>{_category_label(category)}</extra>",
            )
        )
    if season_best:
        fig.add_hline(y=season_best, line={"color": cfg.REFERENCE_LINE_COLOR, "width": 1, "dash": "dash"},
                      annotation_text=f"Season best {season_best:.1f} km/h", annotation_position="top left",
                      annotation_font={"color": T["text_secondary"], "size": 11})
    fig.update_layout(template=TEMPLATE, height=height, yaxis={"title": f"{spec.label} ({spec.unit})"}, xaxis={"tickformat": "%d %b"})
    return fig


def sprint_volume_figure(weekly: pd.DataFrame, height: int = 360) -> go.Figure:
    """Weekly sprint distance stacked by session type (``weekly_load`` on
    ``sprint_distance_m``); per-session bars for a whole season overlap into noise."""
    fig = go.Figure()
    hover_week = weekly["week_start"].dt.strftime("%d %b") + " – " + weekly["week_end"].dt.strftime("%d %b")
    for category in cfg.SESSION_CATEGORIES:
        column = f"load_{category}"
        if column not in weekly or weekly[column].sum() == 0:
            continue
        fig.add_trace(
            go.Bar(
                x=weekly["week_start"], y=weekly[column], name=_category_label(category),
                marker={"color": cfg.SESSION_COLORS[category], "line": {"color": T["surface"], "width": 1}},
                customdata=np.stack([hover_week, weekly["load"]], axis=-1),
                hovertemplate=f"%{{customdata[0]}}<br>{_category_label(category)}: %{{y:,.0f}} m<br>Week total: %{{customdata[1]:,.0f}} m<extra></extra>",
            )
        )
    fig.update_layout(template=TEMPLATE, height=height, barmode="stack",
                      yaxis={"title": f"Sprint distance per week (m, ≥{cfg.SPRINT_MIN_KMH} km/h)"}, xaxis={"tickformat": "%d %b"})
    return fig


# --------------------------------------------------------------------------- #
# Practice matches
# --------------------------------------------------------------------------- #


def friendly_vs_official_figure(sessions: pd.DataFrame, metrics: list[str], reference, height: int = 360) -> go.Figure:
    """Every friendly and every official match as % of Gref, one column per metric.

    Shows whether friendlies reproduce official-match demand — the question
    that decides whether a friendly can stand in for a match in the week.
    """
    fig = go.Figure()
    for category, offset in ((cfg.OFFICIAL_MATCH, -0.16), (cfg.PRACTICE_MATCH, 0.16)):
        part = sessions[(sessions["match_category"] == category) & sessions["has_gps"]]
        xs, ys, tips = [], [], []
        for i, metric in enumerate(metrics):
            gref = reference.get(metric)
            if not gref:
                continue
            values = part[metric] / gref * 100
            jitter = np.linspace(-0.06, 0.06, len(values)) if len(values) > 1 else [0]
            xs += list(i + offset + np.array(jitter))
            ys += list(values)
            tips += [f"{d:%d %b %Y} · {cfg.METRICS[metric].label}: {v:.0f}% of Gref · {m:.0f} min"
                     for d, v, m in zip(part["date"], values, part["minutes_played"].fillna(0))]
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys, mode="markers", name=_category_label(category),
                    marker={"color": cfg.SESSION_COLORS[category], "size": 8, "opacity": 0.85,
                            "line": {"color": T["surface"], "width": 1}},
                    text=tips, hovertemplate="%{text}<extra></extra>",
                )
            )
    fig.add_hline(y=100, line={"color": cfg.REFERENCE_LINE_COLOR, "width": 1, "dash": "dash"})
    fig.update_layout(
        template=TEMPLATE, height=height, yaxis={"title": "% of Gref", "ticksuffix": "%"},
        xaxis={"tickvals": list(range(len(metrics))), "ticktext": [cfg.METRICS[m].short for m in metrics], "range": [-0.5, len(metrics) - 0.5]},
    )
    return fig


# --------------------------------------------------------------------------- #
# Session detail table styling
# --------------------------------------------------------------------------- #


def number_format(decimals: int):
    return lambda v: "—" if v is None or pd.isna(v) else f"{v:,.{decimals}f}".replace(",", " ")


def style_vs_gref(table: pd.DataFrame, value_to_metric: dict[str, str], reference, extra_formats: dict | None = None):
    """Pandas Styler: each metric cell shaded by its % of Gref (sequential blue).

    All formats go in one ``.format`` call — a second call resets the first."""
    def shade(column: pd.Series):
        metric = value_to_metric.get(column.name)
        gref = reference.get(metric) if metric else None
        if not gref:
            return [""] * len(column)
        styles = []
        for value in column:
            if pd.isna(value):
                styles.append("")
                continue
            bg = demand_color(value / gref * 100)
            styles.append(f"background-color: {bg}; color: {readable_text(bg)}")
        return styles

    formats = {col: number_format(cfg.METRICS[m].decimals) for col, m in value_to_metric.items()}
    formats.update(extra_formats or {})
    numeric = table.copy()
    for col in value_to_metric:
        numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    return numeric.style.apply(shade, axis=0).format(formats, na_rep="—")


def style_md_table(table: pd.DataFrame, metric_columns: list[str]):
    def shade(column: pd.Series):
        if column.name not in metric_columns:
            return [""] * len(column)
        return [
            "" if pd.isna(v) else f"background-color: {demand_color(v)}; color: {readable_text(demand_color(v))}"
            for v in column
        ]
    return table.style.apply(shade, axis=0).format({c: "{:.0f}%" for c in metric_columns}, na_rep="—")


# --------------------------------------------------------------------------- #
# Page CSS (generated from THEME so no colour is hardcoded in the layout)
# --------------------------------------------------------------------------- #


def page_css() -> str:
    """Global CSS for the report: black page, accent-bordered cards, the heat table."""
    a, bg, s, s2 = T["accent"], T["background"], T["surface"], T["surface_raised"]
    return f"""
<style>
:root {{ --gps-accent: {a}; }}
html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{ background: {bg}; }}
[data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]) {{ font-family: {cfg.FONT_FAMILY}; }}
[data-testid="stSidebar"] {{ background: {s}; border-right: 1px solid {T['grid']}; }}
.block-container {{ padding-top: 3.2rem; max-width: 1500px; }}
.gps-title {{ font-family: {cfg.TITLE_FONT_FAMILY} !important; text-align: center; color: {T['text']};
  font-size: clamp(1.9rem, 3.4vw, 3.1rem); letter-spacing: .06em; text-transform: uppercase; margin: .2rem 0 .1rem; line-height: 1.05; }}
.gps-subtitle {{ text-align: center; color: {T['text_secondary']}; font-size: .95rem; margin-bottom: 1.2rem; }}
.gps-subtitle b {{ color: {T['text']}; font-weight: 600; }}
.gps-player {{ border: 1px solid {a}; border-radius: 10px; padding: .8rem .9rem; margin-bottom: .6rem; }}
.gps-player .name {{ font-family: {cfg.TITLE_FONT_FAMILY} !important; font-size: 1.6rem; color: {T['text']}; text-transform: uppercase; letter-spacing: .04em; line-height: 1; }}
.gps-player .meta {{ color: {T['text_secondary']}; font-size: .85rem; margin-top: .35rem; }}
.gps-sidebar-label {{ color: {T['text']}; font-weight: 700; font-size: .95rem; margin: .4rem 0 -.2rem; }}
.gps-section {{ display: flex; align-items: baseline; gap: .8rem; margin: 2.2rem 0 .6rem; padding-bottom: .35rem; border-bottom: 1px solid {T['grid']}; }}
.gps-section h3 {{ margin: 0; padding: 0; color: {T['text']}; font-family: {cfg.TITLE_FONT_FAMILY} !important; text-transform: uppercase; letter-spacing: .05em; font-size: 1.35rem; }}
.gps-section .num {{ color: {bg}; background: {a}; border-radius: 4px; padding: 0 .45rem; font-weight: 700; font-size: .9rem; }}
.gps-section span.sub {{ color: {T['text_muted']}; font-size: .88rem; }}
.gps-card {{ border: 1.5px solid {a}; border-radius: 10px; overflow: hidden; background: {bg}; }}
.gps-card-header {{ background: {a}; color: {T['accent_text']}; font-weight: 700; text-align: center; padding: .45rem .6rem; font-size: 1.05rem; letter-spacing: .01em; }}
.gps-table-wrap {{ overflow: auto; padding: 0 .6rem .6rem; }}
.gps-table {{ width: 100%; border-collapse: separate; border-spacing: 0 2px; font-variant-numeric: tabular-nums; }}
.gps-table thead th {{ position: sticky; top: 0; background: {bg}; color: {T['text']}; font-weight: 400; font-size: 1rem;
  text-align: center; padding: .7rem .4rem .5rem; border-bottom: 1px solid {T['axis']}; z-index: 1; white-space: nowrap; }}
.gps-table td {{ text-align: center; padding: .32rem .4rem; font-size: .95rem; color: {T['text']}; white-space: nowrap; }}
.gps-table td.gps-date {{ text-align: right; color: {T['text']}; padding-right: .8rem; }}
.gps-table td.gps-md {{ color: {T['text_secondary']}; font-size: .85rem; }}
.gps-table td.gps-empty {{ color: {T['text_muted']}; padding: 1.2rem; }}
.gps-chip {{ display: inline-flex; align-items: center; gap: .35rem; color: {T['text_secondary']}; font-size: .85rem; }}
.gps-chip i {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; }}
.gps-note {{ margin-left: .4rem; font-size: .75rem; color: {T['text_muted']}; border: 1px solid {T['axis']}; border-radius: 4px; padding: 0 .3rem; }}
.gps-fallback {{ font-size: .55em; margin-left: .2rem; opacity: .85; }}
.gps-legend {{ display: flex; flex-wrap: wrap; gap: .9rem; align-items: center; color: {T['text_muted']}; font-size: .82rem; margin: .5rem .2rem 0; }}
.gps-swatch {{ display: inline-flex; gap: .3rem; align-items: center; }}
.gps-swatch i {{ width: 14px; height: 10px; border-radius: 2px; display: inline-block; }}
.gps-kpi-head {{ background: {a}; color: {T['accent_text']}; font-weight: 700; text-align: center; padding: .4rem .5rem; font-size: 1rem; border-radius: 8px 8px 0 0; }}
.gps-kpi-foot {{ display: flex; justify-content: space-between; gap: .4rem; flex-wrap: wrap; color: {T['text_muted']}; font-size: .78rem; padding: 0 .7rem .6rem; }}
.gps-marker {{ display: inline-block; width: 3px; height: 10px; background: {cfg.GAUGE['marker']}; margin-right: .3rem; vertical-align: -1px; }}
.gps-bignum {{ text-align: center; font-size: 3.6rem; font-weight: 700; color: {T['text']}; line-height: 1; padding: 2.6rem 0 2.1rem; font-variant-numeric: tabular-nums; }}
.gps-bignum small {{ font-size: 1rem; font-weight: 400; color: {T['text_secondary']}; margin-left: .3rem; }}
.gps-stat {{ border: 1px solid {T['grid']}; border-radius: 8px; padding: .6rem .8rem; background: {s}; }}
.gps-stat .label {{ color: {T['text_muted']}; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }}
.gps-stat .value {{ color: {T['text']}; font-size: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums; }}
.gps-stat .hint {{ color: {T['text_secondary']}; font-size: .8rem; }}
.gps-caption {{ color: {T['text_muted']}; font-size: .85rem; margin-top: .3rem; }}
.gps-warning {{ border-left: 3px solid {cfg.STATUS_COLORS['warning']}; background: {s2}; color: {T['text_secondary']}; padding: .5rem .8rem; border-radius: 4px; font-size: .88rem; margin: .4rem 0; }}
div[class*="st-key-kpi_"] {{ border: 1.5px solid {a}; border-radius: 10px; background: {bg}; gap: 0 !important; padding: 0 !important; overflow: hidden; }}
div[class*="st-key-panel_"] {{ border: 1px solid {T['grid']}; border-radius: 10px; background: {s}; padding: .8rem .9rem .4rem; }}
div[class*="st-key-panel_"] h4 {{ margin: 0 0 .1rem; color: {T['text']}; font-size: 1.02rem; font-weight: 600; }}
[data-testid="stExpander"] details {{ border-color: {T['grid']}; background: {s}; }}
</style>
"""
