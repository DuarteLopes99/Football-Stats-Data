"""Loaders for the body-composition assessments in ``data/body/``.

**These are anthropometry, not nutrition intake.** The files come from
periodic nutritionist reports (skinfolds, girths, scale readings and the
composition estimates computed from them). There is no record of what was
eaten, so nothing here measures diet directly — it measures what the body did
in response to whatever the diet and the training load were. Every
"nutritional" reading of this data is an inference, and the GPS side supplies
only the expenditure half of an energy balance whose intake half is unmeasured.

Provenance: all five CSVs are produced by ``tools/nutrition_pdf_to_csv.py``,
which parses the report PDFs. This module only reads them — the extraction and
the derived-metric formulas (Durnin & Womersley 1974 body density, Siri, the
Heath-Carter somatotype components, corrected girths and limb muscle areas)
live in that script, which is the authority on them.

- ``body_measurements.csv`` — values as reported, one row per (date, metric),
  with the source PDF for provenance. Where a printed value was a confirmed
  transcription error the corrected figure is stored alongside the original
  (``value_original`` / ``corrected`` / ``correction_note``) so the change is
  auditable rather than silent — see ``applied_corrections``.
- ``body_wide.csv`` — the same values pivoted, one row per assessment.
- ``body_derived.csv`` — metrics computed from the raw ones, tagged by group
  (``composicao`` / ``distribuicao`` / ``futebol``).
- ``body_changes.csv`` — deltas vs. the previous assessment and vs. baseline,
  plus a ``meaningful_change`` flag (see ``MEANINGFUL_CHANGE``).
- ``body_season_summary.csv`` — per-season stability and net change.

Every table also carries ``phase`` — where in the football calendar the
assessment falls (pré-época, 1ª volta, 2ª volta, final de época, fora de
época). It is the most useful grouping this data has: a pre-season figure and a
mid-season one describe different athletes, and comparing them directly is what
makes body-composition charts misleading.

**Season labels are rewritten on load.** The extraction script tags seasons
from August 1; the rest of this package uses July 1 (``gps/seasons.py``), so a
July assessment lands in a different season under each convention. The
exported label is preserved as ``season_reported`` and ``season`` is recomputed
with the GPS convention, so the dashboard's Season selector filters body and
GPS data consistently instead of splitting one season in two.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from football_stats.config import DATA_ROOT
from football_stats.gps.seasons import add_season_column

DEFAULT_BODY_DIR = DATA_ROOT / "body"

MEASUREMENTS_FILE = "body_measurements.csv"
WIDE_FILE = "body_wide.csv"
DERIVED_FILE = "body_derived.csv"
CHANGES_FILE = "body_changes.csv"
SEASON_SUMMARY_FILE = "body_season_summary.csv"

PHASE_ORDER = ["pré-época", "1ª volta", "2ª volta", "final de época", "fora de época"]
"""Football-calendar order of ``phase``, for sorting and for laying out charts
chronologically within a season rather than alphabetically."""

LOWER_IS_BETTER = {
    "Massa Gorda",
    "Massa Gorda (Atletas)",
    "% Massa Gorda (Atletas)",
    "% Massa Gorda (Durnin-Womersley)",
    "% Massa Gorda (Faulkner)",
    "% Massa Gorda (Yuhasz)",
    "% Massa Gorda (Petroski)",
    "Percentagem Massa Gorda (Atletas)",
    "Percentagem Massa Gorda (Sedentários)",
    "Índice de Massa Gorda (FMI)",
    "Soma de Pregas",
    "Soma de Pregas (recalculada)",
    "Soma ISAK (8 de 8 sítios)",
    "Soma ISAK (7 de 8 sítios)",
    "Soma 6 pregas (referência de atletas)",
    "Soma pregas tronco",
    "Soma pregas membros",
    # The individual sites. Each is a caliper reading of subcutaneous fat, so
    # falling is unambiguously the favourable direction -- unlike the girths
    # below, which mix muscle and fat and are left directionless.
    "Prega Cutânea Triciptal",
    "Prega Cutânea Bicipital",
    "Prega Cutânea Subescapular",
    "Prega Cutânea Supra-ilíaca",
    "Prega Cutânea Abdominal",
    "Prega cutânea Supraespinhal",
    "Prega Cutânea Coxa",
    "Prega Gêmeo",
    "Perímetro Cintura",
    "Perímetro Umbigo",
    "Rácio Cintura/Altura",
    "Rácio Umbigo/Altura",
    # Waist-to-hip, as printed and as recalculated: a central-adiposity marker
    # where lower is the standard favourable direction.
    "Relação Cintura/Anca",
    "Rácio Cintura/Anca (recalculado)",
    "Somatótipo - Endomorfia",
}
"""Metrics where a **fall** is the favourable direction — fat mass and its
estimators, skinfold sums, and the central-adiposity girths and ratios."""

HIGHER_IS_BETTER = {
    "Massa Isenta de Gordura",
    "Massa Isenta de Gordura (Atletas)",
    "Massa Isenta de Gordura / Peso",
    "Massa Magra",
    "Massa Muscular",
    "Índice de Massa Muscular",
    "Índice de Massa Isenta de Gordura (FFMI)",
    "FFMI normalizado (1.80m)",
    "Índice alométrico de massa magra",
    "Rácio Massa Muscular/Massa Gorda",
    "Rácio Músculo/Gordura (recalculado)",
    "Perímetro Coxa corrigido",
    "Perímetro Gémeo corrigido",
    "Perímetro Braço corrigido",
    "Área muscular estimada da coxa",
    "Área muscular estimada do gémeo",
    "Coxa corrigida / peso",
}
"""Metrics where a **rise** is the favourable direction — lean and muscle mass,
their height- and weight-scaled indices, and the corrected (fat-free) limb
girths and areas."""


def metric_direction(metric: str) -> str:
    """``"up"`` / ``"down"`` / ``"neutral"`` — which way is better for this metric.

    Drives the dashboard's colour coding. **Neutral is the default and is used
    deliberately**, not as a fallback for metrics nobody classified: body mass,
    height, BMI, girths that mix muscle and fat, the somatotype linearity
    component and every methodological cross-check are genuinely directionless
    for a footballer. Colouring them green or red would assert a goal the data
    does not contain — a heavier reading is not "better" than a lighter one.
    """
    if metric in LOWER_IS_BETTER:
        return "down"
    if metric in HIGHER_IS_BETTER:
        return "up"
    return "neutral"


METRIC_FAMILIES = {
    "Composição": "Masses and fat percentages — the headline picture of what the body is made of.",
    "Índices": "Size-normalised indices (BMI, FFMI, FMI) — mass expressed relative to height.",
    "Pregas": "Skinfolds and their sums — the caliper measurements the fat estimates are built from.",
    "Perímetros": "Girths, raw and skinfold-corrected — limb size, and limb size with fat removed.",
    "Rácios": "Ratios between two measurements — shape rather than size.",
    "Somatótipo": "Heath-Carter components — the body's overall shape classification.",
    "Áreas musculares": "Estimated muscle cross-sections and body surface area.",
    "Verificações": "Cross-checks between methods — data quality, not physiology.",
}
"""Metric groupings for the dashboard's selector, in the order they are offered.

The body files expose ~48 metrics. Offered as one flat alphabetical list they
are unnavigable — "Soma ISAK (7 de 8 sítios)" sits between two unrelated
neighbours, and the five different fat-percentage equations scatter. Grouping
them by *what kind of measurement they are* lets a whole family be picked or
dropped at once, and keeps the methodological cross-checks out of the way of
the metrics that describe the athlete."""

_FAMILY_OVERRIDES = {
    "Peso": "Composição",
    "Altura": "Composição",
    "Índice de massa corporal": "Índices",
    "FFMI normalizado (1.80m)": "Índices",
    "Índice alométrico de massa magra": "Índices",
    "Coxa corrigida / peso": "Rácios",
    "Massa Isenta de Gordura / Peso": "Rácios",
    "Relação Cintura/Anca": "Rácios",
    "Área de Superfície Corporal (Du Bois)": "Áreas musculares",
}
"""Metrics whose family the prefix rules below would get wrong.

``Índice de massa corporal`` and ``Índice de Massa Muscular`` share a prefix but
belong to different families; ``Massa Isenta de Gordura / Peso`` is a ratio
despite starting like a mass. These are named rather than encoded as ever-more
specific rules."""


def metric_family(metric: str) -> str:
    """Which ``METRIC_FAMILIES`` group a metric belongs to.

    Prefix-based with an explicit override table, so a metric added to the
    extraction script lands in a sensible group without this file changing.
    Anything unrecognised falls into "Composição" rather than a bin called
    "other" — an unfamiliar metric is more useful shown among the masses than
    hidden in a category the user has no reason to open.
    """
    if metric in _FAMILY_OVERRIDES:
        return _FAMILY_OVERRIDES[metric]
    if metric.startswith(("Coerência", "Diferença")):
        return "Verificações"
    if metric.startswith("Somatótipo"):
        return "Somatótipo"
    if metric.startswith("Área"):
        return "Áreas musculares"
    if metric.startswith(("Prega", "Soma")):
        return "Pregas"
    if metric.startswith("Perímetro"):
        return "Perímetros"
    if metric.startswith(("Rácio", "Relação")):
        return "Rácios"
    if metric.startswith("Índice"):
        return "Índices"
    return "Composição"


DEFAULT_FAMILIES = ["Composição", "Pregas", "Perímetros"]
"""Families shown before the user chooses anything.

The three that describe the athlete directly. Ratios, indices and somatotype
are derived views of the same measurements, and ``Verificações`` is about
whether the *numbers* agree rather than about the body — showing all of them by
default buries the eight metrics that actually answer "how am I doing"."""


def change_verdict(metric: str, delta: float | None) -> str:
    """``"better"`` / ``"worse"`` / ``"noise"`` / ``"neutral"`` for one change.

    A change smaller than the metric's ``MEANINGFUL_CHANGE`` threshold is
    ``"noise"`` regardless of direction — calling a 0.2 kg move an improvement
    would be reading the caliper's repeatability as a training effect.
    """
    if delta is None or pd.isna(delta):
        return "neutral"
    threshold = MEANINGFUL_CHANGE.get(metric)
    if threshold is not None and abs(delta) < threshold:
        return "noise"
    direction = metric_direction(metric)
    if direction == "neutral" or delta == 0:
        return "neutral"
    improving = delta > 0 if direction == "up" else delta < 0
    return "better" if improving else "worse"


SANITY_RANGES = {
    "Altura": (120, 220),
    "Peso": (35, 200),
    "Índice de massa corporal": (12, 50),
    "Percentagem Massa Gorda (Sedentários)": (3, 60),
    "Perímetro Cintura": (50, 160),
    "Perímetro Umbigo": (50, 160),
    "Perímetro Anca/Glúteo": (60, 170),
    "Perímetro Braço": (15, 60),
    "Perímetro Coxa": (30, 90),
    "Perímetro Gémeo": (20, 60),
    "Relação Cintura/Anca": (0.5, 1.5),
}
"""Plausible range per metric, mirrored from ``tools/nutrition_pdf_to_csv.py``.

The extraction script checks every value against these and applies a correction
only where the true figure has been confirmed against the source, recording the
printed value in ``value_original``. ``implausible_rows`` re-derives the check
here as a second line of defence: anything still outside its range is a value
that was *not* corrected, and should be treated as missing.
"""

MEANINGFUL_CHANGE = {
    "Peso": 0.8,
    "Massa Gorda": 0.5,
    "Massa Isenta de Gordura": 0.5,
    "Massa Muscular": 0.5,
    "Massa Magra": 0.5,
    "Percentagem Massa Gorda (Sedentários)": 1.0,
    "Soma de Pregas (recalculada)": 4.0,
    "Soma de Pregas": 4.0,
    "Perímetro Coxa": 1.0,
    "Perímetro Gémeo": 0.5,
    "Perímetro Braço": 0.5,
    "Perímetro Cintura": 1.0,
    "Perímetro Coxa corrigido": 1.0,
    "Perímetro Gémeo corrigido": 0.5,
    "Perímetro Braço corrigido": 0.5,
    "Área muscular estimada da coxa": 7.0,
    "Área muscular estimada do gémeo": 3.0,
    "Massa Isenta de Gordura / Peso": 1.0,
    # A single skinfold site is read to the nearest 0.5 mm at best, and
    # site-to-site technique variation is larger than that; 1.0 mm keeps a
    # re-measurement of the same fold from registering as a training effect.
    "Prega Cutânea Triciptal": 1.0,
    "Prega Cutânea Bicipital": 1.0,
    "Prega Cutânea Subescapular": 1.0,
    "Prega Cutânea Supra-ilíaca": 1.0,
    "Prega Cutânea Abdominal": 1.0,
    "Prega cutânea Supraespinhal": 1.0,
    "Prega Cutânea Coxa": 1.0,
    "Prega Gêmeo": 1.0,
    "Relação Cintura/Anca": 0.02,
    "Rácio Cintura/Anca (recalculado)": 0.02,
}
"""Smallest change worth reading as real, per metric (units as in the file).

Mirrored from ``tools/nutrition_pdf_to_csv.py``, which is where they are
applied to produce ``body_changes.csv``'s ``meaningful_change`` column. These
are *practitioner judgement about caliper and scale repeatability*, not figures
from a published typical-error study — a metric with no entry here gets a blank
flag rather than a guessed one.
"""


def _resolve(directory: Path | None, filename: str) -> Path:
    return (Path(directory) if directory else DEFAULT_BODY_DIR) / filename


def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(path, encoding="utf-8")


def _with_dates_and_season(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if "season" in df.columns:
        df = df.rename(columns={"season": "season_reported"})
    return add_season_column(df).sort_values("date").reset_index(drop=True)


def load_measurements(directory: Path | None = None) -> pd.DataFrame:
    """Raw report values, one row per (date, metric)."""
    path = _resolve(directory, MEASUREMENTS_FILE)
    df = _read(path, ["date", "metric", "unit", "value", "reference", "source_file"])
    return _with_dates_and_season(df)


def load_wide(directory: Path | None = None) -> pd.DataFrame:
    """One row per assessment, one column per raw metric."""
    path = _resolve(directory, WIDE_FILE)
    return _with_dates_and_season(_read(path, ["date", "season"]))


def load_derived(directory: Path | None = None) -> pd.DataFrame:
    """Computed metrics, long format, tagged by ``group``."""
    path = _resolve(directory, DERIVED_FILE)
    return _with_dates_and_season(_read(path, ["date", "season", "group", "metric", "unit", "value", "note"]))


def load_changes(directory: Path | None = None) -> pd.DataFrame:
    """Per-metric deltas vs. previous assessment and vs. baseline."""
    path = _resolve(directory, CHANGES_FILE)
    return _with_dates_and_season(_read(path, ["date", "season", "metric", "unit", "value"]))


def load_season_summary(directory: Path | None = None) -> pd.DataFrame:
    """Per-season net change and stability. Keeps the file's own season labels.

    Unlike the other loaders this one cannot be relabelled to the July-start
    convention: the rows are already aggregated under the August-start one, and
    re-tagging a summary row would misattribute the assessments behind it.
    """
    path = _resolve(directory, SEASON_SUMMARY_FILE)
    df = _read(path, ["season", "metric", "unit", "n_sessions"])
    if df.empty:
        return df
    return df.rename(columns={"season": "season_reported"})


def applied_corrections(measurements: pd.DataFrame) -> pd.DataFrame:
    """Values changed from what the report printed, with the reason for each.

    Corrections are applied upstream by the extraction script, which keeps the
    printed figure in ``value_original`` rather than overwriting it. Surfacing
    them is the point: a corrected dataset that cannot show what it corrected is
    just an unsourced one. Dependent figures are recomputed too, so a single
    transcription fix can produce more than one row here.
    """
    if measurements.empty or "corrected" not in measurements.columns:
        return pd.DataFrame(columns=["date", "metric", "unit", "value_original", "value", "correction_note"])
    rows = measurements[measurements["corrected"].astype(str).str.strip().str.lower() == "sim"]
    columns = ["date", "metric", "unit", "value_original", "value", "correction_note", "source_file"]
    return rows[[c for c in columns if c in rows.columns]].sort_values("date").reset_index(drop=True)


def implausible_rows(measurements: pd.DataFrame) -> pd.DataFrame:
    """Values still outside ``SANITY_RANGES`` after corrections were applied.

    An empty result is the expected state. A row here is a value the extraction
    script flagged but could not confirm a fix for, so it should be treated as
    missing — along with anything derived from it — until the report is
    rechecked.
    """
    if measurements.empty:
        return measurements
    flagged = []
    for metric, (low, high) in SANITY_RANGES.items():
        rows = measurements[measurements["metric"] == metric]
        values = pd.to_numeric(rows["value"], errors="coerce")
        outside = rows[(values < low) | (values > high)]
        for _, row in outside.iterrows():
            flagged.append(
                {
                    "date": row["date"],
                    "metric": metric,
                    "value": row["value"],
                    "unit": row.get("unit"),
                    "plausible_range": f"{low}–{high}",
                    "source_file": row.get("source_file"),
                }
            )
    return pd.DataFrame(flagged).sort_values("date").reset_index(drop=True) if flagged else pd.DataFrame(
        columns=["date", "metric", "value", "unit", "plausible_range", "source_file"]
    )
