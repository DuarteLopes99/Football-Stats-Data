"""The config module is the single source of truth — and the bugs it replaced stay fixed."""

import math

import pandas as pd
import toml

from football_stats.config import REPO_ROOT
from football_stats.gps import charts
from football_stats.gps import config as cfg
from football_stats.gps.analyzer import PerformanceAnalyzer
from football_stats.gps.data_store import SCHEMA_COLUMNS
from football_stats.gps.sync import diff
from tests._gps_helpers import match, training


def test_streamlit_theme_mirrors_config():
    theme = toml.load(REPO_ROOT / ".streamlit" / "config.toml")["theme"]
    assert theme["base"] == "dark"
    assert theme["primaryColor"].upper() == cfg.THEME["accent"].upper()
    assert theme["backgroundColor"].upper() == cfg.THEME["background"].upper()
    assert theme["secondaryBackgroundColor"].upper() == cfg.THEME["surface_raised"].upper()
    assert theme["textColor"].upper() == cfg.THEME["text"].upper()


def test_usage_stats_are_off():
    assert toml.load(REPO_ROOT / ".streamlit" / "config.toml")["browser"]["gatherUsageStats"] is False


def test_every_report_metric_is_specified():
    for metric in cfg.REPORT_METRICS + cfg.FOCUS_METRICS:
        assert metric in cfg.METRICS


def test_heatmap_follows_the_brief_bands():
    assert charts.heat_color(3) == charts.heat_color(-3)          # coloured on |change|
    assert charts.heat_color(5).upper() == "#22B14C"              # green
    assert charts.heat_color(15).upper() == "#E9C21B"             # amber
    assert charts.heat_color(25).upper() == "#EE8A2A"             # orange
    assert charts.heat_color(60).upper() == "#D9433F"             # red
    assert charts.heat_color(float("nan")) == cfg.HEATMAP_EMPTY


def test_cell_text_picks_the_readable_ink():
    assert charts.readable_text("#22B14C") == cfg.THEME["text_on_light"]
    assert charts.readable_text("#0D366B") == cfg.THEME["text"]


def _analyzer(rows):
    return PerformanceAnalyzer(pd.DataFrame(rows).reindex(columns=SCHEMA_COLUMNS))


def test_quality_month_without_a_match_is_not_scored_as_zero():
    analyzer = _analyzer([training("2025-11-04"), match("2025-11-09"), training("2025-12-02")])
    december = analyzer.monthly_quality_metric().set_index("month_label").loc["Dec 2025"]
    assert math.isnan(december["match_quality"])
    assert december["combined_quality"] == december["training_quality"]


def test_baseline_per90_excludes_cameos():
    cameo = match("2025-10-12", 2070, duration_min=20, minutes_game_zerozero=9, sprint_distance_m=237)
    analyzer = _analyzer([match("2025-10-05", 9000), cameo])
    table = analyzer.compare_to_baseline("official_match", position="full_back").set_index("Metric")
    assert table.loc["Total Distance (m)", "Current"] == 9000      # the cameo's 20 700 m/90 is not averaged in


def test_starter_vs_sub_ignores_unused_substitutes():
    bench = match("2025-10-12", 0, was_starter=False, duration_min=0, minutes_game_zerozero=0)
    sub = match("2025-10-19", 3000, was_starter=False, duration_min=30)
    table = _analyzer([bench, sub]).starter_vs_substitute().set_index("was_starter")
    assert table.loc["Substitute", "duration_min_count"] == 1 and table.loc["Substitute", "total_distance_m_mean"] == 3000


def test_intensity_radar_scales_each_axis_on_its_own():
    fig = _analyzer([training("2025-10-01"), match("2025-10-05")]).plot_intensity_radar()
    for trace in fig.data:
        assert max(trace.r) <= 1.0 and min(trace.r) > 0.2   # no axis squashed by another metric's units


def test_sync_diff_reports_added_and_removed_rows():
    old = pd.DataFrame({"date": pd.to_datetime(["2025-09-04"]), "session_kind": ["training"], "session_type": ["Treino Quarta-Feira"]})
    new = pd.DataFrame({"date": pd.to_datetime(["2025-09-04", "2026-09-05"]), "session_kind": ["training", "game"],
                        "session_type": ["Treino Quinta-Feira", "Jogo Treino Fiães B (CASA) 6-1"]})
    report = diff(old, new)
    assert report.rows_before == 1 and report.rows_after == 2 and len(report.added) == 2 and len(report.removed) == 1
