"""The GPS Report page — layout only.

Sections (in order): title, Weekly Change % table + KPI cards, weekly load +
ACWR, % of match demand + microcycle profile, speed / sprint, practice matches,
session detail, definitions. Every section reads the same ``ReportScope`` built
from the sidebar filters; every number comes from ``football_stats.gps``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from football_stats.gps import charts
from football_stats.gps import config as cfg
from football_stats.gps.load_monitoring import weekly_acwr, weekly_load
from football_stats.gps.match_label import add_match_label_columns
from football_stats.gps.reference import MatchReference, match_reference
from football_stats.gps.weekly_change import weekly_change


@dataclass
class ReportScope:
    sessions: pd.DataFrame
    """Every prepared, MD-labelled session (all seasons, unfiltered)."""
    season: str
    start: pd.Timestamp
    end: pd.Timestamp
    categories: list[str]
    type_label: str
    focus_metric: str
    change_mode: str
    acwr_method: str

    @property
    def season_sessions(self) -> pd.DataFrame:
        return self.sessions[self.sessions["season"] == self.season]

    @property
    def in_range(self) -> pd.DataFrame:
        """Season + date range, every session type (for whole-load views)."""
        s = self.season_sessions
        return s[(s["date"] >= self.start) & (s["date"] <= self.end)]

    @property
    def filtered(self) -> pd.DataFrame:
        """All three global filters applied."""
        s = self.in_range
        return s[s["match_category"].isin(self.categories)]


def chart(fig, key: str | None = None) -> None:
    st.plotly_chart(fig, theme=None, config=charts.PLOTLY_CONFIG, key=key)


def section(number: int, title: str, subtitle: str = "") -> None:
    st.html(
        f'<div class="gps-section"><span class="num">{number}</span><h3>{title}</h3>'
        + (f'<span class="sub">{subtitle}</span>' if subtitle else "")
        + "</div>"
    )


def caption(text: str) -> None:
    st.html(f'<div class="gps-caption">{text}</div>')


def stat(label: str, value: str, hint: str = "") -> None:
    st.html(f'<div class="gps-stat"><div class="label">{label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>')


def _fmt(value, metric: str, unit: bool = True) -> str:
    spec = cfg.METRICS[metric]
    if value is None or pd.isna(value):
        return "—"
    text = f"{value:,.{spec.decimals}f}".replace(",", " ")
    return f"{text} {spec.unit}" if unit else text


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


def _header(scope: ReportScope) -> None:
    measured = scope.filtered[scope.filtered["has_gps"]]
    st.html(
        '<div class="gps-title">Weekly Change % GPS Report</div>'
        f'<div class="gps-subtitle"><b>{scope.season}</b> · {scope.start:%d %b %Y} – {scope.end:%d %b %Y} · '
        f"<b>{scope.type_label}</b> · {len(scope.filtered)} sessions ({len(measured)} with GPS data)</div>"
    )


def _weekly_change_section(scope: ReportScope, reference: MatchReference) -> None:
    section(1, "Weekly change %", cfg.CHANGE_MODES[scope.change_mode])
    changes = weekly_change(scope.season_sessions, cfg.REPORT_METRICS, mode=scope.change_mode, reference=reference)
    rows = changes.loc[changes.index.intersection(scope.filtered.index)] if not changes.empty else changes
    st.html(charts.weekly_change_table_html(rows, cfg.REPORT_METRICS, scope.change_mode))
    st.html(charts.heat_legend_html())
    if scope.change_mode == "previous_microcycle":
        caption(
            "Each session against the session with the <b>same MD label in the previous microcycle</b> "
            "(a match against the previous match). When that doesn't exist, against the <b>previous session "
            "of the same type</b>, marked ●. Never across types. Colour is the size of the change, either "
            f"direction; about {cfg.WEEKLY_PROGRESSION_GUIDE_PCT:.0f}% a week is the progression guideline "
            "(Ravé et al. 2020). Hover a cell for both values."
        )
    else:
        caption("Each session against the match reference Gref: −40% means 40% under one match's demand.")

    _kpi_cards(scope, reference)


def _kpi_cards(scope: ReportScope, reference: MatchReference) -> None:
    measured = scope.filtered[scope.filtered["has_gps"]]
    n = len(measured)
    columns = st.columns(len(cfg.REPORT_METRICS), gap="small")
    for column, metric in zip(columns, cfg.REPORT_METRICS):
        spec = cfg.METRICS[metric]
        gref = reference.get(metric)
        with column, st.container(key=f"kpi_{metric}"):
            st.html(f'<div class="gps-kpi-head">{spec.label}</div>')
            if metric in cfg.BIG_NUMBER_METRICS:
                value = measured[metric].max() if n else None
                st.html(charts.big_number_html(value, spec, gref))
            else:
                value = measured[metric].mean() if n else None
                chart(charts.gauge_figure(value, gref, spec), key=f"gauge_{metric}")
                st.html(charts.kpi_caption_html(value, gref, spec, f"avg / session · n={n}"))
    caption(
        "Cards summarise the selected range: the <b>average session</b> for each metric (the peak for Max Speed), "
        f"against the match reference <b>Gref</b> (orange marker; gauge runs to {cfg.GAUGE_MAX_MULTIPLIER:.0f}×Gref). "
        "Averages rather than totals so a range of any length reads on the same scale as one match."
    )


def _load_section(scope: ReportScope) -> pd.DataFrame:
    spec = cfg.METRICS[scope.focus_metric]
    section(2, "Weekly load & ACWR", f"{spec.label} · Sunday–Saturday weeks · all session types")
    weekly = weekly_acwr(scope.season_sessions, scope.focus_metric, method=scope.acwr_method)
    shown = weekly[(weekly["week_end"] >= scope.start) & (weekly["week_start"] <= scope.end)] if not weekly.empty else weekly
    if shown.empty:
        st.info("No weeks in the selected range.")
        return weekly

    rated = shown.dropna(subset=["acwr"])
    complete = shown[~shown["partial"]]
    last = complete.iloc[-1] if not complete.empty else shown.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        stat("Latest complete week", _fmt(last["load"], scope.focus_metric), f"week of {last['week_start']:%d %b}")
    with c2:
        wow = last["wow_pct"]
        stat("Change on previous week", "—" if pd.isna(wow) else f"{wow:+.0f}%",
             f"guideline ≈ +{cfg.WEEKLY_PROGRESSION_GUIDE_PCT:.0f}% / week")
    with c3:
        if rated.empty:
            stat("ACWR", "—", "insufficient history")
        else:
            latest = rated.iloc[-1]
            stat("ACWR (latest rated week)", f"{latest['acwr']:.2f}", f"{latest['acwr_zone']} · safe {cfg.ACWR_SAFE_BAND[0]}–{cfg.ACWR_SAFE_BAND[1]}")
    with c4:
        outside = (~rated["acwr"].between(*cfg.ACWR_SAFE_BAND)).sum() if not rated.empty else 0
        stat("Weeks outside the band", f"{outside} / {len(rated)}", f"{(shown['spike']).sum()} week(s) up > {cfg.WEEKLY_PROGRESSION_GUIDE_PCT:.0f}%")

    with st.container(key="panel_load"):
        chart(charts.load_acwr_figure(shown, spec, scope.categories), key="load_acwr")
    method = (
        f"acute = this week, chronic = mean of the previous {cfg.ACWR_CHRONIC_WEEKS} weeks"
        if scope.acwr_method == "rolling"
        else f"EWMA, acute span {cfg.ACWR_EWMA_ACUTE_DAYS} d, chronic span {cfg.ACWR_EWMA_CHRONIC_DAYS} d"
    )
    caption(
        f"<b>{cfg.ACWR_CAPTION}</b> Ratio = {method}; no ratio for the first {cfg.ACWR_MIN_HISTORY_WEEKS} weeks of the season. "
        "Shaded band = 0.8–1.5; red points sit outside it. Load always includes every session type, so session "
        "types hidden by the filter are drawn faded rather than removed. ✕ marks a week containing sessions without "
        "GPS data — its total is a lower bound. A final week the data doesn't fully cover is marked "
        "partial and left unrated."
    )
    return weekly


def _demand_section(scope: ReportScope, reference: MatchReference) -> None:
    spec = cfg.METRICS[scope.focus_metric]
    gref = reference.get(scope.focus_metric)
    section(3, "Match demand & microcycle", f"{spec.label} · Gref = mean of best {cfg.GREF_TOP_N} official matches")
    left, right = st.columns(2, gap="medium")
    measured = scope.filtered[scope.filtered["has_gps"]]
    with left, st.container(key="panel_demand"):
        st.markdown("#### % of match demand, per session")
        chart(charts.match_demand_figure(measured, scope.focus_metric, gref), key="demand")
    with right, st.container(key="panel_profile"):
        st.markdown("#### Microcycle profile")
        profile = charts.microcycle_profile(scope.in_range[scope.in_range["match_category"].isin(scope.categories + [cfg.OFFICIAL_MATCH])], scope.focus_metric)
        chart(charts.microcycle_profile_figure(profile, scope.focus_metric, gref), key="profile")
    caption(
        "Left: each session as a share of Gref (100% = one match at your best). Right: the shape of a regular "
        "week — mean per MD label with the range as whiskers; pre-season and extended microcycles (breaks longer than "
        f"{cfg.EXTENDED_MICROCYCLE_DAYS} days) are left out because their MD-n labels count down from much further away. "
        "The MD bar is always shown for reference."
    )

    table = charts.md_demand_table(measured[measured["md_label"] != cfg.PRESEASON_LABEL], cfg.REPORT_METRICS, reference)
    if not table.empty:
        with st.expander("% of match demand by MD day, every report metric", expanded=False):
            metric_columns = [cfg.METRICS[m].label for m in cfg.REPORT_METRICS]
            st.dataframe(charts.style_md_table(table, metric_columns), hide_index=True)


def _speed_section(scope: ReportScope) -> None:
    section(4, "Speed & sprint", f"sprint ≥ {cfg.SPRINT_MIN_KMH} km/h · STATSports bands")
    season_measured = scope.season_sessions[scope.season_sessions["has_gps"]]
    measured = scope.filtered[scope.filtered["has_gps"]]
    season_best = season_measured["top_speed_kmh"].max() if not season_measured.empty else None

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        best_row = season_measured.loc[season_measured["top_speed_kmh"].idxmax()] if season_measured["top_speed_kmh"].notna().any() else None
        stat("Season top speed", _fmt(season_best, "top_speed_kmh"), f"{best_row['date']:%d %b %Y}" if best_row is not None else "")
    with c2:
        stat("Top speed in range", _fmt(measured["top_speed_kmh"].max() if not measured.empty else None, "top_speed_kmh"),
             f"{measured['top_speed_kmh'].max() / season_best * 100:.0f}% of season best" if season_best and measured["top_speed_kmh"].notna().any() else "")
    with c3:
        near = (measured["top_speed_kmh"] >= cfg.NEAR_MAX_SPEED_PCT * season_best).sum() if season_best else 0
        stat(f"Sessions ≥ {cfg.NEAR_MAX_SPEED_PCT:.0%} of best", f"{near} / {measured['top_speed_kmh'].notna().sum()}", "near-max exposure")
    with c4:
        stat("Sprints in range", f"{measured['sprints_total'].sum():.0f}", f"{measured['sprint_distance_m'].sum():,.0f} m sprinting".replace(",", " "))

    left, right = st.columns(2, gap="medium")
    with left, st.container(key="panel_speed"):
        st.markdown("#### Max speed per session")
        chart(charts.speed_trend_figure(measured, season_best), key="speed")
    with right, st.container(key="panel_sprint"):
        st.markdown("#### Sprint distance per week")
        chart(charts.sprint_volume_figure(weekly_load(scope.filtered, "sprint_distance_m")), key="sprint")
    caption(
        "Per-second velocity isn't in the export, so time-to-speed and acceleration by speed band "
        "(Reinhardt et al. 2019) can't be computed — only the session peaks and totals the device reports."
    )


def _practice_section(scope: ReportScope, reference: MatchReference) -> None:
    section(5, "Practice matches", "friendlies — practice with a scoreline")
    if cfg.PRACTICE_MATCH not in scope.categories:
        st.info("Practice matches are hidden by the session-type filter.")
        return
    friendlies = add_match_label_columns(scope.in_range[(scope.in_range["match_category"] == cfg.PRACTICE_MATCH)])
    if friendlies.empty:
        st.info("No practice matches in the selected range.")
        return

    comparison = scope.in_range[scope.in_range["match_category"].isin([cfg.OFFICIAL_MATCH, cfg.PRACTICE_MATCH])]
    metrics = ["total_distance_m", "hsr_sprint_m", "sprint_distance_m", "hia", "top_speed_kmh", "m_per_min"]
    with st.container(key="panel_friendly"):
        st.markdown("#### Friendlies vs official matches, % of Gref")
        chart(charts.friendly_vs_official_figure(comparison, metrics, reference), key="friendly")
    table = friendlies[["date", "opponent", "md_label", "minutes_played", *metrics]].copy()
    table = table.rename(columns={"date": "Date", "opponent": "Opponent", "md_label": "MD", "minutes_played": "Min"})
    value_map = {}
    for metric in metrics:
        label = cfg.METRICS[metric].short
        table = table.rename(columns={metric: label})
        value_map[label] = metric
    table["Date"] = table["Date"].dt.date
    styled = charts.style_vs_gref(table.sort_values("Date", ascending=False), value_map, reference,
                                  extra_formats={"Min": charts.number_format(0)})
    st.dataframe(styled, hide_index=True)
    caption(
        "Friendlies are analysed as <b>practice</b>: they sit inside the microcycle with an MD label like any session and "
        "never anchor one. The question here is whether a friendly reproduces official-match demand — dots near 100% "
        "mean it can stand in for a match's load; well below means it is a lighter training stimulus. Table cells are "
        "shaded by % of Gref."
    )


def _session_table(scope: ReportScope, reference: MatchReference) -> None:
    section(6, "Session detail", "sortable · cells shaded by % of Gref")
    df = add_match_label_columns(scope.filtered).sort_values("date", ascending=False)
    if df.empty:
        st.info("No sessions in the selected range.")
        return
    metrics = ["total_distance_m", "hsr_sprint_m", "hsr_m", "sprint_distance_m", "top_speed_kmh", "accelerations",
               "decelerations", "sprints_total", "hia", "m_per_min"]
    status = pd.Series("", index=df.index)
    status[df["short_appearance"]] = "short appearance"
    status[~df["has_gps"]] = "no GPS data"
    status[df["unused_sub"]] = "unused sub"
    table = pd.DataFrame({
        "Date": df["date"].dt.date,
        "Type": df["match_category"].map(cfg.SESSION_CATEGORY_LABELS),
        "MD": df["md_label"],
        "Session": df["session_type"],
        "Min": df["minutes_played"],
    })
    value_map = {}
    for metric in metrics:
        label = f"{cfg.METRICS[metric].short} ({cfg.METRICS[metric].unit})"
        table[label] = df[metric]
        value_map[label] = metric
    table["Flag"] = status
    table["Notes"] = df["notes"]
    styled = charts.style_vs_gref(table, value_map, reference, extra_formats={"Min": charts.number_format(0)})
    st.dataframe(styled, hide_index=True, height=440)


def _definitions(reference: MatchReference) -> None:
    with st.expander("Definitions, thresholds and data notes"):
        gref_rows = "\n".join(
            f"| {cfg.METRICS[m].label} | {_fmt(reference.get(m), m)} | {reference.matches_used.get(m, 0)} of {reference.eligible.get(m, 0)} |"
            for m in cfg.REPORT_METRICS + ["sprint_distance_m", "accelerations", "decelerations"]
        )
        st.markdown(
            f"""
**Device bands (STATSports).** HSR & Sprint = distance above {cfg.HSR_MIN_KMH} km/h, sprinting included; HSR alone =
{cfg.HSR_MIN_KMH}–{cfg.SPRINT_MIN_KMH} km/h (HSR & Sprint − Sprint); Sprint = above {cfg.SPRINT_MIN_KMH} km/h.
Accelerations / decelerations = efforts beyond ±{cfg.ACC_THRESHOLD_MS2:g} m/s². High-Intensity Actions = accelerations +
decelerations + sprints. Distance per minute = total distance ÷ GPS duration (recomputed; the export's own column
disagrees on a few rows). No training-load metric exists in the export, so none is shown.

**Match reference (Gref).** Mean of the best {cfg.GREF_TOP_N} official-match values per metric, this season
({reference.season or '—'}). Unused-substitute matches are excluded; for Distance per Minute, appearances under
{cfg.SHORT_APPEARANCE_MIN:.0f} minutes are excluded too.

| Metric | Gref | matches used / eligible |
|---|---|---|
{gref_rows}

**MD labels.** Official match = MD. Up to {cfg.MD_PLUS_MAX_DAYS} days after it = MD+1/MD+2; every other session = MD−n,
n = days to the next official match. Friendlies never anchor. Before the season's first match: MD−n within
{cfg.PRESEASON_LEAD_DAYS} days, otherwise PRE. A microcycle runs from MD to the day before the next MD; longer than
{cfg.EXTENDED_MICROCYCLE_DAYS} days = extended.

**Weekly change.** Default basis: same MD label in the previous microcycle, falling back to the previous session of
the same type (●). Heat colours on |change|: ≤10% green, 10–20% amber, 20–30% orange, >30% red, interpolated.

**ACWR.** Weekly ({cfg.WEEK_FREQ.replace('W-SAT', 'Sunday–Saturday')}) load of the focus metric across all session
types; {cfg.ACWR_METHOD} method by default, EWMA selectable. Safe band {cfg.ACWR_SAFE_BAND[0]}–{cfg.ACWR_SAFE_BAND[1]}.
*{cfg.ACWR_CAPTION}*

**Data hygiene.** Rows without GPS data stay in the log but carry no values; unused-substitute matches (all zeros in the
export) are treated as "did not play", not as zero output. Thresholds and colours live in
`src/football_stats/gps/config.py`. Sources: Ravé et al. (2020) *Front. Physiol.* 11:944; Reinhardt et al. (2019)
*PLoS ONE*; Gabbett (2016) *BJSM* 50(5); Williams et al. (2017) *BJSM* 51(3).
"""
        )


def render(scope: ReportScope) -> None:
    _header(scope)
    reference = match_reference(scope.sessions, scope.season)
    if reference.season is None:
        st.markdown(f'<div class="gps-warning">{reference.describe()}</div>', unsafe_allow_html=True)
    elif reference.warning:
        st.markdown(f'<div class="gps-warning">Gref: {reference.describe()}</div>', unsafe_allow_html=True)

    if scope.season_sessions.empty:
        st.info(f"No GPS sessions in {scope.season} — the body-composition analyses on the **More analysis** page still apply.")
        return

    _weekly_change_section(scope, reference)
    _load_section(scope)
    _demand_section(scope, reference)
    _speed_section(scope)
    _practice_section(scope, reference)
    _session_table(scope, reference)
    _definitions(reference)
