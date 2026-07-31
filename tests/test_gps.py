import pandas as pd

from football_stats.gps.data_store import SCHEMA_COLUMNS, append_session, load_sessions
from football_stats.gps.analyzer import PerformanceAnalyzer

SESSIONS = pd.DataFrame(
    [
        {
            "date": "2025-09-01",
            "session_kind": "training",
            "week": 1,
            "month": 9,
            "session_type": "Treino A",
            "total_distance_m": 8000,
            "sprint_distance_m": 300,
            "high_speed_distance_m": 900,
            "top_speed_kmh": 28,
            "duration_min": 90,
            "accelerations": 30,
            "decelerations": 40,
            "calories": 700,
            "sprints_total": 10,
        },
        {
            "date": "2025-09-08",
            "session_kind": "game",
            "week": 2,
            "month": 9,
            "session_type": "Jogo A",
            "competition_type": "Campeonato",
            "was_starter": True,
            "total_distance_m": 10000,
            "sprint_distance_m": 500,
            "high_speed_distance_m": 1400,
            "top_speed_kmh": 32,
            "duration_min": 90,
            "accelerations": 40,
            "decelerations": 50,
            "calories": 900,
            "sprints_total": 15,
        },
    ]
)


def test_analyzer_monthly_summary_and_baseline():
    analyzer = PerformanceAnalyzer(SESSIONS.reindex(columns=SCHEMA_COLUMNS))
    training_summary = analyzer.monthly_summary("training")
    assert not training_summary.empty
    assert training_summary.iloc[0]["total_distance_m_mean"] == 8000

    comparison = analyzer.compare_to_baseline("training")
    row = comparison[comparison["Metric"] == "Total Distance (m)"].iloc[0]
    assert row["Current_Avg"] == 8000
    assert row["Baseline"] == 9000


def test_append_session_persists_and_reloads(tmp_path):
    path = tmp_path / "gps_sessions.csv"
    save_target = SESSIONS.reindex(columns=SCHEMA_COLUMNS)
    save_target.to_csv(path, index=False)

    updated = append_session(
        {"date": "2025-09-15", "session_kind": "training", "total_distance_m": 7200},
        path=path,
    )
    assert len(updated) == 3

    reloaded = load_sessions(path)
    assert len(reloaded) == 3
    assert reloaded.iloc[-1]["total_distance_m"] == 7200
