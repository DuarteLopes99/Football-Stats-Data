"""Attach league-fixture context to GPS match sessions, and use the official
match-sheet minutes (``minutes_game_zerozero``) as the per-90 denominator.

Two asymmetries make this join worth doing carefully rather than naively:

**The fixture data is about the team; the GPS data is about one player.** A
fixture row says "Mansores lost 1-3 away to Espinho B"; the GPS row says how far
*this player* ran while on the pitch for part of that match. Joining them adds
context (opponent, venue, scoreline, result) to a session — it does not turn a
team result into a measure of individual performance. Splits like "distance in
wins vs. losses" are descriptive at best: the player is one of eleven, the
sample is a couple of dozen matches, and minutes played vary from 0 to 98.
``output_by_result`` therefore always reports ``n`` alongside every mean.

**Two different minute counts exist per match, and they measure different things.**
``duration_min`` is how long the GPS unit was recording; ``minutes_game_zerozero``
is the official match-sheet time from zerozero.pt. The gap between them is
**instrumentation, not error**: the unit is usually switched on before coming
onto the pitch and forgotten for a while after the final whistle (56 recorded
vs. 45 official), and occasionally started late (54 recorded vs. 65 official).
Both numbers are honest about what they measure.

That still matters for per-90 rates, where the official figure is the right
denominator because it is the time actually spent playing. ``minutes_overhang``
quantifies how much recording sits outside the match sheet, so the size of the
correction is visible rather than assumed — and so a session where the unit
missed real playing time (a negative overhang, where the GPS *totals* are
short) can be told apart from the ordinary case.

Only official matches can link: practice matches ("Treino") aren't league
fixtures and have no row to join to.
"""

from __future__ import annotations

import pandas as pd

from football_stats.config import SeasonConfig, list_seasons

OFFICIAL_COMPETITION_TYPES = {"Campeonato", "Taça"}
"""``competition_type`` values that correspond to a real fixture (see
``gps/analyzer.py``'s match categories — practice matches are "Treino")."""

FIXTURE_COLUMNS = [
    "fixture_date",
    "competition",
    "matchweek",
    "venue",
    "opponent",
    "goals_for",
    "goals_against",
    "scoreline",
    "team_result",
]

PER90_MATCH_METRICS = [
    "total_distance_m",
    "sprint_distance_m",
    "high_speed_distance_m",
    "accelerations",
    "decelerations",
    "sprints_total",
]

LARGE_OVERHANG_MIN = 10.0
"""Overhang above which the recording window is flagged as notably wider than
the match itself. Not an error threshold — a big overhang is normal when the
unit runs through the warm-up and warm-down. It is the point past which the
per-90 correction is large enough (roughly a fifth on a typical appearance)
that it is worth knowing the rate moved a lot."""

MINUTES_FLOOR = 20.0
"""Official minutes below which a per-90 rate is extrapolation, not measurement.

A 9-minute substitute stint covering 2070 m becomes 20 700 m per 90 — a rate no
full match has ever sustained. The number is arithmetically correct and
practically meaningless: a cameo is spent chasing the game at an intensity
nobody holds for 90 minutes, so scaling it up describes a match that could not
happen.

Aggregates (``output_by_result``, ``output_by_venue``) **exclude** these rows,
because a couple of them decide the ordering of a bucket of four matches.
Per-session listings **keep** them and flag them instead — the session happened,
and deleting a row from a log is worse than labelling it."""

UNDER_RECORDING_MIN = -5.0
"""Overhang below which the unit recorded **less** than the official playing
time, meaning the GPS totals themselves are missing part of the match. Unlike a
positive overhang this one does compromise the data: distance and sprint counts
for that session are undercounts, and no denominator fixes that."""


def load_primary_team_fixtures(season: SeasonConfig) -> pd.DataFrame:
    """Played fixtures for the season's primary team, from that team's own point of view.

    Reads the team's raw scrape (the processed tables carry no date, so they
    cannot be joined to dated GPS sessions). ``Result`` is always
    "home score-away score" regardless of which side the tracked team is on —
    the same trap that produced the home/away swap bug fixed in
    ``season/fixtures.py`` — so goals are assigned via ``Location``, not by
    reading the score left-to-right.
    """
    path = season.raw_dir / f"{season.primary_team}_fixtures.csv"
    if not path.exists():
        return pd.DataFrame(columns=FIXTURE_COLUMNS)

    raw = pd.read_csv(path)
    played = raw[raw["Played?"] == True].copy()  # noqa: E712
    if played.empty:
        return pd.DataFrame(columns=FIXTURE_COLUMNS)

    scores = played["Result"].astype(str).str.split("-", expand=True)
    home_goals = pd.to_numeric(scores[0], errors="coerce")
    away_goals = pd.to_numeric(scores[1], errors="coerce")
    at_home = played["Location"] == "(C)"

    out = pd.DataFrame(
        {
            "fixture_date": pd.to_datetime(played["Date"]),
            "competition": played["Competition"],
            "matchweek": played["Matchweek"].astype(str),
            "venue": at_home.map({True: "home", False: "away"}),
            "opponent": played["Team2"],
            "goals_for": home_goals.where(at_home, away_goals),
            "goals_against": away_goals.where(at_home, home_goals),
            "scoreline": played["Result"],
        }
    )
    out["team_result"] = out.apply(_result_letter, axis=1)
    return out.dropna(subset=["fixture_date"]).sort_values("fixture_date").reset_index(drop=True)


def _result_letter(row) -> str | None:
    if pd.isna(row["goals_for"]) or pd.isna(row["goals_against"]):
        return None
    if row["goals_for"] > row["goals_against"]:
        return "W"
    if row["goals_for"] < row["goals_against"]:
        return "L"
    return "D"


def link_sessions_to_fixtures(
    sessions: pd.DataFrame, season: SeasonConfig, tolerance_days: int = 1
) -> pd.DataFrame:
    """Add fixture context columns to every session; official matches may match a fixture.

    A one-day tolerance is deliberate: at least one match in the current data is
    logged in the GPS file a day after the fixture date (2025-10-26 vs. the
    fixture's 2025-10-25), and an exact-date join would silently drop it.
    ``fixture_match`` records how each row was resolved ("exact", "±Nd",
    "unmatched", or "not an official match") so a near-miss never passes as a
    confirmed link.
    """
    linked = sessions.copy()
    for column in [*FIXTURE_COLUMNS, "fixture_match", "days_from_fixture"]:
        linked[column] = None

    fixtures = load_primary_team_fixtures(season)
    official_mask = _official_mask(linked)
    linked.loc[~official_mask, "fixture_match"] = "not an official match"
    if fixtures.empty or not official_mask.any():
        linked.loc[official_mask, "fixture_match"] = "unmatched"
        return linked

    official = linked.loc[official_mask, ["date"]].sort_values("date")
    matched = pd.merge_asof(
        official,
        fixtures,
        left_on="date",
        right_on="fixture_date",
        direction="nearest",
        tolerance=pd.Timedelta(days=tolerance_days),
    ).set_index(official.index)

    for column in FIXTURE_COLUMNS:
        linked.loc[matched.index, column] = matched[column]

    offset = (matched["date"] - matched["fixture_date"]).dt.days
    linked.loc[matched.index, "days_from_fixture"] = offset
    linked.loc[matched.index, "fixture_match"] = offset.apply(_match_quality)
    return linked


def _match_quality(offset) -> str:
    if pd.isna(offset):
        return "unmatched"
    if offset == 0:
        return "exact"
    return f"{int(offset):+d}d"


def _official_mask(sessions: pd.DataFrame) -> pd.Series:
    return (sessions["session_kind"] == "game") & sessions["competition_type"].isin(
        OFFICIAL_COMPETITION_TYPES
    )


def official_minutes(sessions: pd.DataFrame) -> pd.DataFrame:
    """Add ``official_minutes`` / ``minutes_source`` — match-sheet time where known.

    Falls back to the GPS unit's runtime when the match sheet wasn't recorded
    (22 of the current file's sessions have it, the rest don't), and yields NaN
    for a session with zero minutes — an unused substitute has no rate to
    compute, and ``0`` would otherwise become a divide-by-zero.
    """
    df = sessions.copy()
    sheet = pd.to_numeric(df.get("minutes_game_zerozero"), errors="coerce")
    gps = pd.to_numeric(df.get("duration_min"), errors="coerce")

    df["official_minutes"] = sheet.where(sheet > 0, gps.where(gps > 0))
    df["minutes_source"] = pd.Series("none", index=df.index)
    df.loc[gps > 0, "minutes_source"] = "gps_runtime"
    df.loc[sheet > 0, "minutes_source"] = "match_sheet"
    return df


def minutes_overhang(sessions: pd.DataFrame) -> pd.DataFrame:
    """One row per session with both minute counts, and the recording overhang.

    ``minutes_overhang`` = GPS runtime − match-sheet minutes, i.e. how much of
    the recording sits outside actual playing time. Positive is the normal
    case (unit on early, off late). ``note`` distinguishes the two readings
    that matter:

    - ``"unit under-recorded"`` (overhang below ``UNDER_RECORDING_MIN``) — the
      unit missed real playing time, so this session's distance and sprint
      **totals** are undercounts. The only genuinely lossy case.
    - ``"wide recording window"`` (overhang above ``LARGE_OVERHANG_MIN``) —
      ordinary warm-up/warm-down overhang, but large enough that per-90 rates
      shift a lot once the match sheet is used as the denominator.
    """
    df = sessions.copy()
    sheet = pd.to_numeric(df.get("minutes_game_zerozero"), errors="coerce")
    gps = pd.to_numeric(df.get("duration_min"), errors="coerce")
    both = sheet.notna() & gps.notna() & (sheet > 0)
    if not both.any():
        return pd.DataFrame(
            columns=["date", "session_type", "duration_min", "minutes_game_zerozero",
                     "minutes_overhang", "overhang_pct", "note"]
        )

    overhang = (gps[both] - sheet[both]).round(1)
    out = pd.DataFrame(
        {
            "date": df.loc[both, "date"],
            "session_type": df.loc[both, "session_type"],
            "duration_min": gps[both],
            "minutes_game_zerozero": sheet[both],
            "minutes_overhang": overhang,
            "overhang_pct": (overhang / sheet[both] * 100).round(1),
        }
    )
    out["note"] = ""
    out.loc[out["minutes_overhang"] > LARGE_OVERHANG_MIN, "note"] = "wide recording window"
    out.loc[out["minutes_overhang"] < UNDER_RECORDING_MIN, "note"] = "unit under-recorded"
    return out.sort_values("date", ascending=False).reset_index(drop=True)


def add_match_per90(sessions: pd.DataFrame, metrics: list[str] | None = None) -> pd.DataFrame:
    """Add ``{metric}_per90_official`` columns normalized by ``official_minutes``.

    Distinct from ``skillcorner_metrics.add_per90_columns``, which divides by
    ``duration_min`` (the GPS unit's runtime) and applies to every session type.
    This one is for matches, where the match sheet says how long the player was
    actually on the pitch.
    """
    df = official_minutes(sessions)
    minutes = df["official_minutes"]
    safe_minutes = minutes.where(minutes > 0)
    for metric in metrics or PER90_MATCH_METRICS:
        if metric in df.columns:
            values = pd.to_numeric(df[metric], errors="coerce")
            df[f"{metric}_per90_official"] = (values / safe_minutes * 90).round(2)
    return df


def flag_short_appearances(sessions: pd.DataFrame, minutes_floor: float = MINUTES_FLOOR) -> pd.DataFrame:
    """Add ``short_appearance`` — True where a per-90 rate is an extrapolation.

    Applied to per-session listings, which keep cameo rows rather than dropping
    them. The flag is what makes the rate readable: without it a 20 700 m/90 row
    sits in the same column as a 9 500 m/90 row and looks like the best match of
    the season.
    """
    df = sessions.copy() if "official_minutes" in sessions.columns else official_minutes(sessions)
    minutes = pd.to_numeric(df["official_minutes"], errors="coerce")
    df["short_appearance"] = minutes.notna() & (minutes < minutes_floor)
    return df


def output_by_result(
    linked: pd.DataFrame, metrics: list[str] | None = None, minutes_floor: float = MINUTES_FLOOR
) -> pd.DataFrame:
    """Mean per-90 output split by the team's result, with ``n`` always shown.

    ``minutes_floor`` drops cameo appearances: a 6-minute substitute stint
    extrapolates to a per-90 rate that no full match would ever sustain, and
    with a handful of matches per bucket a couple of those decide the ordering.
    The ``n`` column is not decoration — with this many matches these means are
    descriptive, not evidence that the player runs more in wins.
    """
    if "team_result" not in linked.columns:
        raise KeyError("call link_sessions_to_fixtures() first — no team_result column")
    df = add_match_per90(linked, metrics)
    df = df[df["team_result"].notna() & (df["official_minutes"] >= minutes_floor)]
    if df.empty:
        return pd.DataFrame(columns=["team_result", "n", "mean_minutes"])

    columns = {"n": ("date", "size"), "mean_minutes": ("official_minutes", "mean")}
    for metric in metrics or PER90_MATCH_METRICS:
        per90 = f"{metric}_per90_official"
        if per90 in df.columns:
            columns[per90] = (per90, "mean")

    grouped = df.groupby("team_result").agg(**columns).round(1).reset_index()
    order = {"W": 0, "D": 1, "L": 2}
    return grouped.sort_values("team_result", key=lambda s: s.map(order)).reset_index(drop=True)


def output_by_venue(
    linked: pd.DataFrame, metrics: list[str] | None = None, minutes_floor: float = MINUTES_FLOOR
) -> pd.DataFrame:
    """Same as ``output_by_result``, split home vs. away instead. Same caveats."""
    if "venue" not in linked.columns:
        raise KeyError("call link_sessions_to_fixtures() first — no venue column")
    df = add_match_per90(linked, metrics)
    df = df[df["venue"].notna() & (df["official_minutes"] >= minutes_floor)]
    if df.empty:
        return pd.DataFrame(columns=["venue", "n", "mean_minutes"])

    columns = {"n": ("date", "size"), "mean_minutes": ("official_minutes", "mean")}
    for metric in metrics or PER90_MATCH_METRICS:
        per90 = f"{metric}_per90_official"
        if per90 in df.columns:
            columns[per90] = (per90, "mean")
    return df.groupby("venue").agg(**columns).round(1).reset_index()


def link_coverage(linked: pd.DataFrame) -> pd.DataFrame:
    """How many official sessions actually found a fixture, by resolution.

    Coverage is limited by how recently the fixture scraper was run, not by the
    join: unmatched official sessions are usually matches played after the last
    scrape (see the season-prediction doc's step 3).
    """
    if "fixture_match" not in linked.columns:
        raise KeyError("call link_sessions_to_fixtures() first — no fixture_match column")
    official = linked[_official_mask(linked)]
    if official.empty:
        return pd.DataFrame(columns=["fixture_match", "sessions"])
    counts = official["fixture_match"].value_counts(dropna=False).rename_axis("fixture_match")
    return counts.reset_index(name="sessions")


def season_config_for_label(label: str) -> SeasonConfig | None:
    """Find the ``SeasonConfig`` matching a GPS season label ("2025/26").

    GPS sessions carry a season *label*; fixtures live under a season *key*
    ("mansores_2025_26"), which embeds the same two years. A season with GPS
    data but no declared config (or vice versa) returns ``None`` rather than
    guessing — the dashboard then says the fixture link is unavailable instead
    of joining against the wrong competition.
    """
    suffix = label.replace("/", "_")
    for season in list_seasons():
        if season.key.endswith(suffix):
            return season
    return None
