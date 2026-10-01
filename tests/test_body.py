"""Tests for the body-composition loaders and their join to GPS sessions.

All body values below are synthetic: real assessments are personal health data
and stay in the gitignored data/body/.
"""

import pandas as pd
import pytest

from football_stats.body import data_store as bd
from football_stats.body import gps_link as bl

MEASUREMENTS = pd.DataFrame(
    [
        {"date": "2025-07-18", "metric": "Peso", "unit": "kg", "value": 70.0,
         "reference": "", "source_file": "a.pdf"},
        {"date": "2025-08-21", "metric": "Peso", "unit": "kg", "value": 70.7,
         "reference": "", "source_file": "b.pdf"},
        # Transcription typo: 820 cm rather than 82 cm.
        {"date": "2025-08-21", "metric": "Perímetro Cintura", "unit": "cm", "value": 820.0,
         "reference": "78 - 94", "source_file": "b.pdf"},
        {"date": "2025-07-18", "metric": "Perímetro Cintura", "unit": "cm", "value": 80.0,
         "reference": "78 - 94", "source_file": "a.pdf"},
    ]
)

WIDE = pd.DataFrame(
    [
        {"date": "2025-07-18", "season": "2024/25", "Peso (kg)": 70.0, "Massa Magra (Kg)": 60.0},
        {"date": "2025-08-21", "season": "2025/26", "Peso (kg)": 70.7, "Massa Magra (Kg)": 59.9},
        {"date": "2025-10-17", "season": "2025/26", "Peso (kg)": 71.0, "Massa Magra (Kg)": 61.1},
    ]
)

DERIVED = pd.DataFrame(
    [
        {"date": "2025-07-18", "season": "2024/25", "group": "composicao", "metric": "Massa Gorda",
         "unit": "kg", "value": 10.00, "note": ""},
        {"date": "2025-08-21", "season": "2025/26", "group": "composicao", "metric": "Massa Gorda",
         "unit": "kg", "value": 11.16, "note": ""},
        {"date": "2025-10-17", "season": "2025/26", "group": "composicao", "metric": "Massa Gorda",
         "unit": "kg", "value": 10.76, "note": ""},
    ]
)


@pytest.fixture
def body_dir(tmp_path):
    MEASUREMENTS.to_csv(tmp_path / bd.MEASUREMENTS_FILE, index=False, encoding="utf-8")
    WIDE.to_csv(tmp_path / bd.WIDE_FILE, index=False, encoding="utf-8")
    DERIVED.to_csv(tmp_path / bd.DERIVED_FILE, index=False, encoding="utf-8")
    return tmp_path


def test_season_is_relabelled_to_the_july_start_convention(body_dir):
    wide = bd.load_wide(body_dir)
    july = wide[wide["date"] == pd.Timestamp("2025-07-18")].iloc[0]

    # The extraction script tags seasons from August, so it called this 2024/25;
    # the rest of the package starts seasons on July 1.
    assert july["season_reported"] == "2024/25"
    assert july["season"] == "2025/26"


def test_missing_files_load_as_empty_frames(tmp_path):
    assert bd.load_wide(tmp_path).empty
    assert bd.load_derived(tmp_path).empty
    assert bd.load_changes(tmp_path).empty


def test_implausible_values_are_reported_not_silently_corrected(body_dir):
    measurements = bd.load_measurements(body_dir)
    flagged = bd.implausible_rows(measurements)

    assert len(flagged) == 1
    assert flagged.loc[0, "metric"] == "Perímetro Cintura"
    assert flagged.loc[0, "value"] == 820.0
    # The stored value still matches the printed report.
    stored = measurements[
        (measurements["metric"] == "Perímetro Cintura")
        & (measurements["date"] == pd.Timestamp("2025-08-21"))
    ]
    assert stored.iloc[0]["value"] == 820.0


def test_wide_column_units_are_stripped_so_metric_names_match_the_long_files(body_dir):
    assert bl.strip_unit_suffix("Peso (kg)") == "Peso"
    assert bl.strip_unit_suffix("Rácio Massa Muscular/Massa Gorda") == "Rácio Massa Muscular/Massa Gorda"

    table = bl.assessment_table(bd.load_wide(body_dir), bd.load_derived(body_dir))
    assert "Peso" in table.columns          # from the wide file, unit stripped
    assert "Massa Gorda" in table.columns   # from the derived file


def _sessions():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-07-20", "2025-08-25", "2025-09-10", "2025-10-20"]),
            "total_distance_m": [7000.0, 8000.0, 9000.0, 6000.0],
            "calories": [700.0, 800.0, 900.0, 600.0],
            "duration_min": [90.0, 90.0, 90.0, 90.0],
        }
    )


def test_body_state_uses_the_previous_assessment_never_a_later_one(body_dir):
    attached = bl.attach_body_state(_sessions(), bd.load_wide(body_dir), bd.load_derived(body_dir))
    by_date = attached.set_index("date")

    # 2025-08-25 sits between the Aug 21 and Oct 17 assessments: it must take Aug 21,
    # not the nearer-in-spirit future one.
    assert by_date.loc[pd.Timestamp("2025-08-25"), "assessment_date"] == pd.Timestamp("2025-08-21")
    assert by_date.loc[pd.Timestamp("2025-08-25"), "Peso"] == 70.7
    assert by_date.loc[pd.Timestamp("2025-08-25"), "days_since_assessment"] == 4

    assert by_date.loc[pd.Timestamp("2025-07-20"), "assessment_date"] == pd.Timestamp("2025-07-18")


def test_stale_assessments_are_blanked_rather_than_carried_forward(body_dir):
    late = pd.DataFrame({"date": [pd.Timestamp("2026-06-01")], "total_distance_m": [8000.0]})
    attached = bl.attach_body_state(
        late, bd.load_wide(body_dir), bd.load_derived(body_dir), max_staleness_days=120
    )

    assert pd.isna(attached.loc[0, "Peso"])
    assert pd.isna(attached.loc[0, "assessment_date"])

    carried = bl.attach_body_state(
        late, bd.load_wide(body_dir), bd.load_derived(body_dir), max_staleness_days=None
    )
    assert carried.loc[0, "Peso"] == 71.0


def test_assessment_windows_pair_training_done_with_body_change(body_dir):
    windows = bl.assessment_windows(_sessions(), bd.load_wide(body_dir), bd.load_derived(body_dir))

    assert len(windows) == 2  # three assessments -> two gaps
    first = windows.iloc[0]
    assert first["window_start"] == pd.Timestamp("2025-07-18")
    assert first["window_end"] == pd.Timestamp("2025-08-21")
    # A session on the closing assessment's own date belongs to the window; one on
    # the opening date does not (it was already reflected in that measurement).
    assert first["sessions"] == 1
    assert first["total_distance_m"] == 7000.0
    assert first["Peso (Δ)"] == pytest.approx(0.7)
    assert first["Massa Gorda (Δ)"] == pytest.approx(1.16)

    second = windows.iloc[1]
    assert second["sessions"] == 2
    assert second["football_kcal_per_day"] == round((800 + 900) / 57)


def test_windows_need_two_assessments(body_dir):
    single = bd.load_wide(body_dir).head(1)
    assert bl.assessment_windows(_sessions(), single, bd.load_derived(body_dir).head(1)).empty


def test_metric_families_group_the_report_into_navigable_sets():
    """62 metrics in one alphabetical list is not a choice anyone can make."""
    assert bd.metric_family("Prega Cutânea Abdominal") == "Pregas"
    assert bd.metric_family("Soma ISAK (8 de 8 sítios)") == "Pregas"
    assert bd.metric_family("Perímetro Coxa corrigido") == "Perímetros"
    assert bd.metric_family("Somatótipo - Endomorfia") == "Somatótipo"
    assert bd.metric_family("Diferença entre métodos (%MG)") == "Verificações"
    # The two that a prefix rule alone gets wrong: same first word, different family.
    assert bd.metric_family("Índice de massa corporal") == "Índices"
    assert bd.metric_family("Massa Isenta de Gordura / Peso") == "Rácios"
    # An unrecognised metric lands among the masses, not in a bin nobody opens.
    assert bd.metric_family("Something New") == "Composição"


def test_every_family_offered_is_reachable_from_the_real_data():
    """A group in the selector that can never contain anything is a dead option."""
    wide, derived = bd.load_wide(), bd.load_derived()
    if wide.empty:
        pytest.skip("no body data checked out")
    families = {bd.metric_family(m) for m in bl.available_metrics(wide, derived)}
    assert families <= set(bd.METRIC_FAMILIES)
    assert set(bd.DEFAULT_FAMILIES) <= families


def test_available_metrics_finds_the_individual_skinfold_sites():
    """The hand-written list this replaced knew about `Soma de Pregas` but none
    of the eight folds it is the sum of."""
    wide, derived = bd.load_wide(), bd.load_derived()
    if wide.empty:
        pytest.skip("no body data checked out")
    metrics = bl.available_metrics(wide, derived)

    assert "Prega Cutânea Abdominal" in metrics
    assert "Perímetro Anca/Glúteo" in metrics
    # Unit suffixes are stripped, so a metric is named the same wherever it lives.
    assert "Peso" in metrics and "Peso (kg)" not in metrics
    # Index columns are not metrics.
    assert not {"date", "season", "phase"} & set(metrics)


def test_individual_skinfolds_are_directional_but_girths_are_not():
    """A caliper reading is unambiguously fat; a girth mixes muscle and fat."""
    assert bd.metric_direction("Prega Cutânea Abdominal") == "down"
    assert bd.metric_direction("Prega Gêmeo") == "down"
    assert bd.metric_direction("Perímetro Braço") == "neutral"
    # And a fold has to move more than the caliper's repeatability to count.
    assert bd.change_verdict("Prega Cutânea Abdominal", -0.4) == "noise"
    assert bd.change_verdict("Prega Cutânea Abdominal", -1.5) == "better"
