"""Streamlit dashboard: GPS training/match performance analysis.

Run with:
    streamlit run dashboards/gps_dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_stats.body import data_store as body_store  # noqa: E402
from football_stats.body import gps_link as body_gps  # noqa: E402
from football_stats.body import performance_link  # noqa: E402
from football_stats.body import summary as body_summary  # noqa: E402
from football_stats.gps.analyzer import MATCH_CATEGORIES, PerformanceAnalyzer, add_match_category_column  # noqa: E402
from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, append_session, load_sessions  # noqa: E402
from football_stats.gps.formatting import DISPLAY_LABELS, MATCH_CATEGORY_LABELS, humanize_columns, numeric_column_config  # noqa: E402
from football_stats.gps.gauges import (  # noqa: E402
    acwr_gauge,
    intensity_gauge,
    monotony_gauge,
    percentile_gauge,
    quality_gauge,
    strain_gauge,
    top_speed_gauge,
)
from football_stats.gps.load_monitoring import classify_acwr, classify_monotony, compute_acwr, weekly_monotony_and_strain  # noqa: E402
from football_stats.gps.match_link import (  # noqa: E402
    MINUTES_FLOOR,
    flag_short_appearances,
    minutes_overhang,
    official_minutes,
)
from football_stats.gps.match_label import (  # noqa: E402
    add_match_label_columns,
    build_match_label,
    output_by,
)
from football_stats.gps.fatigue import (  # noqa: E402
    BALANCED_ACCEL_DECEL,
    NEAR_MAX_SPEED_PCT,
    add_mechanical_load,
    classify_accel_decel_ratio,
    high_speed_exposure,
    retention_summary,
    second_half_retention,
    training_match_intensity_gap,
)
from football_stats.gps.position_baselines import POSITION_LABELS, POSITIONS  # noqa: E402
from football_stats.gps.seasons import add_season_column  # noqa: E402
from football_stats.gps.skillcorner_metrics import (  # noqa: E402
    PER90_METRICS,
    add_intensity_ratios,
    add_per90_columns,
    percentile_rank,
    robust_top_speed,
)

st.set_page_config(page_title="GPS Performance", page_icon="🏃", layout="wide")

ALL_SEASONS = "All seasons"
WEEKLY_METRICS = ["duration_min", "total_distance_m", "sprint_distance_m", "high_speed_distance_m", "calories"]
WEEKLY_GROUPS = [
    ("training", "Training"),
    ("official_match", "Official Matches"),
    ("practice_match", "Practice Matches"),
    ("total", "Overall (All Categories)"),
]


@st.cache_data
def _load() -> pd.DataFrame:
    sessions = load_sessions(DEFAULT_SESSIONS_PATH)
    if sessions.empty:
        return sessions
    sessions = add_match_category_column(sessions)
    sessions = add_season_column(sessions)
    return sessions


@st.cache_data
def _load_body() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Body-composition assessments (wide, derived, raw measurements, changes)."""
    return (
        body_store.load_wide(),
        body_store.load_derived(),
        body_store.load_measurements(),
        body_store.load_changes(),
    )


def _show_table(df: pd.DataFrame) -> None:
    display = humanize_columns(df)
    st.dataframe(display, width="stretch", hide_index=True, column_config=numeric_column_config(display))


def _metric_label(metric: str) -> str:
    return DISPLAY_LABELS.get(metric, metric)


def _add_session_form() -> None:
    st.subheader("Add a new session")
    with st.form("add_session", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            date = st.date_input("Date")
            session_kind = st.selectbox("Session kind", ["training", "game"])
            session_type = st.text_input(
                "Session type / label", placeholder="e.g. Treino Terça-Feira",
                help="Used as-is for training. For a game, the match fields below compose the label instead.",
            )
        with col2:
            duration_min = st.number_input("Duration (min)", min_value=0.0, step=1.0)
            total_distance_m = st.number_input("Total distance (m)", min_value=0.0, step=10.0)
            sprint_distance_m = st.number_input("Sprint distance (m)", min_value=0.0, step=10.0)
            high_speed_distance_m = st.number_input("High-speed distance (m)", min_value=0.0, step=10.0)
        with col3:
            top_speed_kmh = st.number_input("Top speed (km/h)", min_value=0.0, step=0.1)
            sprints_total = st.number_input("Sprints (#)", min_value=0.0, step=1.0)
            accelerations = st.number_input("Accelerations (#)", min_value=0.0, step=1.0)
            decelerations = st.number_input("Decelerations (#)", min_value=0.0, step=1.0)

        calories = st.number_input("Calories", min_value=0.0, step=10.0)

        competition_type, was_starter = None, None
        opponent, venue, matchweek = "", "home", ""
        goals_home = goals_away = None
        if session_kind == "game":
            st.caption("Competition type decides whether this counts as an official match or a practice match in the analysis.")
            gcol1, gcol2 = st.columns(2)
            with gcol1:
                competition_type = st.selectbox("Competition type", ["Campeonato", "Taça", "Treino"])
            with gcol2:
                was_starter = st.checkbox("Started the match", value=True)

            # Captured as fields and composed into `session_type`, rather than left
            # to be typed freehand. Opponent, venue and result are read back out of
            # that label everywhere in this dashboard, so a label that doesn't match
            # the format is a row that silently loses its match context.
            st.caption(
                "These compose the **session label**, which is where the rest of the dashboard "
                "reads opponent, venue and result from. Leave the score blank if it isn't known "
                "yet — the label records `?-?` and the row keeps its opponent and venue."
            )
            mcol1, mcol2, mcol3, mcol4 = st.columns([3, 2, 2, 2])
            with mcol1:
                opponent = st.text_input("Opponent", placeholder="e.g. Vila Viçosa")
            with mcol2:
                venue = st.radio("Venue", ["home", "away"], horizontal=True,
                                 format_func=lambda v: "Home (CASA)" if v == "home" else "Away (FORA)")
            with mcol3:
                goals_home = st.number_input("Goals — home", min_value=0, step=1, value=None, placeholder="?")
            with mcol4:
                goals_away = st.number_input("Goals — away", min_value=0, step=1, value=None, placeholder="?")
            if competition_type == "Campeonato":
                matchweek = st.text_input(
                    "Matchweek", placeholder="e.g. 11, or 1 Ap.Campeão",
                    help="The round number as the label writes it. Playoff rounds carry the Ap.Campeão suffix.",
                )
            st.caption(
                "The score is entered **home-first** — the same way every existing label writes "
                "it — and your team's result is derived from it and the venue, not typed in."
            )

        notes = st.text_area("Notes", placeholder="Optional")
        submitted = st.form_submit_button("Add session")

        if submitted:
            label = session_type or None
            if session_kind == "game" and opponent.strip():
                label = build_match_label(
                    competition_type, opponent, venue, goals_home, goals_away, matchweek
                )
            append_session(
                {
                    "date": str(date),
                    "session_kind": session_kind,
                    "session_type": label,
                    "duration_min": duration_min or None,
                    "total_distance_m": total_distance_m or None,
                    "sprint_distance_m": sprint_distance_m or None,
                    "high_speed_distance_m": high_speed_distance_m or None,
                    "top_speed_kmh": top_speed_kmh or None,
                    "sprints_total": sprints_total or None,
                    "accelerations": accelerations or None,
                    "decelerations": decelerations or None,
                    "calories": calories or None,
                    "competition_type": competition_type,
                    "was_starter": was_starter,
                    "notes": notes or None,
                },
                path=DEFAULT_SESSIONS_PATH,
            )
            st.cache_data.clear()
            st.success(f"Session added — label: `{label}`" if label else "Session added.")
            st.rerun()

VERDICT_COLOURS = {
    "better": "rgba(33, 150, 83, 0.18)",
    "worse": "rgba(214, 69, 69, 0.18)",
    "noise": "rgba(130, 130, 130, 0.12)",
    "neutral": "",
}
VERDICT_LABELS = {
    "better": "✅ improved",
    "worse": "🔻 regressed",
    "noise": "· within noise",
    "neutral": "— no direction",
}


def _style_by_verdict(df: pd.DataFrame, verdict_column: str = "verdict"):
    """Tint each row by its verdict so evolution and regression read at a glance."""
    if df.empty or verdict_column not in df.columns:
        return df

    def _row(row):
        colour = VERDICT_COLOURS.get(row[verdict_column], "")
        return [f"background-color: {colour}" if colour else "" for _ in row]

    return df.style.apply(_row, axis=1).format(precision=2)


def _delta_colour(direction: str) -> str:
    """Map a metric's direction onto Streamlit's delta colouring.

    ``"off"`` for directionless metrics is the important case: body mass has no
    good direction for a footballer, and coloring a 1.7 kg gain green would
    assert a goal this data does not contain.
    """
    return {"up": "normal", "down": "inverse"}.get(direction, "off")


def _physical_profile_tab(filtered: pd.DataFrame) -> None:
    st.subheader("Physical profile — fatigue, mechanical load and speed exposure")
    st.caption(
        "Everything on the other tabs is built on `total_distance_m`, which measures only one kind "
        "of cost: how much running was done. This tab covers the three things distance cannot see — "
        "whether output **held up** across a match, the **mechanical** cost of changing speed, and "
        "how often you actually get near **top speed**."
    )

    st.markdown("**Second-half sprint retention**")
    st.caption(
        "Second-half sprint count as a share of the first half. The most direct fatigue signal in "
        "this data — and until now the `sprints_1st_half` / `sprints_2nd_half` columns were parsed "
        "and then read by nothing. Matches under 50 official minutes are excluded: three appearances "
        "here show 18–25 first-half sprints then **zero**, and all three are 45-minute outings. "
        "That is a substitution, not a collapse."
    )
    retention = second_half_retention(filtered)
    if retention.empty:
        st.info("No match in the current filters has both half-splits and enough minutes played.")
    else:
        summary = retention_summary(retention)
        columns = st.columns(max(len(summary), 1))
        for column, (_, row) in zip(columns, summary.iterrows()):
            column.metric(
                MATCH_CATEGORY_LABELS.get(row["match_category"], row["match_category"]),
                f"{row['median_retention']:.2f}×",
                f"n = {int(row['matches'])} · range {row['min_retention']:.2f}–{row['max_retention']:.2f}",
                delta_color="off",
            )
        st.caption(
            "1.00 means the same number of sprints in both halves; 0.50 means output halved after "
            "the break. Median rather than mean, with the range beside it — with this many matches "
            "a single figure should not be read as a level."
        )
        st.plotly_chart(
            px.bar(
                retention.sort_values("date"),
                x="date",
                y="second_half_retention",
                color="match_category",
                labels={"second_half_retention": "2nd half ÷ 1st half", "date": "", "match_category": ""},
            ).add_hline(y=1.0, line_dash="dash", annotation_text="no drop-off"),
        )
        _show_table(retention)

    st.markdown("---")
    st.markdown("**Mechanical load — the axis distance can't measure**")
    st.caption(
        "Accelerations + decelerations: a count of speed *changes*, standing in for the eccentric "
        "cost that damages muscle. Two sessions can cover identical distance while one involves "
        "twice the braking, and every load metric on the Performance Insights tab would call them "
        "the same session."
    )
    mechanical = add_mechanical_load(filtered)
    ratios = pd.to_numeric(mechanical["accel_decel_ratio"], errors="coerce").dropna()
    if ratios.empty:
        st.info("No session in the current filters records both accelerations and decelerations.")
    else:
        median_ratio = float(ratios.median())
        col1, col2, col3 = st.columns(3)
        col1.metric("Median accel : decel", f"{median_ratio:.2f}", classify_accel_decel_ratio(median_ratio), delta_color="off")
        col2.metric(
            "Median mechanical load / min",
            f"{pd.to_numeric(mechanical['mechanical_load_per_min'], errors='coerce').median():.2f}",
        )
        col3.metric("Sessions with both counts", len(ratios))
        st.caption(
            f"Balanced is {BALANCED_ACCEL_DECEL[0]}–{BALANCED_ACCEL_DECEL[1]}. Below that, braking "
            "is outpacing accelerating — decelerating is the eccentric, more damaging half of the "
            "pair. This band is a reasonable symmetry interval, **not** a validated threshold, so "
            "read it as a prompt to check soreness rather than as a diagnosis."
        )
        st.plotly_chart(
            px.scatter(
                mechanical.dropna(subset=["mechanical_load_per_min"]).sort_values("date"),
                x="date", y="mechanical_load_per_min", color="match_category", trendline=None,
                labels={"mechanical_load_per_min": "Accel + decel per minute", "date": "", "match_category": ""},
            ),
        )

        st.markdown("**Load monitoring on the mechanical axis**")
        st.caption(
            "ACWR computed on accel+decel counts instead of distance. The two answer different "
            "questions and routinely disagree: distance load can sit comfortably while speed-change "
            "load spikes, which is exactly the overload a distance-only monitor misses."
        )
        mechanical_acwr = compute_acwr(mechanical, load_col="mechanical_load").dropna()
        distance_acwr = compute_acwr(filtered, load_col="total_distance_m").dropna()
        if mechanical_acwr.empty:
            st.info("Not enough data for a mechanical ACWR yet.")
        else:
            both = pd.DataFrame(
                {"Mechanical (accel+decel)": mechanical_acwr, "Metabolic (distance)": distance_acwr}
            ).dropna(how="all")
            figure = px.line(both, labels={"value": "ACWR", "index": "", "variable": ""})
            figure.add_hrect(y0=0.8, y1=1.3, fillcolor="green", opacity=0.08, line_width=0)
            figure.add_hline(y=1.5, line_dash="dash", annotation_text="high risk")
            st.plotly_chart(figure)
            st.caption(
                "Shaded band is Gabbett's 0.8–1.3 optimal zone. Plotted over time rather than as a "
                "single gauge because a ratio of 1.35 arrived at from 0.9 means something entirely "
                "different from one falling from 1.8."
            )

    st.markdown("---")
    st.markdown("**High-speed exposure**")
    st.caption(
        "How often you actually reach near-maximal speed, as a share of the month's sessions rather "
        "than a count — a month with 18 sessions shouldn't look better than one with 8 just for "
        "being busier. Regular near-max sprinting is a widely used hamstring-injury prevention "
        "target; the reference speed is your own best in the current scope, since no external "
        "benchmark exists for amateur football."
    )
    exposure = high_speed_exposure(filtered)
    if exposure.empty:
        st.info("No top-speed data in the current filters.")
    else:
        st.plotly_chart(
            px.bar(exposure, x="month_label", y="near_max_pct",
                   labels={"near_max_pct": f"% of sessions ≥{int(NEAR_MAX_SPEED_PCT * 100)}% of best", "month_label": ""}),
        )
        _show_table(exposure)

    st.markdown("---")
    st.markdown("**Do you train at the intensity you have to play at?**")
    st.caption(
        "Training's high-speed and sprint share of total distance, as a percentage of the same "
        "share in official matches that month. 100% means training reaches match intensity. Uses "
        "intensity *shares* rather than absolute distances so a shorter session isn't penalised for "
        "being shorter, and months without both a training session and an official match are "
        "dropped rather than compared against nothing."
    )
    gap = training_match_intensity_gap(filtered)
    if gap.empty:
        st.info("Need at least one training session and one official match in the same month.")
    else:
        figure = px.line(
            gap, x="month_label", y=["high_speed_gap_pct", "sprint_gap_pct"], markers=True,
            labels={"value": "% of match intensity", "month_label": "", "variable": ""},
        )
        figure.add_hline(y=100, line_dash="dash", annotation_text="match intensity")
        st.plotly_chart(figure)
        _show_table(gap)


def _body_tab(filtered: pd.DataFrame, season_choice: str) -> None:
    st.subheader("Body composition")
    st.caption(
        "Periodic nutritionist assessments, parsed from the report PDFs by "
        "`tools/nutrition_pdf_to_csv.py` into `data/body/`. **This is anthropometry, not intake** — "
        "nothing here records what was eaten, so every nutritional reading of it is an inference "
        "about what the body did in response to a diet and a training load, only one of which is "
        "measured."
    )

    wide, derived, measurements, changes = _load_body()
    if wide.empty:
        st.info("No body-composition data found in `data/body/`.")
        return

    # The metric universe is read off the files rather than hand-listed, so the
    # eight individual skinfold sites and the raw girths are selectable too.
    # Grouped into families because 62 metrics in one alphabetical list is not a
    # choice anyone can make -- see METRIC_FAMILIES for why these groups.
    all_metrics = body_gps.available_metrics(wide, derived)
    families = st.multiselect(
        "Metric groups",
        list(body_store.METRIC_FAMILIES),
        default=[f for f in body_store.DEFAULT_FAMILIES if f in body_store.METRIC_FAMILIES],
        help="\n\n".join(f"**{name}** — {why}" for name, why in body_store.METRIC_FAMILIES.items()),
    )
    metrics = [m for m in all_metrics if body_store.metric_family(m) in set(families)]
    if not metrics:
        st.info("Pick at least one metric group above.")
        return
    st.caption(
        f"{len(metrics)} of {len(all_metrics)} metrics in scope. Every table and chart below "
        "follows this choice, so narrowing it here narrows the whole tab rather than just one "
        "figure — the headline tiles are the exception and always show the same core set."
    )

    assessments = body_gps.assessment_table(wide, derived, metrics=metrics)
    scoped = assessments if season_choice == ALL_SEASONS else assessments[assessments["season"] == season_choice]
    if scoped.empty:
        st.info(f"No assessments recorded in {season_choice}.")
        return

    latest = scoped.iloc[-1]
    st.markdown(
        f"### {latest['date']:%d %B %Y} · {latest.get('phase', '—')} · {latest['season']}"
        f"  \n<span style='opacity:0.7'>{len(scoped)} assessments in scope"
        f" · previous {scoped.iloc[-2]['date']:%d %b} </span>"
        if len(scoped) > 1
        else f"### {latest['date']:%d %B %Y} · {latest.get('phase', '—')} · {latest['season']}",
        unsafe_allow_html=True,
    )

    # Deliberately built from its own table, not from `scoped`: the headline is a
    # fixed core set, and unticking "Pregas" above should narrow the analysis
    # below without quietly removing tiles from the summary at the top.
    headline_source = body_gps.assessment_table(wide, derived, metrics=body_summary.HEADLINE_METRICS)
    if season_choice != ALL_SEASONS:
        headline_source = headline_source[headline_source["season"] == season_choice]
    headline = body_summary.headline(headline_source)
    if not headline.empty:
        for start in range(0, len(headline), 4):
            for column, (_, row) in zip(st.columns(4), headline.iloc[start : start + 4].iterrows()):
                change = row["change"]
                if row["verdict"] == "noise":
                    delta, colour = f"{change:+.2f} · within noise", "off"
                elif change is None or pd.isna(change):
                    delta, colour = None, "off"
                else:
                    delta, colour = f"{change:+.2f}", _delta_colour(row["unit_direction"])
                column.metric(row["metric"], f"{row['latest_value']:.2f}", delta, delta_color=colour)

    st.caption(
        "Colour follows the metric's **direction**, not the arrow: green means moved the favourable "
        "way. Fat mass and skinfolds are better falling, lean and muscle mass better rising, and "
        "body mass is deliberately grey — for a footballer neither direction is the goal, and "
        "colouring it would assert an aim this data doesn't contain. A change smaller than that "
        "metric's caliper/scale repeatability is labelled *within noise* rather than shaded."
    )

    st.markdown("---")
    baseline_choice = st.radio(
        "Compare against",
        ["first assessment in scope", "previous assessment"],
        horizontal=True,
        help="These routinely disagree — fat mass can be down across a season while up since the last check.",
    )
    baseline = "first" if baseline_choice.startswith("first") else "previous"
    evolution = body_summary.evolution(scoped, metrics, baseline=baseline)
    counts = body_summary.verdict_counts(evolution)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Improved", counts["better"])
    col2.metric("Regressed", counts["worse"])
    col3.metric("Within noise", counts["noise"])
    col4.metric("No direction", counts["neutral"])
    st.caption(
        f"{counts['better'] + counts['worse']} of {counts['directional']} directional metrics moved "
        "meaningfully. Metrics with no favourable direction are excluded from that denominator — "
        "they can't improve or regress."
    )

    display = evolution.assign(
        status=evolution["verdict"].map(VERDICT_LABELS),
        group=evolution["metric"].map(body_store.metric_family),
    )[["group", "metric", "baseline_value", "latest_value", "change", "pct_change", "threshold", "status", "verdict"]]
    st.dataframe(
        _style_by_verdict(display),
        width="stretch",
        hide_index=True,
        # "verdict" drives the row tint but stays out of the view -- "status" is its readable form.
        column_order=["group", "metric", "baseline_value", "latest_value", "change", "pct_change", "threshold", "status"],
    )

    st.markdown("---")
    st.markdown("**Trend**")
    metric_names = [c for c in scoped.columns if c not in {"date", "season", "phase"}]
    # Ordered by family so related metrics sit together in the dropdown rather
    # than alphabetically, which split the five fat-percentage equations apart.
    family_index = {name: i for i, name in enumerate(body_store.METRIC_FAMILIES)}
    metric_names.sort(key=lambda m: (family_index.get(body_store.metric_family(m), 99), m))
    chosen = st.multiselect(
        "Body metrics",
        metric_names,
        default=[m for m in ["Peso", "Massa Gorda", "Massa Isenta de Gordura"] if m in metric_names]
        or metric_names[:3],
        format_func=lambda m: f"{body_store.metric_family(m)} · {m}",
    )
    if chosen:
        trend = scoped.melt(id_vars=["date", "phase"], value_vars=chosen, var_name="metric", value_name="value")
        st.plotly_chart(
            px.line(trend.dropna(subset=["value"]), x="date", y="value", color="metric", markers=True,
                    hover_data=["phase"], labels={"value": "", "date": "", "metric": ""}),
        )

    st.markdown("**By season phase**")
    st.caption(
        "The comparison the football calendar supports: pre-season, first half, second half and "
        "run-in are different training states, and reading a body metric against its phase says "
        "more than reading it against a date."
    )
    _show_table(body_summary.phase_averages(scoped))

    st.markdown("---")
    st.markdown("**Training done vs. body change, block by block**")
    st.caption(
        "One row per gap between assessments: the football played in that block next to how the "
        "body moved across it. Deliberately **side by side and not divided into each other** — with "
        "no intake data and a handful of blocks, a \"kcal per kg\" figure would read as a "
        "calculation when it would be a coincidence. Calories are the GPS unit's own estimate of "
        "the football cost only: no resting metabolism, nothing off the pitch."
    )
    scoped_wide = wide if season_choice == ALL_SEASONS else wide[wide["season"] == season_choice]
    scoped_derived = derived if season_choice == ALL_SEASONS else derived[derived["season"] == season_choice]
    windows = body_gps.assessment_windows(filtered, scoped_wide, scoped_derived)
    if windows.empty:
        st.info("Two assessments are needed before a block can be measured.")
    else:
        columns = ["window_start", "window_end", "phase", "days", "sessions", "sessions_per_week",
                   "km_per_week", "football_kcal_per_day"] + [c for c in windows.columns if c.endswith("(Δ)")]
        _show_table(windows[[c for c in columns if c in windows.columns]])
        st.caption("Blocks with zero sessions are off-season gaps between assessments, not missing data.")

    corrections = body_store.applied_corrections(measurements)
    flagged = body_store.implausible_rows(measurements)
    with st.expander(f"Data quality — {len(corrections)} correction(s) applied, {len(flagged)} value(s) still out of range"):
        if not corrections.empty:
            st.markdown(
                "Values changed from what the report printed. The extraction script keeps the "
                "printed figure in `value_original` rather than overwriting it — a corrected "
                "dataset that can't show what it corrected is just an unsourced one. Dependent "
                "figures are recomputed too, so one transcription fix can produce more than one row."
            )
            _show_table(corrections)
        if not flagged.empty:
            st.error(
                "Still outside their plausible range after corrections — treat these, and anything "
                "derived from them, as missing until the report is rechecked.",
                icon="🚩",
            )
            _show_table(flagged)
        elif not corrections.empty:
            st.success("No value remains outside its plausible range.", icon="✅")

    with st.expander("Which metrics count as better going up, and which going down"):
        st.caption(
            "Shown rather than left implicit: a green arrow means nothing without knowing which way "
            "the metric is supposed to move. Anything not listed here is treated as directionless."
        )
        _show_table(body_summary.direction_legend())


def _body_performance_tab(filtered: pd.DataFrame, season_choice: str) -> None:
    st.subheader("Body × performance — is there any relationship?")
    st.caption(
        "This tab exists to test a question, not to decorate one. Each assessment is paired with "
        "the **average** GPS output over the 28 days *before* it — before, because a body "
        "measurement describes the state you arrived in, and averaged so that a busy block doesn't "
        "score higher on volume alone."
    )

    wide, derived, _, _ = _load_body()
    if wide.empty:
        st.info("No body-composition data found in `data/body/`.")
        return

    metrics = body_gps.available_metrics(wide, derived)
    assessments = body_gps.assessment_table(wide, derived, metrics=metrics)
    scoped = assessments if season_choice == ALL_SEASONS else assessments[assessments["season"] == season_choice]
    if scoped.empty:
        st.info(f"No assessments recorded in {season_choice}.")
        return

    # The binding constraint on this whole tab is how many assessments have any
    # training behind them, and that is a direct function of the window length.
    # Exposing it makes the trade-off the user's to make rather than a constant
    # buried in a module: a short window describes a real training block, a long
    # one pairs more assessments but blurs across blocks.
    lookback = st.select_slider(
        "Lookback window before each assessment",
        options=[14, 28, 42, 60, 90, 120],
        value=28,
        format_func=lambda d: f"{d} days",
        help=(
            "28 days matches the chronic-load window used by ACWR. Widening it brings more "
            "assessments into range at the cost of averaging across different training blocks."
        ),
    )
    performance = performance_link.performance_per_assessment(filtered, scoped, lookback_days=lookback)
    coverage = performance_link.coverage(performance)

    col1, col2, col3 = st.columns(3)
    col1.metric("Assessments in scope", coverage["assessments"])
    col2.metric(
        "With training behind them",
        coverage["paired"],
        delta=f"{-coverage['shortfall']} vs. well-powered" if coverage["shortfall"] else "well powered",
        delta_color="inverse" if coverage["shortfall"] else "normal",
    )
    col3.metric("Sessions paired", int(performance["sessions_in_window"].sum()) if not performance.empty else 0)

    correlations = performance_link.correlate_body_vs_performance(scoped, performance)
    findings = performance_link.summarise_findings(correlations)

    # The analysis runs on whatever overlap exists rather than refusing below a
    # threshold -- the honest handling of thin data is to report it at its real
    # strength, not to withhold it. The coverage caveat sits above the result so
    # it is read first, and every row below carries its own reliability tier.
    if not coverage["analysable"]:
        st.warning(
            f"Only **{coverage['paired']} of {coverage['assessments']}** assessments have any "
            f"training in the {lookback} days before them — fewer than the "
            f"{performance_link.ABSOLUTE_MIN_PAIRS} points a rank correlation needs to exist. "
            "Try a longer window above; the scatter and the phase table below still work.",
            icon="📉",
        )
    else:
        if not coverage["well_powered"]:
            st.warning(
                f"**Underpowered, and analysed anyway.** {coverage['paired']} of "
                f"{coverage['assessments']} assessments have training in the {lookback} days "
                f"before them — {coverage['shortfall']} short of the "
                f"{performance_link.MIN_PAIRS} at which a coefficient carries real weight. The "
                "limit is **overlap, not method**: the body record starts about a year before the "
                "GPS record. Everything below is computed on the data that exists and labelled "
                "with the strength it actually has — read it as a direction to re-check next "
                "season, never as a result.",
                icon="⚖️",
            )
        if findings["survivors"] == 0:
            st.info(f"**{findings['verdict']}** {findings['detail']}", icon="🔍")
        elif findings["underpowered"]:
            # Green here would be the whole tab undone: a survivor found at this
            # sample size is a lead, and reads as a conclusion if it is styled
            # like one.
            st.warning(f"**{findings['verdict']}** {findings['detail']}", icon="🔍")
        else:
            st.success(f"**{findings['verdict']}** {findings['detail']}", icon="🔍")

    if not correlations.empty:
        st.markdown("---")
        st.markdown("**All tested pairs, strongest first**")
        st.caption(
            "Spearman rank correlation, so no linearity is assumed and one pre-season outlier can't "
            "drag the coefficient. `q_value` is the Benjamini-Hochberg adjusted p-value across the "
            "whole grid — with this many pairs several will clear p<0.05 by chance, and "
            "`survives_fdr` is the only column worth acting on. `reliability` is read straight off "
            "`n`: **worth acting on** at "
            f"{performance_link.MIN_PAIRS}+ points, **indicative** at 6–{performance_link.MIN_PAIRS - 1}, "
            f"**anecdotal** below that. Even a survivor means *these moved together*: body "
            "composition, training load and match minutes all drift together across a season."
        )
        only_solid = st.checkbox(
            f"Only pairs with {performance_link.MIN_PAIRS}+ paired assessments",
            value=False,
            help="Off by default — with this dataset it usually empties the table, which is itself the finding.",
        )
        shown = correlations[correlations["n"] >= performance_link.MIN_PAIRS] if only_solid else correlations
        if shown.empty:
            st.info(
                f"No pair reaches {performance_link.MIN_PAIRS} paired assessments yet. That is the "
                "honest state of the overlap, not a rendering problem.",
                icon="📉",
            )
        else:
            _show_table(shown)

    st.markdown("---")
    st.markdown("**The paired observations themselves**")
    st.caption(
        "Looking at the points is legitimate even when there are too few to test — as long as "
        "nothing calls the line through them a result."
    )
    body_names = [c for c in scoped.columns if c not in {"date", "season", "phase"}]
    performance_names = [m for m in performance_link.DEFAULT_PERFORMANCE_METRICS if m in performance.columns]
    if not body_names or not performance_names:
        st.info("Nothing to pair yet.")
        return

    col1, col2 = st.columns(2)
    with col1:
        body_metric = st.selectbox(
            "Body metric", body_names,
            index=body_names.index("Massa Gorda") if "Massa Gorda" in body_names else 0,
        )
    with col2:
        performance_metric = st.selectbox("Performance metric", performance_names, format_func=_metric_label)

    points = performance_link.paired_observations(scoped, performance, body_metric, performance_metric)
    if points.empty:
        st.info("No overlapping observations for that pair.")
    else:
        st.plotly_chart(
            px.scatter(
                points, x=body_metric, y=performance_metric, color="phase", text=points["date"].dt.strftime("%b %y"),
                labels={performance_metric: _metric_label(performance_metric), "phase": ""},
            ).update_traces(textposition="top center"),
        )
        _show_table(points)

    st.markdown("---")
    st.markdown("**Performance by season phase**")
    st.caption(
        "A comparison the calendar supports where a correlation doesn't: these are different "
        "training blocks, not points on a trend line spanning two off-seasons."
    )
    _show_table(performance_link.phase_profile(performance))

    with st.expander("Why this analysis is built the way it is"):
        st.markdown(
            f"""
**The multiplicity problem.** ~{len(body_names)} body metrics against
{len(performance_names)} performance metrics is a grid of several hundred tests. At n≈20, a
handful will clear p<0.05 from noise alone. Reporting the strongest few from such a grid without
correction is how a search becomes a "finding", so every p-value here carries a
Benjamini-Hochberg q-value computed over the **whole** grid that was tested — not just the pairs
that looked interesting.

**Why Spearman.** Body composition moves in small monotonic drifts with occasional step changes.
Rank correlation doesn't assume a straight line and isn't dragged by one outlying pre-season
measurement.

**Why pairs below {performance_link.MIN_PAIRS} observations are dropped entirely.** With 5 points a
rank correlation of 0.9 is unremarkable. Reporting those with a caveat attached just moves the
error into a footnote nobody reads.

**Why nothing here is causal, even if something survives.** Fat mass falls through pre-season
while running volume rises; match minutes climb as fitness returns. Body composition, training
load and the calendar all move together, so a correlation between any two of them is expected
without either driving the other. The honest reading is always *"these moved together"*.
            """
        )


def main() -> None:
    st.title("🏃 GPS Performance Analysis")

    sessions = _load()
    if sessions.empty:
        st.warning("No GPS sessions found yet. Add one below to get started.")
        _add_session_form()
        return

    # The selector spans both datasets, not just GPS. The body record starts about
    # a year earlier, and building the list from sessions alone made 11 assessments
    # in 2024/25 unreachable -- there was no season to select them under.
    gps_seasons = set(sessions["season"].unique())
    body_seasons = set(_load_body()[0].get("season", pd.Series(dtype=str)).unique())
    seasons = sorted(gps_seasons | body_seasons)
    season_choice = st.sidebar.selectbox("Season", [ALL_SEASONS, *seasons])
    if season_choice != ALL_SEASONS and season_choice not in gps_seasons:
        st.sidebar.caption(
            f"No GPS sessions in {season_choice} — body-composition tabs still apply, "
            "the performance tabs will be empty."
        )

    categories = st.sidebar.multiselect(
        "Match category",
        MATCH_CATEGORIES,
        default=MATCH_CATEGORIES,
        format_func=lambda c: MATCH_CATEGORY_LABELS[c],
    )

    min_date, max_date = sessions["date"].min().date(), sessions["date"].max().date()
    date_range = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)

    category_scope = sessions[sessions["match_category"].isin(categories)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        category_scope = category_scope[(category_scope["date"] >= pd.Timestamp(start)) & (category_scope["date"] <= pd.Timestamp(end))]

    filtered = category_scope if season_choice == ALL_SEASONS else category_scope[category_scope["season"] == season_choice]

    analyzer = PerformanceAnalyzer(filtered)
    # Season Summary always reflects every season in scope, regardless of the Season selector above.
    overall_analyzer = PerformanceAnalyzer(category_scope)

    tabs = st.tabs(
        [
            "Overview",
            "Monthly",
            "Weekly Load",
            "Intensity",
            "Trends",
            "Baseline",
            "Quality",
            "Season Summary",
            "Performance Insights",
            "Physical Profile",
            "Body Composition",
            "Body × Performance",
            "Add Session",
        ]
    )

    # Opponent, venue and result come out of the session's own label
    # ("Jornada 11 - Vila Viçosa (FORA) 2-3"), not from the fixture scrape. The
    # label is on every game session including friendlies; the scrape reached 13
    # of 26 official matches and nothing else.
    labelled = add_match_label_columns(filtered)

    with tabs[0]:
        st.subheader("Sessions")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total sessions", len(filtered))
        col2.metric("Total distance (km)", round(filtered["total_distance_m"].sum() / 1000, 1))
        col3.metric("Season", season_choice)

        # Merged onto the session rows rather than sitting in a table of their
        # own: "6260 m on 17 Jan" and "6260 m away to Vila Viçosa, won 3-2" are
        # the same number with very different readability.
        context_columns = ["opponent", "venue", "scoreline", "team_result"]
        front = ["date", "session_kind", "session_type", "match_category"] + context_columns
        table = labelled.sort_values("date", ascending=False)
        table = table[[c for c in front if c in table.columns] + [c for c in table.columns if c not in front]]
        _show_table(table)

        games = labelled[labelled["session_kind"] == "game"]
        if not games.empty:
            unresolved = games[games["team_result"].isna()]
            st.caption(
                f"Opponent, venue and result are **read out of `session_type`**, so they cover all "
                f"{len(games)} game sessions in scope — friendlies included, which no fixture list "
                "holds. `scoreline` is written **home-first** as the label writes it, and "
                "`team_result` is from your team's side of it."
                + (
                    f" {len(unresolved)} row(s) have no result: the label records the score as `?-?`."
                    if not unresolved.empty
                    else ""
                )
            )

    with tabs[1]:
        st.subheader("Monthly comparison")
        st.pyplot(analyzer.plot_monthly_comparison())

    with tabs[2]:
        st.subheader("Weekly load")
        if season_choice == ALL_SEASONS and len(seasons) > 1:
            st.info("Week numbers restart every season — pick a specific season above for a meaningful weekly breakdown.")
        weekly = analyzer.weekly_load()
        if weekly.empty:
            st.info("No data for the current filters.")
        else:
            for category, label in WEEKLY_GROUPS:
                st.markdown(f"**{label}**")
                cols = ["week"] + [f"{category}_{metric}" for metric in WEEKLY_METRICS]
                _show_table(weekly[[c for c in cols if c in weekly.columns]])
            fig = analyzer.plot_weekly_load_heatmap()
            if fig is not None:
                st.plotly_chart(fig)

    with tabs[3]:
        st.subheader("Training vs official vs practice intensity")
        st.pyplot(analyzer.plot_intensity_radar())
        st.subheader("Starter vs substitute (all games)")
        _show_table(analyzer.starter_vs_substitute())

        # The same question the two blocks above ask -- does output differ by the
        # context a match was played in -- split two more ways, off the labels.
        resolved = labelled[labelled["team_result"].notna()]
        if not resolved.empty:
            st.subheader("By match context")
            categories = ", ".join(
                MATCH_CATEGORY_LABELS.get(c, c) for c in sorted(resolved["match_category"].dropna().unique())
            )
            st.caption(
                f"{len(resolved)} games with a recorded result, covering: **{categories}** — this "
                "follows the sidebar's Match category filter, so narrow it there to separate "
                "official matches from friendlies. Rates use **match-sheet minutes** as the "
                f"denominator, not GPS runtime, and appearances under {MINUTES_FLOOR:.0f} official "
                "minutes are excluded: a cameo extrapolates to a per-90 rate no full match would "
                "sustain, and a couple of those would decide the ordering."
            )
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**By team result**")
                _show_table(output_by(resolved, "team_result"))
            with col2:
                st.markdown("**By venue**")
                _show_table(output_by(resolved, "venue"))
            st.caption(
                "`n` is not decoration — at these bucket sizes these are descriptions of the data, "
                "not evidence about how you play. And a team result is a team outcome: reading "
                "higher distance in defeats as *cause* runs both ways, since chasing a game "
                "produces running and so does a game that was always going to be chased."
            )

    with tabs[4]:
        st.subheader("Performance trends")
        metric_options = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh"]
        chosen = st.multiselect("Metrics", metric_options, default=["total_distance_m"], format_func=_metric_label)
        if chosen:
            st.pyplot(analyzer.plot_performance_trends(chosen))

        st.subheader("Best / worst sessions")
        col1, col2 = st.columns(2)
        with col1:
            metric = st.selectbox("Metric", metric_options, format_func=_metric_label, key="best_worst_metric")
        with col2:
            category = st.selectbox(
                "Match category", MATCH_CATEGORIES, format_func=lambda c: MATCH_CATEGORY_LABELS[c], key="best_worst_category"
            )
        st.pyplot(analyzer.plot_best_worst(metric=metric, category=category))

    with tabs[5]:
        st.subheader("Baseline comparison")
        st.caption(
            "Position-specific baselines sourced from published research (Di Salvo et al. 2007 for distance "
            "metrics; a separate GPS accel/decel study for accelerations/decelerations) — not the old "
            "spreadsheet's unsourced flat baseline. Training baselines are estimated from the match baseline "
            "using a documented intensity ratio, since no position-specific training study was found. "
            "Full sourcing: `docs/gps_analysis.md`."
        )

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            position = st.selectbox(
                "Position", POSITIONS, format_func=lambda p: POSITION_LABELS[p], key="baseline_position"
            )
        with bcol2:
            category = st.selectbox(
                "Match category", MATCH_CATEGORIES, format_func=lambda c: MATCH_CATEGORY_LABELS[c], key="baseline_category"
            )

        mcol1, mcol2, mcol3 = st.columns(3)
        mcol1.metric("Avg Training Duration (min)", analyzer.average_minutes("training"))
        mcol2.metric("Avg Official Match Duration (min)", analyzer.average_minutes("official_match"))
        mcol3.metric("Avg Practice Match Duration (min)", analyzer.average_minutes("practice_match"))
        st.caption(
            "Baselines are expressed per 90 minutes; the averages above show how far your actual session "
            "length is from that basis. A session much shorter than 90 minutes (e.g. a late substitute "
            "appearance) can show an inflated per-90 rate for bursty metrics like sprint distance — the rate "
            "is real, but extrapolating a short high-intensity spell across a full 90 minutes overstates what "
            "a full match at that pace would actually look like."
        )

        _show_table(analyzer.compare_to_baseline(category, position=position))

    with tabs[6]:
        st.subheader("Monthly quality evolution")
        st.caption("Blends training (60%) and official-match (40%) intensity. Practice matches aren't included.")
        fig = analyzer.plot_quality_evolution()
        if fig is not None:
            st.pyplot(fig)
        else:
            st.info("Not enough data to compute a quality trend yet.")

    with tabs[7]:
        st.subheader("Season Summary")
        st.caption("Always covers every season (ignores the Season filter above) — this is the career-wide view.")
        summary = overall_analyzer.season_summary()
        _show_table(summary)
        if len(summary) > 1:
            st.bar_chart(summary.set_index("season")["total_distance_km"])
            st.line_chart(summary.set_index("season")["avg_quality_score"])
        else:
            st.info("Only one season of data so far — this becomes more useful once a second season is added.")

    with tabs[8]:
        st.subheader("Performance Insights")
        st.caption(
            "Per-90 normalization and percentile comparison are adapted from SkillCorner's physical-data "
            "methodology; ACWR/Monotony/Strain are general sports science, not SkillCorner-specific. See "
            "the Methodology section below for exactly what's borrowed vs. adapted vs. general."
        )
        st.caption(
            "Everything on this tab uses the **same scope as the sidebar filters above** — Season, Match "
            "category, and Date range. Switching those changes every gauge and table here too."
        )

        scope = analyzer.sessions.sort_values("date")

        st.markdown("**Load monitoring**")
        lcol1, lcol2, lcol3 = st.columns(3)

        with lcol1:
            acwr_series = compute_acwr(scope).dropna()
            if not acwr_series.empty:
                latest_acwr = acwr_series.iloc[-1]
                st.plotly_chart(acwr_gauge(latest_acwr))
                st.caption(f"Zone: **{classify_acwr(latest_acwr)}** — 7-day load vs. 28-day average.")
            else:
                st.info("Not enough data for ACWR yet.")

        weekly = weekly_monotony_and_strain(scope).dropna(subset=["monotony"])
        with lcol2:
            if not weekly.empty:
                latest_monotony = weekly.iloc[-1]["monotony"]
                st.plotly_chart(monotony_gauge(latest_monotony))
                st.caption(f"Zone: **{classify_monotony(latest_monotony)}** — mean daily load ÷ its SD, this week.")
            else:
                st.info("Not enough data for training monotony yet (need 2+ sessions in a week).")
        with lcol3:
            if not weekly.empty:
                latest_strain = weekly.iloc[-1]["strain"]
                typical_strain = weekly["strain"].median()
                st.plotly_chart(strain_gauge(latest_strain, typical_strain))
                st.caption("Weekly load × monotony, vs. your own median week (black line) — no universal scale exists for this one.")
            else:
                st.info("Not enough data for training strain yet.")

        st.markdown("---")
        st.markdown("**Form**")
        gcol1, gcol2 = st.columns(2)

        with gcol1:
            quality = analyzer.monthly_quality_metric()
            if not quality.empty:
                st.plotly_chart(quality_gauge(quality.iloc[-1]["combined_quality"]))
                st.caption(f"Latest month: {quality.iloc[-1]['month_label']}.")
            else:
                st.info("Not enough data for a quality score yet.")

        with gcol2:
            speeds = robust_top_speed(scope).dropna()
            if not speeds.empty:
                personal_best = scope["top_speed_kmh"].max()
                st.plotly_chart(top_speed_gauge(speeds.iloc[-1], personal_best))
                st.caption("Rolling 95th-percentile of the last 10 sessions' top speed — see Methodology.")
            else:
                st.info("Not enough data for a robust top speed yet.")

        st.markdown("---")
        st.markdown("**Latest session, ranked against the current filters' history**")
        st.caption(
            "\"Current filters\" = the Season / Match category / Date range picked in the sidebar — the same "
            "`scope` this whole tab uses, not a separate filter. **How the percentile works**: it's the share "
            "of sessions *within that scope* whose value was lower than your latest session's — e.g. 80% means "
            "4 out of 5 sessions in the current scope had less of that metric than your latest one did. It's "
            "relative to your own recorded history in the current scope, not to any external/positional "
            "benchmark (that comparison lives in the Baseline tab instead)."
        )
        pcol1, pcol2, pcol3, pcol4 = st.columns(4)
        rank_metric_options = ["total_distance_m", "sprint_distance_m", "high_speed_distance_m", "top_speed_kmh"]
        with pcol1:
            rank_metric = st.selectbox("Metric", rank_metric_options, format_func=_metric_label, key="percentile_metric")
        latest_row = scope.dropna(subset=[rank_metric]).tail(1)
        if not latest_row.empty:
            rank = percentile_rank(scope[rank_metric], latest_row.iloc[0][rank_metric])
            with pcol2:
                st.plotly_chart(percentile_gauge(rank, f"{_metric_label(rank_metric)} Percentile"))
            intensity = add_intensity_ratios(scope).iloc[-5:]
            with pcol3:
                avg_hi_pct = intensity["high_speed_pct"].mean()
                st.plotly_chart(intensity_gauge(avg_hi_pct, "High-Speed % (last 5)", max_val=max(avg_hi_pct * 2, 10)))
            with pcol4:
                avg_sprint_pct = intensity["sprint_pct"].mean()
                st.plotly_chart(intensity_gauge(avg_sprint_pct, "Sprint % (last 5)", max_val=max(avg_sprint_pct * 2, 10)))
        else:
            st.info(f"No sessions with {_metric_label(rank_metric)} recorded yet.")

        st.markdown("---")
        st.markdown("**Per-90-minute rates** — comparable across sessions regardless of duration")
        st.caption(
            "The denominator is **match-sheet minutes** (`minutes_game_zerozero`, the time "
            "zerozero.pt records you as having played) wherever they exist, and the GPS unit's "
            "runtime otherwise. `minutes_source` says which was used per row. This matters: the "
            "unit typically runs about 7 minutes longer than the match sheet, so dividing a match "
            "by runtime understates every rate by roughly that much. Rates are blank for a match "
            "with zero minutes — an unused substitute has no rate, and `0` would be a "
            "divide-by-zero rather than a real value."
        )
        # official_minutes() prefers the match sheet and falls back to GPS runtime,
        # so one table now covers training and matches on the right denominator for
        # each, instead of applying the runtime to both.
        per90 = flag_short_appearances(add_per90_columns(official_minutes(scope), minutes_col="official_minutes"))
        per90_cols = [
            "date", "session_kind", "match_category", "official_minutes", "minutes_source",
            "short_appearance",
        ] + [f"{m}_per90" for m in PER90_METRICS if f"{m}_per90" in per90.columns]
        _show_table(per90[per90_cols].sort_values("date", ascending=False).head(20))
        st.caption(
            f"**`short_appearance` marks rows under {MINUTES_FLOOR:.0f} official minutes, where the "
            "rate is extrapolation rather than measurement.** A 9-minute cameo covering 2070 m "
            "scales to 20 700 m per 90 — arithmetically correct, and a match nobody has played: a "
            "cameo is spent chasing a game at an intensity no one holds for 90 minutes. The rows "
            "are kept because the sessions happened, and flagged because the numbers don't compare. "
            "The aggregates elsewhere in the dashboard exclude them outright."
        )

        overhang = minutes_overhang(scope)
        if not overhang.empty:
            under = overhang[overhang["note"] == "unit under-recorded"]
            label = f"Recording overhang — why the match sheet is the denominator ({len(overhang)} matches)"
            with st.expander(label):
                col1, col2, col3 = st.columns(3)
                col1.metric("Matches with both counts", len(overhang))
                col2.metric("Median overhang (min)", round(float(overhang["minutes_overhang"].median()), 1))
                col3.metric("Sessions with lost data", len(under))
                st.caption(
                    "A **positive** overhang is the normal case: the unit goes on before you come "
                    "onto the pitch and gets forgotten after the whistle. That is instrumentation, "
                    "not error — both numbers are honest about what they measure, and the match "
                    "sheet is simply the right denominator for a per-90 rate. The one case that "
                    "does cost data is a **negative** overhang, where the unit missed real playing "
                    "time and that session's distance and sprint *totals* are undercounts."
                )
                if not under.empty:
                    st.error(
                        "Undercounted totals on: "
                        + ", ".join(f"{d:%d %b %Y}" for d in under["date"])
                        + " — the unit recorded less than the match lasted, so no denominator "
                        "fixes these.",
                        icon="🚩",
                    )
                _show_table(overhang)

        with st.expander("Methodology — what's SkillCorner, what's adapted, what's general sports science"):
            st.markdown(
                """
**Directly from SkillCorner's methodology** ([skillcornerviz](https://github.com/liamMichaelBailey/skillcornerviz),
their open-source physical-data toolkit):
- **Per-90 normalization** — `add_standard_metrics()` in `skillcorner_physical_utils.py` normalizes distance/accel/decel/sprint
  counts per 90 minutes so sessions of different lengths are comparable. Same idea, applied above.
- **Percentile-based comparison** — their `summary_table.py`/`table_grid.py` color tables by percentile rather than raw value.
  We have no peer group (single player), so this ranks a session against the *player's own* history instead — see the
  explanation above the percentile gauge for exactly how that's computed.
- **HI/Sprint thresholds** — SkillCorner defines High-Intensity distance as **>19.8 km/h** and Sprint distance as
  **>25.2 km/h**. We don't recompute these (no raw speed stream to threshold), but this repo's `high_speed_distance_m`/
  `sprint_distance_m` categories already match that convention.

**Inspired by, but explicitly *not*, a SkillCorner metric:**
- **Robust Top Speed** — SkillCorner's real **PSV-99** is the 99th percentile over thousands of raw in-match speed
  *samples*, designed to discount one glitchy sample. We only have one already-aggregated max speed per *session* — over
  a ~10-session window the 99th percentile would just equal "the max of the window" (no noise-robustness gained), so this
  uses the **95th percentile of the last 10 sessions'** top speeds instead. Different granularity, same spirit.

**General sports science, not SkillCorner-specific** (moved to `gps/load_monitoring.py`):
- **ACWR (Acute:Chronic Workload Ratio)** — Gabbett (2016). 7-day load ÷ 28-day average load. `<0.8` undertrained,
  `0.8–1.3` optimal, `1.3–1.5` elevated risk, `>1.5` high risk.
- **Training Monotony & Strain** — Foster (1998). Monotony = mean daily load ÷ its standard deviation over the week
  (high monotony = every day looks the same, no easier days); Strain = weekly load × monotony (a big week that was
  *also* monotonous — the combination linked to overtraining risk more than either figure alone). ~2.0+ monotony with
  a high weekly load is a commonly cited caution point, not a validated hard threshold. Strain has no fixed scale, so
  its gauge is relative to your own median week instead of fixed colored zones.
- Both use `total_distance_m` as the load input, not session-RPE (the field's more standard input) — this dataset
  doesn't collect a subjective-exertion rating. A real substitution, disclosed rather than hidden.

Full writeup with source links: `docs/skillcorner_metrics.md` and `docs/load_monitoring.md` in the repo.
                """
            )

    with tabs[9]:
        _physical_profile_tab(filtered)

    with tabs[10]:
        _body_tab(filtered, season_choice)

    with tabs[11]:
        _body_performance_tab(filtered, season_choice)

    with tabs[12]:
        _add_session_form()


if __name__ == "__main__":
    main()
