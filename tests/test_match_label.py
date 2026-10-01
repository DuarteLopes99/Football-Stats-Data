"""Tests for parsing opponent/venue/result out of the ``session_type`` label."""

import pandas as pd
import pytest

from football_stats.gps import match_label as ml


def test_parses_a_league_label():
    parsed = ml.parse_match_label("Jornada 11 - Vila Viçosa (FORA) 2-3")

    assert parsed["opponent"] == "Vila Viçosa"
    assert parsed["venue"] == "away"
    assert parsed["matchweek"] == "11"
    # Home-first: the away side scored 3, and the away side is us.
    assert parsed["goals_for"] == 3
    assert parsed["goals_against"] == 2
    assert parsed["team_result"] == "W"
    assert parsed["scoreline"] == "2-3"


def test_the_score_is_home_first_not_us_first():
    """The discriminating case, and the reason this is asserted rather than assumed.

    An away `0-2` is a win. Under a "player's team first" reading it would be a
    2-0 defeat — the opposite result from the same string. The fixture scrape
    independently recorded W for this match.
    """
    away = ml.parse_match_label("Jornada 9 - União Mata (FORA) 0-2")
    assert away["team_result"] == "W"
    assert (away["goals_for"], away["goals_against"]) == (2, 0)

    home = ml.parse_match_label("Jornada 10 - ADS B (CASA) 1-3")
    assert home["team_result"] == "L"
    assert (home["goals_for"], home["goals_against"]) == (1, 3)


@pytest.mark.parametrize(
    "label, opponent, venue",
    [
        # No space before the dash, none before the bracket.
        ("Jogo Taça -Canedo(CASA) 1-0", "Canedo", "home"),
        # Mixed-case venue token.
        ("Jogo Taça - Sangedo (Fora) 3-0", "Sangedo", "away"),
        # Friendly: no round prefix at all.
        ("Jogo Treino Paivense (CASA) 1-3", "Paivense", "home"),
        # Digits and spaces inside the opponent name must survive.
        ("Jornada 4 - Sub23 Rui Dolores (CASA) 5-1", "Sub23 Rui Dolores", "home"),
        ("Jornada 2 -Sub23 Mosteiro (FORA) 0-2", "Sub23 Mosteiro", "away"),
        ("Jornada 10 - ADS B (CASA) 1-3", "ADS B", "home"),
        # The playoff round added to config after the championship ended.
        ("Jornada 1 Ap.Campeão - Calvão (CASA) 1-0", "Calvão", "home"),
    ],
)
def test_handles_every_spacing_and_prefix_variant_in_the_real_file(label, opponent, venue):
    parsed = ml.parse_match_label(label)
    assert parsed["opponent"] == opponent
    assert parsed["venue"] == venue


def test_an_unrecorded_score_keeps_opponent_and_venue():
    """`?-?` is a real row. Dropping it would lose the opponent too."""
    parsed = ml.parse_match_label("Jogo Treino Sub19 Arouca (CASA) ?-?")

    assert parsed["opponent"] == "Sub19 Arouca"
    assert parsed["venue"] == "home"
    assert parsed["scoreline"] == "?-?"
    assert parsed["team_result"] is None
    assert parsed["goals_for"] is None


def test_a_training_label_yields_nothing_rather_than_a_guess():
    for label in ["Treino Terça-Feira", "", None, "Ginásio"]:
        assert ml.parse_match_label(label) == dict.fromkeys(ml.OUTPUT_COLUMNS)


def test_a_draw_is_a_draw_at_either_venue():
    assert ml.parse_match_label("Jornada 16 - Milheiroense (CASA) 2-2")["team_result"] == "D"
    assert ml.parse_match_label("Jornada 2 Ap.Campeão - Gafanha (FORA) 1-1")["team_result"] == "D"


def test_columns_are_added_to_every_row_not_just_games():
    """A table that gains and loses columns depending on the filter is worse
    than one with blanks in it."""
    sessions = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-01-17"), "session_kind": "game",
             "session_type": "Jornada 11 - Vila Viçosa (FORA) 2-3"},
            {"date": pd.Timestamp("2026-01-19"), "session_kind": "training",
             "session_type": "Treino Segunda"},
        ]
    )
    out = ml.add_match_label_columns(sessions)

    assert set(ml.OUTPUT_COLUMNS) <= set(out.columns)
    assert len(out) == 2
    assert out.loc[0, "team_result"] == "W"
    assert pd.isna(out.loc[1, "team_result"])


def test_missing_session_type_column_is_not_an_error():
    out = ml.add_match_label_columns(pd.DataFrame({"date": [pd.Timestamp("2026-01-17")]}))
    assert set(ml.OUTPUT_COLUMNS) <= set(out.columns)


@pytest.mark.parametrize(
    "competition_type, opponent, venue, home, away, matchweek",
    [
        ("Campeonato", "Vila Viçosa", "away", 2, 3, "11"),
        ("Campeonato", "Calvão", "home", 1, 0, "1 Ap.Campeão"),
        ("Taça", "Canedo", "home", 1, 0, None),
        ("Treino", "Paivense", "home", 1, 3, None),
        ("Treino", "Sub19 Arouca", "home", None, None, None),
    ],
)
def test_the_writer_round_trips_through_the_reader(competition_type, opponent, venue, home, away, matchweek):
    """A writer and a reader that drift apart are worse than no writer: the
    add-session form would produce labels the whole dashboard reads as blank."""
    label = ml.build_match_label(competition_type, opponent, venue, home, away, matchweek)
    parsed = ml.parse_match_label(label)

    assert parsed["opponent"] == opponent
    assert parsed["venue"] == venue
    if home is None:
        assert parsed["team_result"] is None
    else:
        expected = (home, away) if venue == "home" else (away, home)
        assert (parsed["goals_for"], parsed["goals_against"]) == expected


def test_output_by_refuses_unparsed_sessions():
    with pytest.raises(KeyError, match="add_match_label_columns"):
        ml.output_by(pd.DataFrame({"date": [pd.Timestamp("2026-01-17")]}), "team_result")


def test_output_by_excludes_cameos_and_reports_n():
    sessions = ml.add_match_label_columns(
        pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-01-17"), "session_kind": "game",
                 "session_type": "Jornada 11 - Vila Viçosa (FORA) 2-3",
                 "duration_min": 90.0, "minutes_game_zerozero": 90.0, "total_distance_m": 9000.0},
                # 9 official minutes extrapolates to 20 700 m/90 and must not
                # land in a bucket mean.
                {"date": pd.Timestamp("2026-01-11"), "session_kind": "game",
                 "session_type": "Jornada 10 - ADS B (CASA) 3-1",
                 "duration_min": 20.0, "minutes_game_zerozero": 9.0, "total_distance_m": 2070.0},
            ]
        )
    )
    result = ml.output_by(sessions, "team_result")

    assert list(result["team_result"]) == ["W"]
    assert result.loc[0, "n"] == 1
    assert result.loc[0, "total_distance_m_per90_official"] == 9000.0


def test_parses_every_game_in_the_real_file():
    """No game session may lose its opponent to a label format this misses.

    Guards the parser against a new spacing variant being typed into the log and
    silently blanking that row's match context everywhere in the dashboard.
    """
    from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, load_sessions

    if not DEFAULT_SESSIONS_PATH.exists():
        pytest.skip("no session log checked out")
    sessions = load_sessions(DEFAULT_SESSIONS_PATH)
    games = ml.add_match_label_columns(sessions[sessions["session_kind"] == "game"])
    if games.empty:
        pytest.skip("no game sessions logged")

    missing = games[games["opponent"].isna()]
    assert missing.empty, f"unparsed labels: {list(missing['session_type'])}"
    assert games["venue"].isin(["home", "away"]).all()

    # Only genuinely unrecorded scores may lack a result.
    unresolved = games[games["team_result"].isna()]
    assert unresolved["scoreline"].fillna("").str.contains(r"\?").all()


def test_parser_agrees_with_the_independent_fixture_scrape():
    """The label and the scraped league table are two separate records of the
    same matches. Where both exist they must agree, or one of them is wrong."""
    from football_stats.gps.analyzer import add_match_category_column
    from football_stats.gps.data_store import DEFAULT_SESSIONS_PATH, load_sessions
    from football_stats.gps.match_link import link_sessions_to_fixtures, season_config_for_label
    from football_stats.gps.seasons import add_season_column

    if not DEFAULT_SESSIONS_PATH.exists():
        pytest.skip("no session log checked out")
    sessions = add_season_column(add_match_category_column(load_sessions(DEFAULT_SESSIONS_PATH)))
    officials = sessions[sessions["match_category"] == "official_match"]

    frames = [
        link_sessions_to_fixtures(officials[officials["season"] == label], config)
        for label, config in ((s, season_config_for_label(s)) for s in officials["season"].dropna().unique())
        if config is not None
    ]
    if not frames:
        pytest.skip("no fixture data to cross-check against")
    linked = pd.concat(frames, ignore_index=True)
    matched = linked[linked["opponent"].notna()]
    if matched.empty:
        pytest.skip("no fixtures matched")

    parsed = ml.add_match_label_columns(sessions).set_index("date")
    for _, fixture in matched.iterrows():
        row = parsed.loc[fixture["date"]]
        assert row["venue"] == fixture["venue"], fixture["date"]
        assert row["team_result"] == fixture["team_result"], fixture["date"]


def test_written_labels_match_the_shape_already_in_the_file():
    """League and cup rows use " - "; friendlies run the name straight on."""
    assert ml.build_match_label("Campeonato", "Vila Viçosa", "away", 2, 3, "11") == (
        "Jornada 11 - Vila Viçosa (FORA) 2-3"
    )
    assert ml.build_match_label("Taça", "Canedo", "home", 1, 0) == "Jogo Taça - Canedo (CASA) 1-0"
    assert ml.build_match_label("Treino", "Paivense", "home", 1, 3) == "Jogo Treino Paivense (CASA) 1-3"
