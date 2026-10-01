"""Tests for joining GPS match sessions to league fixtures.

``load_primary_team_fixtures`` only needs ``raw_dir`` and ``primary_team`` off
its argument, so these use a stub season pointed at a temp directory rather
than mutating the real ``SeasonConfig`` (whose paths are derived from
``DATA_ROOT``).
"""

import pandas as pd
import pytest

from football_stats.gps import match_link as ml

RAW_FIXTURES = pd.DataFrame(
    [
        # Tracked team at home; "Result" is home-away -> 3-1 win.
        {"Date": "2025-10-12", "Location": "(C)", "Team1": "mansores", "Team2": "caldas",
         "Result": "3-1", "Competition": "Liga", "Matchweek": "J1", "Played?": True},
        # Tracked team away; "Result" is *still* home-away -> tracked team scored 2 and won.
        {"Date": "2025-10-19", "Location": "(F)", "Team1": "mansores", "Team2": "mosteiro",
         "Result": "0-2", "Competition": "Liga", "Matchweek": "J2", "Played?": True},
        {"Date": "2025-10-25", "Location": "(F)", "Team1": "mansores", "Team2": "espinho",
         "Result": "1-1", "Competition": "Liga", "Matchweek": "J3", "Played?": True},
        {"Date": "2025-11-01", "Location": "(C)", "Team1": "mansores", "Team2": "vale",
         "Result": "-", "Competition": "Liga", "Matchweek": "J4", "Played?": False},
    ]
)


class StubSeason:
    primary_team = "mansores"

    def __init__(self, raw_dir):
        self.raw_dir = raw_dir


@pytest.fixture
def season(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    RAW_FIXTURES.to_csv(raw_dir / "mansores_fixtures.csv", index=False)
    return StubSeason(raw_dir)


def _sessions():
    return pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-10-12"), "session_kind": "game", "competition_type": "Campeonato",
             "duration_min": 56.0, "minutes_game_zerozero": 45.0, "total_distance_m": 6260.0,
             "session_type": "J1"},
            # Logged a day after the fixture date -- an exact-date join would drop this.
            {"date": pd.Timestamp("2025-10-26"), "session_kind": "game", "competition_type": "Campeonato",
             "duration_min": 70.0, "minutes_game_zerozero": None, "total_distance_m": 7000.0,
             "session_type": "J3"},
            # Practice match, one day from a real fixture: must still never link.
            {"date": pd.Timestamp("2025-10-20"), "session_kind": "game", "competition_type": "Treino",
             "duration_min": 60.0, "minutes_game_zerozero": None, "total_distance_m": 5000.0,
             "session_type": "friendly"},
            {"date": pd.Timestamp("2025-10-14"), "session_kind": "training", "competition_type": None,
             "duration_min": 90.0, "minutes_game_zerozero": None, "total_distance_m": 7500.0,
             "session_type": "Treino"},
        ]
    )


def test_result_is_read_as_home_away_not_tracked_team_first(season):
    fixtures = ml.load_primary_team_fixtures(season)

    away_win = fixtures[fixtures["opponent"] == "mosteiro"].iloc[0]
    # The naive reading ("2 conceded, 0 scored") would turn this win into a loss --
    # the same trap behind the home/away bug fixed in season/fixtures.py.
    assert (away_win["goals_for"], away_win["goals_against"]) == (2, 0)
    assert away_win["team_result"] == "W"
    assert away_win["venue"] == "away"

    home_win = fixtures[fixtures["opponent"] == "caldas"].iloc[0]
    assert (home_win["goals_for"], home_win["goals_against"]) == (3, 1)
    assert home_win["venue"] == "home"

    assert fixtures[fixtures["opponent"] == "espinho"].iloc[0]["team_result"] == "D"


def test_unplayed_fixtures_are_excluded(season):
    assert "vale" not in set(ml.load_primary_team_fixtures(season)["opponent"])


def test_missing_raw_export_yields_an_empty_frame_not_an_error(tmp_path):
    assert ml.load_primary_team_fixtures(StubSeason(tmp_path)).empty


def test_link_tolerates_one_day_offset_but_records_it(season):
    linked = ml.link_sessions_to_fixtures(_sessions(), season).set_index("date")

    assert linked.loc[pd.Timestamp("2025-10-12"), "fixture_match"] == "exact"
    assert linked.loc[pd.Timestamp("2025-10-26"), "fixture_match"] == "+1d"
    assert linked.loc[pd.Timestamp("2025-10-26"), "opponent"] == "espinho"


def test_link_outside_tolerance_is_unmatched_not_snapped_to_the_nearest_fixture(season):
    late = pd.DataFrame(
        [{"date": pd.Timestamp("2025-10-29"), "session_kind": "game", "competition_type": "Campeonato",
          "duration_min": 60.0, "minutes_game_zerozero": None, "total_distance_m": 6000.0,
          "session_type": "?"}]
    )
    linked = ml.link_sessions_to_fixtures(late, season)
    assert linked.loc[0, "fixture_match"] == "unmatched"
    assert pd.isna(linked.loc[0, "opponent"])


def test_practice_and_training_sessions_never_link(season):
    linked = ml.link_sessions_to_fixtures(_sessions(), season).set_index("date")
    for date in [pd.Timestamp("2025-10-20"), pd.Timestamp("2025-10-14")]:
        assert linked.loc[date, "fixture_match"] == "not an official match"
        assert pd.isna(linked.loc[date, "opponent"])


def test_link_coverage_counts_only_official_sessions(season):
    coverage = ml.link_coverage(ml.link_sessions_to_fixtures(_sessions(), season))
    assert coverage["sessions"].sum() == 2  # the two official matches, not the friendly or the training


def test_official_minutes_prefers_the_match_sheet():
    by_date = ml.official_minutes(_sessions()).set_index("date")

    assert by_date.loc[pd.Timestamp("2025-10-12"), "official_minutes"] == 45.0
    assert by_date.loc[pd.Timestamp("2025-10-12"), "minutes_source"] == "match_sheet"
    # No match sheet -> fall back to the GPS unit's runtime, and say which was used.
    assert by_date.loc[pd.Timestamp("2025-10-26"), "official_minutes"] == 70.0
    assert by_date.loc[pd.Timestamp("2025-10-26"), "minutes_source"] == "gps_runtime"


def test_unused_substitute_gets_no_minutes_instead_of_zero():
    df = pd.DataFrame(
        [{"date": pd.Timestamp("2025-12-14"), "session_kind": "game", "competition_type": "Campeonato",
          "duration_min": 0.0, "minutes_game_zerozero": 0.0, "total_distance_m": 0.0, "session_type": "J8"}]
    )
    result = ml.add_match_per90(df)

    assert pd.isna(result.loc[0, "official_minutes"])
    assert result.loc[0, "minutes_source"] == "none"
    assert pd.isna(result.loc[0, "total_distance_m_per90_official"])  # not a divide-by-zero


def test_per90_uses_the_match_sheet_not_the_gps_runtime():
    result = ml.add_match_per90(_sessions().head(1))
    # 6260 m over the match sheet's 45 min, not over the unit's 56 min (a 24% difference).
    assert result.loc[0, "total_distance_m_per90_official"] == round(6260 / 45 * 90, 2)


def test_overhang_separates_normal_recording_from_lost_playing_time():
    df = pd.DataFrame(
        [
            # Unit stopped early: the GPS *totals* are short for this match.
            {"date": pd.Timestamp("2025-11-16"), "session_type": "J6", "duration_min": 54.0,
             "minutes_game_zerozero": 65.0},
            # Ordinary warm-up/warm-down overhang -- not an error, but a big per-90 correction.
            {"date": pd.Timestamp("2025-10-12"), "session_type": "J1", "duration_min": 56.0,
             "minutes_game_zerozero": 45.0},
            # Small overhang: nothing to say about it.
            {"date": pd.Timestamp("2025-09-21"), "session_type": "Taça", "duration_min": 72.0,
             "minutes_game_zerozero": 73.0},
        ]
    )
    result = ml.minutes_overhang(df).set_index("date")

    assert result.loc[pd.Timestamp("2025-11-16"), "minutes_overhang"] == -11.0
    assert result.loc[pd.Timestamp("2025-11-16"), "note"] == "unit under-recorded"
    assert result.loc[pd.Timestamp("2025-10-12"), "note"] == "wide recording window"
    assert result.loc[pd.Timestamp("2025-10-12"), "overhang_pct"] == round(11 / 45 * 100, 1)
    assert result.loc[pd.Timestamp("2025-09-21"), "note"] == ""


def test_overhang_ignores_matches_the_player_did_not_play():
    df = pd.DataFrame(
        [{"date": pd.Timestamp("2025-12-14"), "session_type": "J8", "duration_min": 0.0,
          "minutes_game_zerozero": 0.0}]
    )
    # 0 vs 0 is not a 0-minute overhang worth reporting -- there was no match to overhang.
    assert ml.minutes_overhang(df).empty


def test_output_by_result_reports_sample_size_and_drops_cameos(season):
    sessions = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-10-12"), "session_kind": "game", "competition_type": "Campeonato",
             "duration_min": 90.0, "minutes_game_zerozero": 90.0, "total_distance_m": 9000.0,
             "session_type": "J1"},
            # A 5-minute cameo extrapolates to 21600 m/90 and would swamp the mean.
            {"date": pd.Timestamp("2025-10-19"), "session_kind": "game", "competition_type": "Campeonato",
             "duration_min": 5.0, "minutes_game_zerozero": 5.0, "total_distance_m": 1200.0,
             "session_type": "J2"},
        ]
    )
    result = ml.output_by_result(ml.link_sessions_to_fixtures(sessions, season))

    assert result.loc[0, "team_result"] == "W"
    assert result.loc[0, "n"] == 1
    assert result.loc[0, "total_distance_m_per90_official"] == 9000.0


def test_split_helpers_refuse_unlinked_sessions():
    with pytest.raises(KeyError, match="link_sessions_to_fixtures"):
        ml.output_by_result(_sessions())
    with pytest.raises(KeyError, match="link_sessions_to_fixtures"):
        ml.output_by_venue(_sessions())
    with pytest.raises(KeyError, match="link_sessions_to_fixtures"):
        ml.link_coverage(_sessions())


def test_link_coverage_counts_only_official_sessions(season):
    """The fixture join is scoped to official matches, so a season made only of
    training must produce an empty coverage table rather than a row claiming
    that a training session failed to match a fixture.

    Regression: the dashboard drove this off the sidebar's season list, which
    now spans body-composition seasons too. Selecting 2023/24 -- a season with
    assessments and no GPS session at all -- produced "no season config declared
    for 2023/24, those sessions can't be linked", about sessions that did not
    exist.
    """
    sessions = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-10-14"), "session_kind": "training",
             "competition_type": None, "duration_min": 70.0},
            {"date": pd.Timestamp("2025-10-16"), "session_kind": "training",
             "competition_type": None, "duration_min": 65.0},
        ]
    )
    linked = ml.link_sessions_to_fixtures(sessions, season)
    assert (linked["fixture_match"] == "not an official match").all()
    assert ml.link_coverage(linked).empty


def test_short_appearances_are_flagged_not_dropped_in_per_session_listings():
    """The match-sheet denominator is the right one, and it makes cameo rates
    absurd: 2070 m in 9 minutes scales to 20 700 m per 90. Aggregates exclude
    those rows; a per-session log keeps them and labels them, because deleting a
    session that happened is worse than marking one that doesn't compare."""
    sessions = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-11-09"), "session_kind": "game", "competition_type": "Campeonato",
             "duration_min": 20.0, "minutes_game_zerozero": 9.0, "total_distance_m": 2070.0},
            {"date": pd.Timestamp("2025-09-21"), "session_kind": "game", "competition_type": "Campeonato",
             "duration_min": 72.0, "minutes_game_zerozero": 73.0, "total_distance_m": 7710.0},
        ]
    )
    flagged = ml.flag_short_appearances(sessions)

    assert list(flagged["short_appearance"]) == [True, False]
    # Both rows survive -- the flag is a label, not a filter.
    assert len(flagged) == 2


def test_short_appearance_flag_is_blank_without_a_minute_count():
    """An unused substitute has no rate at all, so it is not a *short* one."""
    sessions = pd.DataFrame(
        [{"date": pd.Timestamp("2025-12-14"), "session_kind": "game", "competition_type": "Campeonato",
          "duration_min": 0.0, "minutes_game_zerozero": 0.0, "total_distance_m": 0.0}]
    )
    assert ml.flag_short_appearances(sessions)["short_appearance"].tolist() == [False]


def test_aggregates_and_listings_share_one_floor():
    """Two different numbers for 'too short to compare' is a bug waiting to be
    reported as an inconsistency."""
    assert ml.MINUTES_FLOOR == 20.0
    import inspect

    for fn in (ml.output_by_result, ml.output_by_venue, ml.flag_short_appearances):
        assert inspect.signature(fn).parameters["minutes_floor"].default == ml.MINUTES_FLOOR
