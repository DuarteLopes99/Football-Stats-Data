import pandas as pd

from football_stats.gps.analyzer import PerformanceAnalyzer, add_match_category_column
from football_stats.gps.data_store import SCHEMA_COLUMNS
from football_stats.gps.seasons import season_label


def test_season_label_boundary():
    assert season_label("2025-09-01") == "2025/26"
    assert season_label("2026-05-12") == "2025/26"  # same season, next calendar year
    assert season_label("2026-06-30") == "2025/26"  # last day of the season
    assert season_label("2026-07-01") == "2026/27"  # first day of the next season


def test_match_category_derivation():
    df = pd.DataFrame(
        {
            "session_kind": ["training", "game", "game", "game", "game"],
            "competition_type": [None, "Campeonato", "Taça", "Treino", None],
        }
    )
    result = add_match_category_column(df)["match_category"].tolist()
    assert result == ["training", "official_match", "official_match", "practice_match", "practice_match"]


def _session(date, session_kind, month, week, **extra):
    row = {
        "date": date,
        "session_kind": session_kind,
        "month": month,
        "week": week,
        "duration_min": 90,
        "total_distance_m": 8000,
    }
    row.update(extra)
    return row


TWO_SEASON_SESSIONS = pd.DataFrame(
    [
        _session("2024-09-05", "training", 9, 1, total_distance_m=7000),
        _session("2025-01-10", "training", 1, 15, total_distance_m=7500),
        _session("2025-09-05", "training", 9, 1, total_distance_m=9000),  # different season, same month number
        _session("2025-10-05", "training", 10, 2, total_distance_m=9500),
    ]
).reindex(columns=SCHEMA_COLUMNS)


def test_monthly_summary_is_chronological_across_a_year_boundary():
    analyzer = PerformanceAnalyzer(TWO_SEASON_SESSIONS)
    summary = analyzer.monthly_summary("training")

    # Sep 2024 -> Jan 2025 -> Sep 2025 -> Oct 2025, NOT sorted as if month were a bare 1-12 number
    assert summary["month_label"].tolist() == ["Sep 2024", "Jan 2025", "Sep 2025", "Oct 2025"]


def test_season_filter_does_not_leak_across_seasons():
    analyzer = PerformanceAnalyzer(TWO_SEASON_SESSIONS)
    assert set(analyzer.sessions["season"]) == {"2024/25", "2025/26"}

    season_2025_26 = analyzer.sessions[analyzer.sessions["season"] == "2025/26"]
    scoped = PerformanceAnalyzer(season_2025_26)
    summary = scoped.monthly_summary("training")

    # Only the two 2025/26 sessions should show up, not the 2024/25 September session too
    assert summary["month_label"].tolist() == ["Sep 2025", "Oct 2025"]
    assert summary["total_distance_m_mean"].tolist() == [9000, 9500]


def test_season_summary_has_one_row_per_season():
    analyzer = PerformanceAnalyzer(TWO_SEASON_SESSIONS)
    summary = analyzer.season_summary()
    assert sorted(summary["season"]) == ["2024/25", "2025/26"]
    assert summary.set_index("season").loc["2024/25", "total_sessions"] == 2
    assert summary.set_index("season").loc["2025/26", "total_sessions"] == 2
