import pandas as pd

from football_stats.season.league_table import compute_league_table
from football_stats.season.predictor import simulate_season

PLAYED = pd.DataFrame(
    [
        {"Home Team": "A", "Away Team": "B", "Home Goals": 2, "Away Goals": 0},
        {"Home Team": "C", "Away Team": "A", "Home Goals": 0, "Away Goals": 1},
        {"Home Team": "B", "Away Team": "C", "Home Goals": 1, "Away Goals": 1},
    ]
)
REMAINING = pd.DataFrame(
    [
        {"Home Team": "A", "Away Team": "C"},
        {"Home Team": "B", "Away Team": "A"},
        {"Home Team": "C", "Away Team": "B"},
    ]
)


def test_no_remaining_fixtures_predicted_equals_actual():
    prediction = simulate_season(PLAYED, pd.DataFrame(columns=REMAINING.columns), n_simulations=50, seed=0)
    pd.testing.assert_frame_equal(
        prediction.predicted_table.reset_index(drop=True),
        prediction.actual_table.reset_index(drop=True),
    )


def test_simulated_points_stay_within_plausible_bounds():
    """Regression test for a bug ported from the source notebook: the final merge divided
    already-averaged stats by n_simulations a second time, producing values like
    Draws_Predicted=965 for a team that plays a handful of games. Every per-team stat here
    must land within what's actually reachable across played + remaining fixtures.
    """
    n_simulations = 200
    prediction = simulate_season(PLAYED, REMAINING, n_simulations=n_simulations, seed=0)

    total_games = 2 + 2  # each team has 2 played + 2 remaining fixtures in this fixture set
    max_points = 3 * total_games

    for _, row in prediction.predicted_table.iterrows():
        assert 0 <= row["Points"] <= max_points
        assert 0 <= row["Wins"] <= total_games
        assert 0 <= row["Draws"] <= total_games
        assert 0 <= row["Losses"] <= total_games
        assert row["Played"] == total_games


def test_position_probabilities_sum_to_one_per_slot():
    prediction = simulate_season(PLAYED, REMAINING, n_simulations=100, seed=1)
    probs = prediction.position_probabilities
    assert set(probs["Team"]) == {"A", "B", "C"}
    assert (probs["Title %"] >= 0).all() and (probs["Title %"] <= 100).all()
    assert abs(probs["Title %"].sum() - 100) < 1e-6
