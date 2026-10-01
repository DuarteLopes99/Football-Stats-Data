#!/usr/bin/env python3
"""
Extract the anthropometric table ("DADOS ATROPOMÉTRICOS") from every
nutrition report PDF in a folder, merge them, and compute derived,
sports-oriented metrics plus session-to-session changes.

Outputs (prefix configurable with -o):
    body_measurements.csv    raw values, one row per (session, metric)
    body_wide.csv            one row per session, one column per metric
    body_derived.csv         derived + football/performance metrics
    body_changes.csv         delta vs previous session and vs baseline,
                             rate per 30 days, meaningful-change flag
    body_season_summary.csv  per season and phase: stability, range, net change
    body_analysis.xlsx       all of the above as one workbook, one sheet each

Usage:
    python nutri_to_csv.py                            # uses defaults below
    python nutri_to_csv.py ./relatorios -o out/body
    python nutri_to_csv.py a.pdf b.pdf ./mais_pdfs

Requires: pdfplumber, openpyxl  (pip install pdfplumber openpyxl)
"""

import argparse
import csv
import glob
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime

import pdfplumber

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:  # the CSVs still work without it
    Workbook = None

# ---- defaults: edit these and you can just run the script with no arguments
INPUT_DIR = "/Users/duartelopes/Desktop/Nutrição/"
OUTPUT_PREFIX = "/Users/duartelopes/Desktop/Nutrição/body"
# Season runs August -> June, so the label year flips on 1 August. A July
# measurement falls after the last match, and is tagged as off-season of the
# season that has just finished.
SEASON_START_MONTH = 8
# Month -> phase of the season. Edit if your club's calendar differs.
SEASON_PHASES = {
    7: "fora de época",   # julho
    8: "pré-época",       # agosto
    9: "1ª volta", 10: "1ª volta", 11: "1ª volta", 12: "1ª volta",
    1: "2ª volta", 2: "2ª volta", 3: "2ª volta", 4: "2ª volta",
    5: "2ª volta", 6: "final de época",
}
# ---------------------------------------------------------------------------

# Known typos in the printed reports, read from a local JSON file so that the
# dated personal values never reach the repo (data/body/ is gitignored):
#   [{"date": "YYYY-MM-DD", "metric": "Perímetro Cintura", "value": 0.0, "why": "..."}]
# Corrections are applied after parsing, the original is kept in the output,
# and anything computed from the value is recomputed. Add an entry there rather
# than editing the CSVs by hand, so a re-run keeps the fix.
CORRECTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "body", "corrections.json")
CORRECTIONS = {}  # (date, metric) -> (correct value, why); filled by load_corrections()


def load_corrections(path=CORRECTIONS_FILE):
    """Read the local corrections file; a missing file means no corrections."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {(e["date"], e["metric"]): (float(e["value"]), e.get("why", "")) for e in json.load(f)}

# Printed fields that are computed from other printed fields. When a source is
# corrected, the dependent field is recomputed instead of left inconsistent.
DEPENDENT_FIELDS = {
    "Relação Cintura/Anca": ("Perímetro Cintura", "Perímetro Anca/Glúteo"),
}

DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
VALUE_RE = re.compile(r"^-$|^\d+[.,]?\d*$")
SECTION_HEADERS = ("AVALIAÇÃO ANTROPOMÉTRICA", "PREGAS E PERÍMETROS")
STOP_MARKERS = ("Página", "Impresso em", "Processado por")

SANITY = {
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

# The report may carry two body-fat columns: "(Sedentários)" and "(Atletas)".
# They are the software/device's own two calibrations of the same measurement,
# not two skinfold equations (see FAT_METHOD_NOTES below). When the athlete
# column is blank, the script reconstructs it — in this order:
#   1. mass balance from the printed Massa Magra: (peso - massa magra)/peso
#   2. the sedentary value minus the gap observed in this person's own sessions
#   3. a skinfold estimate (Faulkner), clearly labelled as a different method
FAT_SED = "Percentagem Massa Gorda (Sedentários)"
FAT_ATH = "Percentagem Massa Gorda (Atletas)"

# Durnin & Womersley (1974) body-density coefficients, by sex and age band,
# applied to log10 of the sum of 4 skinfolds (triceps, biceps, subscapular,
# suprailiac), then converted to %fat with Siri.
DW_COEFFS = {
    "M": [(19, 1.1620, 0.0630), (29, 1.1631, 0.0632), (39, 1.1422, 0.0544),
          (49, 1.1620, 0.0700), (200, 1.1715, 0.0779)],
    "F": [(19, 1.1549, 0.0678), (29, 1.1599, 0.0717), (39, 1.1423, 0.0632),
          (49, 1.1333, 0.0612), (200, 1.1339, 0.0645)],
}

# Smallest change worth reacting to, per metric. Anything below this is inside
# the measurement noise of skinfold calipers / scales and should NOT be read as
# a real trend. Tune these if you know your nutritionist's own repeatability.
MEANINGFUL_CHANGE = {
    "Peso": 0.8,                                  # kg
    "Massa Gorda": 0.5,                           # kg
    "Massa Isenta de Gordura": 0.5,               # kg
    "Massa Muscular": 0.5,                        # kg
    "Massa Magra": 0.5,                           # kg
    "Percentagem Massa Gorda (Sedentários)": 1.0,  # pp
    "Soma de Pregas (recalculada)": 4.0,          # mm
    "Soma de Pregas": 4.0,                        # mm
    "Perímetro Coxa": 1.0,                        # cm
    "Perímetro Gémeo": 0.5,
    "Perímetro Braço": 0.5,
    "Perímetro Cintura": 1.0,
    "Perímetro Coxa corrigido": 1.0,              # cm
    "Perímetro Gémeo corrigido": 0.5,
    "Perímetro Braço corrigido": 0.5,
    "Área muscular estimada da coxa": 7.0,        # cm2
    "Área muscular estimada do gémeo": 3.0,       # cm2
    "Massa Isenta de Gordura / Peso": 1.0,        # pp
}


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def collect_pdfs(paths):
    """Expand folders, globs and plain filenames into a sorted list of PDFs."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            found += glob.glob(os.path.join(path, "**", "*.pdf"), recursive=True)
            found += glob.glob(os.path.join(path, "**", "*.PDF"), recursive=True)
        elif any(c in path for c in "*?["):
            found += glob.glob(path, recursive=True)
        else:
            found.append(path)
    return sorted({os.path.abspath(p) for p in found})


def read_pdf(path):
    """Return (table_page_text, age, sex) for one report."""
    table_text, age, sex = None, None, None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            upper = text.upper()
            if table_text is None and "PREGAS" in upper and (
                "ATROPOM" in upper or "ANTROPOM" in upper
            ):
                table_text = text
            if age is None:
                m = re.search(r"(\d{1,3})\s*Anos", text)
                if m:
                    age = int(m.group(1))
            if sex is None:
                if "Masculino" in text:
                    sex = "M"
                elif "Feminino" in text:
                    sex = "F"
    return table_text, age, sex


def split_label_unit(label):
    """'Peso (kg)' -> ('Peso', 'kg')"""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", label)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return label.strip(), ""


def parse_page(text):
    """Return (dates, [(label, unit, [values...], reference), ...])."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    dates, start = [], 0
    for i, line in enumerate(lines):
        found = [t for t in line.split() if DATE_RE.match(t)]
        if len(found) >= 2:
            dates, start = found, i + 1
            break
    if not dates:
        return [], []

    rows = []
    for line in lines[start:]:
        if any(line.startswith(m) for m in STOP_MARKERS):
            break
        if line.upper() in SECTION_HEADERS:
            continue

        tokens = line.split()
        first_val = next((i for i, t in enumerate(tokens) if VALUE_RE.match(t)), None)

        # wrapped label, e.g. "(Sedentários) (%)" -> glue onto previous row
        if first_val is None or first_val == 0:
            if rows and first_val is None:
                label, unit, values, ref = rows[-1]
                merged = f"{label} ({unit})" if unit else label
                rows[-1] = (*split_label_unit(f"{merged} {line}".strip()), values, ref)
            continue

        label = " ".join(tokens[:first_val])
        rest = tokens[first_val:]
        values = rest[: len(dates)]
        reference = " ".join(rest[len(dates):]).strip()
        name, unit = split_label_unit(label)
        rows.append((name, unit, values, reference))

    return dates, rows


def to_records(path):
    try:
        table_text, age, sex = read_pdf(path)
    except Exception as exc:
        print(f"  ! could not open {os.path.basename(path)}: {exc}", file=sys.stderr)
        return [], None, None

    if table_text is None:
        print(f"  ! no anthropometric table in {os.path.basename(path)}", file=sys.stderr)
        return [], age, sex

    dates, rows = parse_page(table_text)
    records = []
    for name, unit, values, reference in rows:
        for date, raw in zip(dates, values):
            if raw == "-":
                continue
            records.append({
                "date": datetime.strptime(date, "%d-%m-%Y").date().isoformat(),
                "metric": name,
                "unit": unit,
                "value": float(raw.replace(",", ".")),
                "reference": reference,
                "source_file": os.path.basename(path),
            })
    return records, age, sex


def dedupe(records):
    """Same (date, metric) appears in several reports — keep the newest one."""
    best = {}
    for r in records:
        key = (r["date"], r["metric"])
        current = best.get(key)
        if current is None or r["_report_date"] > current["_report_date"]:
            best[key] = r
    out = []
    for r in best.values():
        r.pop("_report_date", None)
        out.append(r)
    return out


# --------------------------------------------------------------------------
# derived metrics
# --------------------------------------------------------------------------
def apply_corrections(records):
    """Apply CORRECTIONS, then recompute anything that depended on them."""
    fixed = []
    for r in records:
        key = (r["date"], r["metric"])
        if key in CORRECTIONS:
            new_value, why = CORRECTIONS[key]
            r = dict(r, value=new_value, value_original=r["value"],
                     corrected="sim", correction_note=why)
        else:
            r = dict(r, value_original="", corrected="", correction_note="")
        fixed.append(r)

    corrected_dates = {d for (d, _) in CORRECTIONS}
    index = {(r["date"], r["metric"]): r for r in fixed}
    for date in corrected_dates:
        for field, (num_name, den_name) in DEPENDENT_FIELDS.items():
            target = index.get((date, field))
            num = index.get((date, num_name))
            den = index.get((date, den_name))
            if not (target and num and den) or not den["value"]:
                continue
            recomputed = round(num["value"] / den["value"], 2)
            if abs(recomputed - target["value"]) < 0.005:
                continue
            target["value_original"] = target["value"]
            target["value"] = recomputed
            target["corrected"] = "sim"
            target["correction_note"] = (
                f"recalculado de {num_name}/{den_name} após correção")
    return fixed


def by_session(records):
    sessions, units = {}, {}
    for r in records:
        sessions.setdefault(r["date"], {})[r["metric"]] = r["value"]
        units.setdefault(r["metric"], r["unit"])
    return sessions, units


def season_of(date_iso, start_month=SEASON_START_MONTH):
    d = datetime.fromisoformat(date_iso)
    start_year = d.year if d.month >= start_month else d.year - 1
    return f"{start_year}/{str(start_year + 1)[-2:]}"


def phase_of(date_iso):
    """Where in the season a measurement sits — pré-época, 1ª/2ª volta, etc."""
    return SEASON_PHASES.get(datetime.fromisoformat(date_iso).month, "")


def durnin_womersley(sex, age, triceps, biceps, subscap, suprailiac):
    folds = [triceps, biceps, subscap, suprailiac]
    if any(f is None or f <= 0 for f in folds) or sex not in DW_COEFFS or age is None:
        return None
    total = sum(folds)
    for max_age, c, m in DW_COEFFS[sex]:
        if age <= max_age:
            density = c - m * math.log10(total)
            break
    return 495.0 / density - 450.0


def faulkner(triceps, subscap, suprailiac, abdominal):
    """Faulkner (1968) — the skinfold equation most used with athletes in PT."""
    folds = [triceps, subscap, suprailiac, abdominal]
    if any(f is None for f in folds):
        return None
    return 0.153 * sum(folds) + 5.783


def yuhasz(triceps, subscap, suprailiac, abdominal, thigh, calf):
    """Yuhasz (1974) — 6 skinfolds, developed on athletic populations."""
    folds = [triceps, subscap, suprailiac, abdominal, thigh, calf]
    if any(f is None for f in folds):
        return None
    return 0.1051 * sum(folds) + 2.585


def petroski(sex, age, subscap, triceps, suprailiac, calf):
    """Petroski (1995) — 4 skinfolds, validated on Brazilian adults."""
    folds = [subscap, triceps, suprailiac, calf]
    if any(f is None for f in folds) or age is None or sex != "M":
        return None
    x = sum(folds)
    density = (1.10726863 - 0.00081201 * x + 0.00000212 * x**2
               - 0.00041761 * age)
    return 495.0 / density - 450.0


def fat_from_lean_mass(weight, lean_mass):
    """Mass balance: whatever is not lean mass is fat."""
    if not weight or not lean_mass:
        return None
    return (weight - lean_mass) / weight * 100


def fit_athlete_models(sessions):
    """
    Learn how the athlete column relates to the rest of the row, using only
    the sessions where it is actually printed, and score every candidate by
    leave-one-out cross-validation. LOO is what stops a model that merely
    memorises 5 points from being mistaken for one that predicts.

    Returns (best_name, predict_fn, loo_mae, scoreboard). predict_fn takes a
    session dict and returns the athlete %, or None if inputs are missing.
    """
    paired = [m for m in sessions.values()
              if m.get(FAT_ATH) is not None and m.get(FAT_SED) is not None]
    if not paired:
        return None, None, None, []

    def fit_offset(rows):
        c = statistics.fmean(m[FAT_SED] - m[FAT_ATH] for m in rows)
        return lambda m: (m[FAT_SED] - c) if m.get(FAT_SED) is not None else None

    def fit_ratio(rows):
        k = statistics.fmean(m[FAT_ATH] / m[FAT_SED] for m in rows if m[FAT_SED])
        return lambda m: (m[FAT_SED] * k) if m.get(FAT_SED) is not None else None

    def fit_linear(rows):
        xs = [m[FAT_SED] for m in rows]
        ys = [m[FAT_ATH] for m in rows]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return None
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        a = my - b * mx
        return lambda m: (a + b * m[FAT_SED]) if m.get(FAT_SED) is not None else None

    def fit_mass_balance(rows):
        # nothing to fit — it is an identity, kept in the scoreboard so its
        # accuracy can be compared against the fitted models
        return lambda m: fat_from_lean_mass(m.get("Peso"), m.get("Massa Magra"))

    candidates = {
        "desvio constante": (fit_offset, 1),
        "rácio constante": (fit_ratio, 1),
        "regressão linear": (fit_linear, 2),
        "balanço de massa": (fit_mass_balance, 0),
    }

    scoreboard = []
    for name, (fitter, n_params) in candidates.items():
        # a fit needs at least one more point than it has parameters to be
        # cross-validated at all
        if len(paired) < n_params + 2 and n_params > 0:
            continue
        errors = []
        for i in range(len(paired)):
            train = paired[:i] + paired[i + 1:]
            predict = fitter(train) if train else None
            if predict is None:
                continue
            got = predict(paired[i])
            if got is not None:
                errors.append(abs(got - paired[i][FAT_ATH]))
        if not errors:
            continue
        scoreboard.append({
            "model": name,
            "n_params": n_params,
            "loo_mae_pp": round(statistics.fmean(errors), 3),
            "loo_max_pp": round(max(errors), 3),
            "n_paired": len(paired),
        })

    if not scoreboard:
        return None, None, None, []
    scoreboard.sort(key=lambda r: (r["loo_mae_pp"], r["n_params"]))
    best = scoreboard[0]
    predict = candidates[best["model"]][0](paired)
    return best["model"], predict, best["loo_mae_pp"], scoreboard


def calibrate_gap(sessions):
    """
    How many percentage points the athlete reading sits below the sedentary
    one, for THIS person. Measured from sessions where both are printed;
    otherwise from the printed Massa Magra, which the athlete column tracks.
    Returns (gap_pp, n_sessions, origin) or (None, 0, "").
    """
    printed, implied = [], []
    for m in sessions.values():
        sed = m.get(FAT_SED)
        if sed is None:
            continue
        if m.get(FAT_ATH) is not None:
            printed.append(sed - m[FAT_ATH])
        lean_based = fat_from_lean_mass(m.get("Peso"), m.get("Massa Magra"))
        if lean_based is not None:
            implied.append(sed - lean_based)
    if printed:
        return statistics.fmean(printed), len(printed), "colunas impressas"
    if implied:
        return statistics.fmean(implied), len(implied), "massa magra impressa"
    return None, 0, ""


def corrected_girth(girth_cm, skinfold_mm):
    """Girth minus the fat ring: a proxy for the muscle+bone girth underneath."""
    if girth_cm is None or skinfold_mm is None:
        return None
    return girth_cm - math.pi * (skinfold_mm / 10.0)


def endomorphy(triceps, subscap, supraspinale, height_cm):
    """Heath-Carter endomorphy (fatness rating), height-corrected."""
    folds = [triceps, subscap, supraspinale]
    if any(f is None for f in folds) or not height_cm:
        return None
    x = sum(folds) * (170.18 / height_cm)
    return -0.7182 + 0.1451 * x - 0.00068 * x**2 + 0.0000014 * x**3


def ectomorphy(height_cm, weight_kg):
    """Heath-Carter ectomorphy (linearity rating) from the ponderal index."""
    if not height_cm or not weight_kg:
        return None
    hwr = height_cm / (weight_kg ** (1 / 3))
    if hwr >= 40.75:
        return 0.732 * hwr - 28.58
    if hwr > 38.25:
        return 0.463 * hwr - 17.63
    return 0.1


def derive(sessions, sex, age, gap=None, model=None, model_name=None,
           model_error=None):
    """Body-composition and football/performance metrics, one row per value."""
    out = []

    def add(date, metric, value, unit, group, note=""):
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        out.append({"date": date, "season": season_of(date),
                    "phase": phase_of(date), "group": group,
                    "metric": metric, "unit": unit,
                    "value": round(value, 2), "note": note})

    for date, m in sorted(sessions.items()):
        g = m.get
        height_cm = g("Altura")
        height_m = height_cm / 100 if height_cm else None
        weight = g("Peso")
        fat_pct = g(FAT_SED)
        muscle = g("Massa Muscular")
        lean_printed = g("Massa Magra")
        waist, hip, navel = g("Perímetro Cintura"), g("Perímetro Anca/Glúteo"), g("Perímetro Umbigo")

        # ---------------- sedentários vs atletas ----------------
        # Reconstruct the athlete column when the report leaves it blank.
        ath_printed = g(FAT_ATH)
        ath_lean = fat_from_lean_mass(weight, lean_printed)
        ath_gap = fat_pct - gap if (fat_pct is not None and gap is not None) else None
        ath_faulkner = faulkner(g("Prega Cutânea Triciptal"), g("Prega Cutânea Subescapular"),
                                g("Prega Cutânea Supra-ilíaca"), g("Prega Cutânea Abdominal"))

        ath_model = model(m) if model is not None else None

        if ath_printed is not None:
            ath_value, origin = ath_printed, "impresso no relatório"
        elif ath_model is not None:
            ath_value = ath_model
            origin = (f"modelo '{model_name}' ajustado às sessões com valor "
                      f"impresso (erro LOO {model_error} pp)")
        elif ath_lean is not None:
            ath_value, origin = ath_lean, "reconstruído de (peso - massa magra)/peso"
        elif ath_gap is not None:
            ath_value, origin = ath_gap, "sedentários menos o desvio médio desta pessoa"
        else:
            ath_value, origin = ath_faulkner, "estimado por Faulkner (pregas)"
        add(date, "% Massa Gorda (Atletas)", ath_value, "%", "composicao",
            f"origem: {origin}")
        if fat_pct is not None and ath_value is not None:
            add(date, "Diferença Sedentários - Atletas", fat_pct - ath_value, "pp",
                "composicao", "desvio entre as duas calibrações; deve ser estável")

        # independent skinfold estimates — different method, not a substitute
        add(date, "% Massa Gorda (Faulkner)", ath_faulkner, "%", "composicao",
            "equação de pregas usada com atletas")
        add(date, "% Massa Gorda (Yuhasz)", yuhasz(
            g("Prega Cutânea Triciptal"), g("Prega Cutânea Subescapular"),
            g("Prega Cutânea Supra-ilíaca"), g("Prega Cutânea Abdominal"),
            g("Prega Cutânea Coxa"), g("Prega Gêmeo")), "%", "composicao",
            "6 pregas, população desportiva")
        add(date, "% Massa Gorda (Petroski)", petroski(
            sex, age, g("Prega Cutânea Subescapular"), g("Prega Cutânea Triciptal"),
            g("Prega Cutânea Supra-ilíaca"), g("Prega Gêmeo")), "%", "composicao",
            "4 pregas + idade")

        if ath_value is not None and weight:
            add(date, "Massa Gorda (Atletas)", weight * ath_value / 100, "kg",
                "composicao", "com a calibração de atletas")
            add(date, "Massa Isenta de Gordura (Atletas)",
                weight * (1 - ath_value / 100), "kg", "composicao",
                "coerente com a Massa Magra impressa")

        # ---------------- composition (sedentários) ----------------
        fat_kg = weight * fat_pct / 100 if weight and fat_pct else None
        ffm_kg = weight - fat_kg if fat_kg is not None else None
        add(date, "Massa Gorda", fat_kg, "kg", "composicao",
            "peso x %massa gorda — segue a variação absoluta, não só a %")
        add(date, "Massa Isenta de Gordura", ffm_kg, "kg", "composicao",
            "peso - massa gorda (calibração de sedentários)")
        if ffm_kg is not None and lean_printed:
            add(date, "Coerência: MIG calculada - Massa Magra impressa",
                ffm_kg - lean_printed, "kg", "composicao",
                "se for grande, os dois campos do relatório vêm de calibrações diferentes")

        if height_m:
            if fat_kg is not None:
                add(date, "Índice de Massa Gorda (FMI)", fat_kg / height_m**2,
                    "kg/m2", "composicao", "massa gorda / altura^2")
            if ffm_kg is not None:
                ffmi = ffm_kg / height_m**2
                add(date, "Índice de Massa Isenta de Gordura (FFMI)", ffmi,
                    "kg/m2", "composicao", "massa isenta de gordura / altura^2")
                add(date, "FFMI normalizado (1.80m)", ffmi + 6.1 * (1.80 - height_m),
                    "kg/m2", "composicao",
                    "FFMI ajustado à altura, comparável entre jogadores")
            if muscle:
                add(date, "Índice de Massa Muscular", muscle / height_m**2,
                    "kg/m2", "composicao", "massa muscular / altura^2")

        # ---------------- shape / distribution ----------------
        if waist and height_cm:
            add(date, "Rácio Cintura/Altura", waist / height_cm, "", "distribuicao",
                "referência habitual: abaixo de 0.5")
        if waist and hip:
            add(date, "Rácio Cintura/Anca (recalculado)", waist / hip, "",
                "distribuicao", "recalculado dos perímetros, ignora o valor impresso")
        if navel and height_cm:
            add(date, "Rácio Umbigo/Altura", navel / height_cm, "", "distribuicao")

        limbs = [g(n) for n in ["Prega Cutânea Triciptal", "Prega Cutânea Bicipital",
                                "Prega Cutânea Coxa", "Prega Gêmeo"] if g(n) is not None]
        trunk = [g(n) for n in ["Prega Cutânea Subescapular", "Prega Cutânea Supra-ilíaca",
                                "Prega Cutânea Abdominal"] if g(n) is not None]
        all_folds = [v for k, v in m.items()
                     if k.lower().startswith("prega") and not k.startswith("Soma")]
        if all_folds:
            add(date, "Soma de Pregas (recalculada)", sum(all_folds), "mm", "distribuicao",
                f"soma das {len(all_folds)} pregas medidas")

        # ISAK sums: raw millimetres, no equation, no population assumption.
        # This is what sports anthropometry tracks instead of a %fat number.
        isak8 = {"Prega Cutânea Triciptal": "tricipital",
                 "Prega Cutânea Subescapular": "subescapular",
                 "Prega Cutânea Bicipital": "bicipital",
                 "Prega cutânea Supraespinhal": "supraespinhal",
                 "Prega Cutânea Abdominal": "abdominal",
                 "Prega Cutânea Coxa": "coxa",
                 "Prega Gêmeo": "gémeo",
                 "Prega Cutânea Supra-ilíaca": "crista ilíaca"}
        present = [k for k in isak8 if g(k) is not None]
        missing = [v for k, v in isak8.items() if g(k) is None]
        if present:
            add(date, f"Soma ISAK ({len(present)} de 8 sítios)",
                sum(g(k) for k in present), "mm", "futebol",
                "milímetros medidos, sem equação nem pressupostos"
                + (f" — em falta: {', '.join(missing)}" if missing else ""))
        six = ["Prega Cutânea Triciptal", "Prega Cutânea Subescapular",
               "Prega Cutânea Supra-ilíaca", "Prega Cutânea Abdominal",
               "Prega Cutânea Coxa", "Prega Gêmeo"]
        if all(g(k) is not None for k in six):
            add(date, "Soma 6 pregas (referência de atletas)",
                sum(g(k) for k in six), "mm", "futebol",
                "sítios do padrão de referência para desportistas")
        if trunk:
            add(date, "Soma pregas tronco", sum(trunk), "mm", "distribuicao")
        if limbs:
            add(date, "Soma pregas membros", sum(limbs), "mm", "distribuicao")
        if limbs and trunk and sum(limbs):
            add(date, "Rácio Pregas Tronco/Membros", sum(trunk) / sum(limbs), "",
                "distribuicao", "sobe = gordura mais central; desce = mais periférica")

        dw = durnin_womersley(sex, age, g("Prega Cutânea Triciptal"),
                              g("Prega Cutânea Bicipital"),
                              g("Prega Cutânea Subescapular"),
                              g("Prega Cutânea Supra-ilíaca"))
        add(date, "% Massa Gorda (Durnin-Womersley)", dw, "%", "composicao",
            "estimativa por 4 pregas — método diferente do do relatório")
        if dw is not None and fat_pct is not None:
            add(date, "Diferença entre métodos (%MG)", fat_pct - dw, "pp", "composicao",
                "relatório menos Durnin-Womersley; deve manter-se estável")

        # ---------------- football / performance ----------------
        # Corrected girths strip the fat ring off the limb, so what is left
        # tracks muscle. For a footballer the thigh and calf are the ones that
        # matter for sprinting, jumping and kicking.
        thigh_c = corrected_girth(g("Perímetro Coxa"), g("Prega Cutânea Coxa"))
        calf_c = corrected_girth(g("Perímetro Gémeo"), g("Prega Gêmeo"))
        arm_c = corrected_girth(g("Perímetro Braço"), g("Prega Cutânea Triciptal"))
        add(date, "Perímetro Coxa corrigido", thigh_c, "cm", "futebol",
            "coxa menos a prega — proxy do músculo, não da gordura")
        add(date, "Perímetro Gémeo corrigido", calf_c, "cm", "futebol",
            "gémeo menos a prega — proxy do músculo")
        add(date, "Perímetro Braço corrigido", arm_c, "cm", "futebol",
            "braço menos a prega tricipital")

        # Cross-sectional area grows with the square of the girth, so it is the
        # more sensitive way to see a change in limb muscularity.
        if thigh_c:
            add(date, "Área muscular estimada da coxa", thigh_c**2 / (4 * math.pi),
                "cm2", "futebol", "a partir do perímetro corrigido")
        if calf_c:
            add(date, "Área muscular estimada do gémeo", calf_c**2 / (4 * math.pi),
                "cm2", "futebol", "a partir do perímetro corrigido")

        # Lower-limb muscularity relative to the mass being accelerated: this is
        # the ratio that tracks with acceleration and repeated-sprint work.
        if thigh_c and weight:
            add(date, "Coxa corrigida / peso", thigh_c / weight, "cm/kg", "futebol",
                "musculatura da coxa relativa à massa a acelerar")
        if ffm_kg and weight:
            add(date, "Massa Isenta de Gordura / Peso", ffm_kg / weight * 100, "%",
                "futebol", "fração do peso que é tecido ativo — sobe se perder gordura")
        if ffm_kg and weight:
            add(date, "Índice alométrico de massa magra", ffm_kg / weight**0.67, "",
                "futebol", "massa magra escalada ao peso^0.67 (relação força/tamanho)")
        if muscle and fat_kg:
            add(date, "Rácio Músculo/Gordura (recalculado)", muscle / fat_kg, "",
                "futebol", "recalculado; sobe com músculo ganho ou gordura perdida")

        # Somatotype: endomorphy and ectomorphy are computable from this data.
        # Mesomorphy needs bone breadths (húmero e fémur), which the report
        # does not measure — ask for them if you want the full somatotype.
        supra = g("Prega cutânea Supraespinhal")
        endo = endomorphy(g("Prega Cutânea Triciptal"), g("Prega Cutânea Subescapular"),
                          supra if supra is not None else g("Prega Cutânea Supra-ilíaca"),
                          height_cm)
        note_endo = "Heath-Carter" + ("" if supra is not None
                                      else " (supra-ilíaca no lugar da supraespinhal)")
        add(date, "Somatótipo - Endomorfia", endo, "", "futebol", note_endo)
        add(date, "Somatótipo - Ectomorfia", ectomorphy(height_cm, weight), "", "futebol",
            "linearidade; mesomorfia exige diâmetros ósseos que o relatório não mede")

        # Body surface area — scales sweat rate and heat loss, useful context
        # for hot-weather matches and hydration planning with the nutritionist.
        if height_cm and weight:
            add(date, "Área de Superfície Corporal (Du Bois)",
                0.007184 * height_cm**0.725 * weight**0.425, "m2", "futebol",
                "escala a perda de calor/suor — contexto para jogos com calor")

    return out


def changes(records):
    """Deltas, rate per 30 days, and whether the change beats measurement noise."""
    series = {}
    for r in records:
        series.setdefault(r["metric"], []).append(r)

    rows = []
    for metric, items in series.items():
        items.sort(key=lambda r: r["date"])
        base = items[0]["value"]
        prev = prev_date = None
        for r in items:
            days = delta = rate = ""
            flag = ""
            if prev is not None:
                days = (datetime.fromisoformat(r["date"])
                        - datetime.fromisoformat(prev_date)).days
                delta = round(r["value"] - prev, 2)
                if days:
                    rate = round(delta / days * 30, 3)
                threshold = MEANINGFUL_CHANGE.get(metric)
                if threshold is not None:
                    flag = "sim" if abs(delta) >= threshold else "ruído"
            rows.append({
                "date": r["date"],
                "season": season_of(r["date"]),
                "phase": phase_of(r["date"]),
                "metric": metric,
                "unit": r["unit"],
                "value": r["value"],
                "days_since_previous": days,
                "delta_previous": delta,
                "pct_previous": round((r["value"] - prev) / prev * 100, 2)
                if prev not in (None, 0) else "",
                "rate_per_30d": rate,
                "meaningful_change": flag,
                "delta_baseline": round(r["value"] - base, 2),
                "pct_baseline": round((r["value"] - base) / base * 100, 2) if base else "",
            })
            prev, prev_date = r["value"], r["date"]
    rows.sort(key=lambda r: (r["metric"], r["date"]))
    return rows


def season_summary(records):
    """
    Per season and per key metric: how many measurements, the range, the
    net change and the coefficient of variation. Low CV across a season is
    what "held condition through the season" looks like in the numbers.
    """
    keep = {"Peso", "Percentagem Massa Gorda (Sedentários)", "Massa Muscular",
            "Massa Magra", "Massa Gorda", "Massa Isenta de Gordura",
            "Soma de Pregas", "Soma de Pregas (recalculada)",
            "Soma 6 pregas (referência de atletas)",
            "% Massa Gorda (Atletas)",
            "Perímetro Coxa corrigido", "Perímetro Gémeo corrigido",
            "Massa Isenta de Gordura / Peso"}
    buckets = {}
    for r in records:
        if r["metric"] in keep:
            season = season_of(r["date"])
            # one bucket for the whole season, one per phase within it
            buckets.setdefault((season, "época completa", r["metric"]), []).append(r)
            buckets.setdefault((season, phase_of(r["date"]), r["metric"]), []).append(r)

    rows = []
    for (season, phase, metric), items in sorted(buckets.items()):
        items.sort(key=lambda r: r["date"])
        values = [r["value"] for r in items]
        mean = statistics.fmean(values)
        rows.append({
            "season": season,
            "phase": phase,
            "metric": metric,
            "unit": items[0]["unit"],
            "n_sessions": len(values),
            "first_date": items[0]["date"],
            "last_date": items[-1]["date"],
            "first": values[0],
            "last": values[-1],
            "net_change": round(values[-1] - values[0], 2),
            "min": min(values),
            "max": max(values),
            "range": round(max(values) - min(values), 2),
            "mean": round(mean, 2),
            "cv_pct": round(statistics.pstdev(values) / mean * 100, 2) if mean else "",
        })
    return rows


def quality_flags(records):
    flags = []
    for r in records:
        if r.get("corrected") == "sim":
            continue
        lo_hi = SANITY.get(r["metric"])
        if lo_hi and not (lo_hi[0] <= r["value"] <= lo_hi[1]):
            flags.append(f"{r['date']}  {r['metric']} = {r['value']} "
                         f"(fora de {lo_hi[0]}-{lo_hi[1]}) — provável erro de digitação")

    series = {}
    for r in records:
        series.setdefault(r["metric"], []).append(r)
    for metric, items in series.items():
        items.sort(key=lambda r: r["date"])
        for a, b in zip(items, items[1:]):
            if a["value"] and abs(b["value"] - a["value"]) / abs(a["value"]) > 0.30:
                if not any(metric in f and b["date"] in f for f in flags):
                    flags.append(f"{b['date']}  {metric}: {a['value']} -> {b['value']} "
                                 f"(salto >30%)")
    return sorted(flags)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def write_csv(rows, fields, path):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_wide(records, path):
    dates = sorted({r["date"] for r in records})
    metrics, units = [], {}
    for r in sorted(records, key=lambda r: r["date"]):
        if r["metric"] not in units:
            metrics.append(r["metric"])
            units[r["metric"]] = r["unit"]
    table = {d: {} for d in dates}
    for r in records:
        table[r["date"]][r["metric"]] = r["value"]

    header = ["date", "season", "phase"] + [f"{m} ({units[m]})" if units[m] else m
                                            for m in metrics]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for d in dates:
            w.writerow([d, season_of(d), phase_of(d)]
                       + [table[d].get(m, "") for m in metrics])


def write_workbook(path, raw, derived, change_rows, season_rows, flags,
                   sources, sex, age):
    """One workbook, one sheet per view, formatted for filtering and pivoting."""
    if Workbook is None:
        print("  ! openpyxl não instalado — xlsx ignorado (pip install openpyxl)",
              file=sys.stderr)
        return

    wb = Workbook()
    header_font = Font(name="Arial", bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2F5597")
    body_font = Font(name="Arial")

    def sheet(title, fields, rows, widths=None, number_format="0.00"):
        ws = wb.create_sheet(title)
        ws.append(fields)
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in rows:
            ws.append([row.get(f, "") for f in fields])
        for col_idx, field in enumerate(fields, start=1):
            letter = get_column_letter(col_idx)
            ws.column_dimensions[letter].width = (
                widths.get(field, 14) if widths else max(12, min(38, len(field) + 4))
            )
            for cell in ws[letter][1:]:
                cell.font = body_font
                if isinstance(cell.value, float):
                    cell.number_format = number_format
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(fields))}{len(rows) + 1}"
        return ws

    # --- Leia-me: what is in here, and what was assumed
    ws = wb.active
    ws.title = "Leia-me"
    notes = [
        ("Análise antropométrica — gerado por nutri_to_csv.py", ""),
        ("Gerado em", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Sexo / idade lidos do PDF", f"{sex or '?'} / {age or '?'}"),
        ("Relatórios processados", ", ".join(sources)),
        ("", ""),
        ("Folha", "Conteúdo"),
        ("Sessoes", "Uma linha por avaliação, uma coluna por medida (valores do relatório)"),
        ("Medicoes", "Formato longo: uma linha por (data, medida) — bom para tabelas dinâmicas"),
        ("Derivados", "Métricas calculadas pelo script; coluna 'group' separa composição, distribuição e futebol"),
        ("Variacoes", "Diferença face à sessão anterior e à primeira, ritmo por 30 dias e filtro de ruído"),
        ("Epoca", "Resumo por época e por fase (pré-época, 1ª volta, 2ª volta, final de época)"),
        ("Qualidade", "Valores implausíveis ou saltos >30% detetados nos relatórios"),
        ("", ""),
        ("Pressupostos", ""),
        ("Época", f"começa em {SEASON_START_MONTH:02d} (agosto) e termina em junho; julho fica como fora de época"),
        ("Fases", "definidas em SEASON_PHASES no topo do script"),
        ("%MG Sedentários/Atletas", "duas calibrações do mesmo equipamento, não duas equações de pregas; quando a coluna de atletas falta é reconstruída — ver a coluna 'note' na folha Derivados"),
        ("Métrica mais segura", "a soma de pregas em mm não depende de nenhuma equação nem de pressupostos de população — é a medida a seguir para acompanhar a forma; as %MG são conversões e trazem erro adicional"),
        ("%MG Durnin-Womersley", "estimada a partir de 4 pregas; método diferente do usado no relatório"),
        ("Somatótipo", "endomorfia e ectomorfia apenas — a mesomorfia exige diâmetros ósseos não medidos"),
        ("Ruído", "limiares por medida em MEANINGFUL_CHANGE; abaixo do limiar a variação é erro de medição"),
        ("Valores assinalados", "mantidos como impressos no PDF — ver folha Qualidade antes de analisar"),
    ]
    for label, value in notes:
        ws.append([label, value])
    ws["A1"].font = Font(name="Arial", bold=True, size=13)
    ws["A6"].font = Font(name="Arial", bold=True)
    ws["A14"].font = Font(name="Arial", bold=True)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 95
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if not cell.font.bold:
                cell.font = body_font
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    # --- Sessoes (wide)
    dates = sorted({r["date"] for r in raw})
    metrics, units = [], {}
    for r in sorted(raw, key=lambda r: r["date"]):
        if r["metric"] not in units:
            metrics.append(r["metric"])
            units[r["metric"]] = r["unit"]
    table = {d: {} for d in dates}
    for r in raw:
        table[r["date"]][r["metric"]] = r["value"]
    wide_fields = ["date", "season", "phase"] + [
        f"{m} ({units[m]})" if units[m] else m for m in metrics
    ]
    wide_rows = []
    for d in dates:
        row = {"date": d, "season": season_of(d), "phase": phase_of(d)}
        for m in metrics:
            row[f"{m} ({units[m]})" if units[m] else m] = table[d].get(m, "")
        wide_rows.append(row)
    sheet("Sessoes", wide_fields, wide_rows)

    sheet("Medicoes",
          ["date", "season", "phase", "metric", "unit", "value", "value_original",
           "corrected", "correction_note", "reference", "source_file"],
          [dict(r, season=season_of(r["date"]), phase=phase_of(r["date"])) for r in raw],
          widths={"metric": 34, "correction_note": 52, "reference": 14,
                  "source_file": 26})

    sheet("Correcoes",
          ["date", "metric", "unit", "value_original", "value", "correction_note"],
          [r for r in raw if r.get("corrected") == "sim"] or
          [{"date": "", "metric": "Sem correções aplicadas."}],
          widths={"metric": 34, "correction_note": 62})

    sheet("Derivados",
          ["date", "season", "phase", "group", "metric", "unit", "value", "note"],
          derived, widths={"metric": 38, "note": 60})

    sheet("Variacoes",
          ["date", "season", "phase", "metric", "unit", "value", "days_since_previous",
           "delta_previous", "pct_previous", "rate_per_30d", "meaningful_change",
           "delta_baseline", "pct_baseline"],
          change_rows, widths={"metric": 38})

    sheet("Epoca",
          ["season", "phase", "metric", "unit", "n_sessions", "first_date", "last_date",
           "first", "last", "net_change", "min", "max", "range", "mean", "cv_pct"],
          season_rows, widths={"metric": 38, "phase": 16})

    sheet("Qualidade", ["flag"], [{"flag": f} for f in flags] or
          [{"flag": "Sem valores suspeitos detetados."}], widths={"flag": 110})

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inputs", nargs="*", default=[INPUT_DIR],
                    help="PDF files, folders or globs (default: %(default)s)")
    ap.add_argument("-o", "--output", default=OUTPUT_PREFIX,
                    help="output prefix, e.g. out/body (default: %(default)s)")
    ap.add_argument("--raw-only", action="store_true",
                    help="skip derived metrics, changes and season summary")
    ap.add_argument("--corrections", default=CORRECTIONS_FILE,
                    help="local JSON of confirmed typo fixes (default: %(default)s)")
    ap.add_argument("--no-excel", action="store_true",
                    help="write only the CSVs, skip the xlsx workbook")
    args = ap.parse_args()
    CORRECTIONS.update(load_corrections(args.corrections))

    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        sys.exit(f"No PDFs found in: {', '.join(args.inputs)}")

    print(f"Found {len(pdfs)} PDF(s)\n")
    all_records, age, sex = [], None, None
    for path in pdfs:
        records, file_age, file_sex = to_records(path)
        report_date = max((r["date"] for r in records), default="")
        for r in records:
            r["_report_date"] = report_date
        age = file_age if file_age is not None else age
        sex = file_sex or sex
        print(f"{os.path.basename(path):<40} {len(records):>4} values / "
              f"{len({r['date'] for r in records})} sessions")
        all_records += records

    raw = apply_corrections(dedupe(all_records))
    if not raw:
        sys.exit("Nothing extracted.")
    applied = [r for r in raw if r["corrected"] == "sim"]
    if applied:
        print("\nCorreções aplicadas:")
        for r in sorted(applied, key=lambda r: (r["date"], r["metric"])):
            print(f"  {r['date']}  {r['metric']}: "
                  f"{r['value_original']} -> {r['value']}  ({r['correction_note']})")

    prefix = args.output
    write_csv(raw, ["date", "metric", "unit", "value", "value_original", "corrected",
                    "correction_note", "reference", "source_file"],
              f"{prefix}_measurements.csv")
    write_wide(raw, f"{prefix}_wide.csv")
    print(f"\n{prefix}_measurements.csv   {len(raw)} rows, "
          f"{len({r['date'] for r in raw})} sessions, "
          f"{len({r['metric'] for r in raw})} metrics")
    print(f"{prefix}_wide.csv           one row per session")

    derived, change_rows, season_rows = [], [], []
    if not args.raw_only:
        sessions, _ = by_session(raw)
        gap, n_gap, gap_origin = calibrate_gap(sessions)
        model_name, model, model_error, scoreboard = fit_athlete_models(sessions)
        if scoreboard:
            print("\nModelos para %MG (Atletas), validados por leave-one-out:")
            for row in scoreboard:
                mark = "<-- usado" if row["model"] == model_name else ""
                print(f"  {row['model']:<20} erro médio {row['loo_mae_pp']:>6} pp "
                      f"| pior {row['loo_max_pp']:>6} pp "
                      f"| {row['n_paired']} sessões emparelhadas {mark}")
        elif gap is not None:
            print(f"\nSem coluna de atletas em nenhum relatório. "
                  f"Desvio estimado pela massa magra: {gap:+.2f} pp "
                  f"({n_gap} sessões)")
        derived = derive(sessions, sex, age, gap, model, model_name, model_error)
        write_csv(derived,
                  ["date", "season", "phase", "group", "metric", "unit", "value", "note"],
                  f"{prefix}_derived.csv")
        n_football = len([r for r in derived if r["group"] == "futebol"])
        print(f"{prefix}_derived.csv        {len(derived)} values "
              f"({n_football} do grupo 'futebol'; sexo={sex or '?'}, idade={age or '?'})")

        combined = raw + [dict(r, reference="", source_file="derived") for r in derived]
        change_rows = changes(combined)
        write_csv(change_rows,
                  ["date", "season", "phase", "metric", "unit", "value",
                   "days_since_previous",
                   "delta_previous", "pct_previous", "rate_per_30d",
                   "meaningful_change", "delta_baseline", "pct_baseline"],
                  f"{prefix}_changes.csv")
        print(f"{prefix}_changes.csv        deltas, ritmo por 30 dias, filtro de ruído")

        season_rows = season_summary(combined)
        write_csv(season_rows,
                  ["season", "phase", "metric", "unit", "n_sessions",
                   "first_date", "last_date",
                   "first", "last", "net_change", "min", "max", "range", "mean", "cv_pct"],
                  f"{prefix}_season_summary.csv")
        print(f"{prefix}_season_summary.csv estabilidade e variação por época")

    flags = quality_flags(raw)

    if not args.no_excel:
        xlsx_path = f"{prefix}_analysis.xlsx"
        write_workbook(xlsx_path, raw, derived, change_rows, season_rows, flags,
                       sorted({r["source_file"] for r in raw}), sex, age)
        if os.path.exists(xlsx_path):
            print(f"{xlsx_path}      workbook com uma folha por vista")

    if flags:
        print("\nData-quality flags (values kept as printed, check the source):")
        for f in flags:
            print(f"  - {f}")


if __name__ == "__main__":
    main()