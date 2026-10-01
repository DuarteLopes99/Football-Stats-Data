"""Opponent, venue and result parsed out of the ``session_type`` label.

Every game session in the GPS file already carries its own context in its
label::

    Jornada 11 - Vila Viçosa (FORA) 2-3
    Jogo Treino Paivense (CASA) 1-3
    Jogo Taça - Sangedo (Fora) 3-0
    Jornada 1 Ap.Campeão - Calvão (CASA) 1-0

This module reads it. That replaces the fixture join
(``match_link.link_sessions_to_fixtures``) as the dashboard's source of match
context, for three reasons:

- **Coverage.** The label covers all 38 game sessions. The fixture scrape
  matched 13 of 26 official matches, because the scrape stops at 2026-01-17.
- **Practice matches.** They are not in any fixture list and never could be, so
  the join could never say who a friendly was against. The label always can.
- **Nothing to go stale or mis-join.** No date tolerance, no re-running a
  scraper, no season config to declare.

The fixture functions in ``match_link`` are kept — they are correct, tested and
the only source of ``competition``/``matchweek`` as the league records them —
but the dashboard no longer needs them to answer "who was this against".

**The score is written home-first**, not player's-team-first. That is not an
assumption: it is checked against the six matches where the fixture scrape
independently recorded a result, three of which discriminate between the two
conventions (an away ``0-2`` is recorded as a win, which only holds if the
second number is the away side). ``tests/test_match_label.py`` pins those cases.
"""

from __future__ import annotations

import re

import pandas as pd

HOME_TOKENS = {"casa"}
AWAY_TOKENS = {"fora"}

_VENUE = re.compile(r"\(\s*(casa|fora)\s*\)", re.IGNORECASE)
_SCORE = re.compile(r"(\d{1,2}|\?)\s*[-–]\s*(\d{1,2}|\?)\s*$")
_PREFIX = re.compile(
    r"""^\s*(
        jornada\s*\d+(\s*ap\.?\s*campeão)?    # league round, incl. the playoff
        | jogo\s+treino                        # friendly
        | jogo\s+taça                          # cup
        | jogo                                 # bare fallback
    )\s*""",
    re.IGNORECASE | re.VERBOSE,
)

OUTPUT_COLUMNS = ["opponent", "venue", "goals_for", "goals_against", "scoreline", "team_result", "matchweek"]


def parse_match_label(label) -> dict:
    """Pull opponent, venue, score and result out of one ``session_type`` string.

    Returns a dict with ``None`` in any field the label doesn't support, rather
    than raising or guessing: a training label carries no opponent, and
    ``Jogo Treino Sub19 Arouca (CASA) ?-?`` is a real row whose score was never
    written down. A partially-parsed label is more useful than a dropped one —
    the opponent and venue are still there when the score is ``?-?``.
    """
    blank = dict.fromkeys(OUTPUT_COLUMNS)
    if not isinstance(label, str) or not label.strip():
        return blank

    venue_match = _VENUE.search(label)
    if venue_match is None:
        # No (CASA)/(FORA) marker means this isn't a match label at all.
        return blank

    token = venue_match.group(1).lower()
    venue = "home" if token in HOME_TOKENS else "away"

    # The opponent is whatever sits between the round/competition prefix and the
    # venue marker. Taking it by position rather than by pattern keeps names with
    # digits and spaces ("Sub23 Rui Dolores", "ADS B") intact.
    head = label[: venue_match.start()]
    opponent = _PREFIX.sub("", head).strip(" -–\t").strip()

    out = dict(blank)
    out["opponent"] = opponent or None
    out["venue"] = venue

    round_match = re.match(r"\s*jornada\s*(\d+\s*(?:ap\.?\s*campeão)?)", label, re.IGNORECASE)
    if round_match:
        out["matchweek"] = re.sub(r"\s+", " ", round_match.group(1)).strip()

    tail = label[venue_match.end():]
    score_match = _SCORE.search(tail)
    if score_match is None:
        return out

    left, right = score_match.group(1), score_match.group(2)
    if left == "?" or right == "?":
        # The score was genuinely not recorded. Venue and opponent still stand.
        out["scoreline"] = f"{left}-{right}"
        return out

    home_goals, away_goals = int(left), int(right)
    goals_for, goals_against = (home_goals, away_goals) if venue == "home" else (away_goals, home_goals)

    out["goals_for"] = goals_for
    out["goals_against"] = goals_against
    out["scoreline"] = f"{home_goals}-{away_goals}"
    out["team_result"] = "W" if goals_for > goals_against else ("L" if goals_for < goals_against else "D")
    return out


def add_match_label_columns(sessions: pd.DataFrame) -> pd.DataFrame:
    """Add the parsed columns to every session; non-matches get ``None``.

    Applied to the whole frame rather than to games only, so the column set is
    the same shape whatever the filters are — a table that gains and loses
    columns depending on the sidebar is worse than one with blanks in it.
    """
    df = sessions.copy()
    if "session_type" not in df.columns:
        for column in OUTPUT_COLUMNS:
            df[column] = None
        return df

    parsed = pd.DataFrame(
        [parse_match_label(label) for label in df["session_type"]],
        index=df.index,
        columns=OUTPUT_COLUMNS,
    )
    for column in OUTPUT_COLUMNS:
        df[column] = parsed[column]
    return df


def build_match_label(
    competition_type: str | None,
    opponent: str,
    venue: str,
    goals_home=None,
    goals_away=None,
    matchweek: str | None = None,
) -> str:
    """Compose a ``session_type`` label in the format this module parses back.

    Used by the dashboard's add-session form so a session typed in today is
    readable by the same code that reads the historical ones. Round-trips
    through ``parse_match_label`` — there is a test asserting exactly that,
    because a writer and a reader that drift apart are worse than no writer.
    """
    venue_token = "CASA" if venue == "home" else "FORA"
    # The separator matches how each competition is already written in the file:
    # league rounds and cup ties use " - ", friendlies run the name straight on
    # from "Jogo Treino". The parser accepts either, but writing labels in a
    # shape no historical row uses makes the log harder to read by eye.
    if competition_type == "Campeonato":
        prefix = f"Jornada {matchweek.strip()}" if matchweek and matchweek.strip() else "Jornada"
        separator = " - "
    elif competition_type == "Taça":
        prefix, separator = "Jogo Taça", " - "
    else:
        prefix, separator = "Jogo Treino", " "

    home = "?" if goals_home is None else int(goals_home)
    away = "?" if goals_away is None else int(goals_away)
    return f"{prefix}{separator}{opponent.strip()} ({venue_token}) {home}-{away}"


def output_by(
    sessions: pd.DataFrame,
    column: str,
    metrics: list[str] | None = None,
    minutes_floor: float | None = None,
) -> pd.DataFrame:
    """Mean per-90 output grouped by a parsed column (``team_result``/``venue``).

    The label-driven equivalent of ``match_link.output_by_result`` /
    ``output_by_venue``, differing only in where the grouping column comes from.
    ``n`` is not decoration: with this many matches per bucket these means
    describe the data rather than evidence how the player plays.
    """
    from football_stats.gps.match_link import MINUTES_FLOOR, PER90_MATCH_METRICS, add_match_per90

    if column not in sessions.columns:
        raise KeyError(f"call add_match_label_columns() first — no {column} column")

    floor = MINUTES_FLOOR if minutes_floor is None else minutes_floor
    wanted = metrics or PER90_MATCH_METRICS
    df = add_match_per90(sessions, wanted)
    df = df[df[column].notna() & (df["official_minutes"] >= floor)]
    if df.empty:
        return pd.DataFrame(columns=[column, "n", "mean_minutes"])

    aggregations = {"n": ("date", "size"), "mean_minutes": ("official_minutes", "mean")}
    aggregations.update(
        {f"{m}_per90_official": (f"{m}_per90_official", "mean") for m in wanted if f"{m}_per90_official" in df.columns}
    )
    grouped = df.groupby(column).agg(**aggregations).round(1).reset_index()

    if column == "team_result":
        order = {"W": 0, "D": 1, "L": 2}
        grouped = grouped.sort_values(column, key=lambda s: s.map(order).fillna(9))
    return grouped.reset_index(drop=True)
