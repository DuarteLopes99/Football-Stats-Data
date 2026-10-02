# Body composition — the nutrition side of the GPS data

Modules: [`src/football_stats/body/`](../src/football_stats/body/) ·
Extraction: [`tools/nutrition_pdf_to_csv.py`](../tools/nutrition_pdf_to_csv.py) ·
Data: [`data/body/`](../data/body/) ·
Tests: [`tests/test_body.py`](../tests/test_body.py) ·
Dashboard: **Body Composition** and **Body × Performance** tabs

---

## 1. What this data is — and what it is not

It is **anthropometry**: periodic nutritionist assessments recording skinfolds,
girths, scale readings, and the body-composition estimates computed from them,
taken every few weeks across several seasons. **The values themselves are
personal health data and never enter the repo** — `data/body/` is gitignored, and
this document describes methods, not measurements.

It is **not intake**. Nothing in these files records what was eaten. Every
"nutritional" reading of this data is therefore an inference about what the body
did in response to a diet and a training load, of which only the second is
measured — and the GPS side supplies only the *expenditure* half of an energy
balance whose *intake* half is unmeasured. The tab is named "Body & Nutrition"
because that is the question it informs, not because the data answers it.

## 2. Files and provenance

All five CSVs in `data/body/` are produced by `tools/nutrition_pdf_to_csv.py`,
which parses the anthropometric table out of each report PDF. **That
script is the authority on the derived-metric formulas**; the `body` package
only reads its output.

| File | Contents |
| --- | --- |
| `body_measurements.csv` | Values as reported, one row per (date, metric), with the source PDF — plus `value_original` / `corrected` / `correction_note` where a printed figure was corrected |
| `body_wide.csv` | The same values pivoted, one row per assessment |
| `body_derived.csv` | Computed metrics, tagged `composicao` / `distribuicao` / `futebol` |
| `body_changes.csv` | Deltas vs. previous assessment and vs. baseline, with a `meaningful_change` flag |
| `body_season_summary.csv` | Per-season and per-phase net change and stability |

Every table also carries `phase` — where in the football calendar the assessment
falls (pré-época, 1ª volta, 2ª volta, final de época, fora de época). It is the
most useful grouping this data has: a pre-season figure and a mid-season one
describe different athletes, and comparing them directly is what makes body
composition charts misleading.

The derived metrics come from: Durnin & Womersley (1974) body density from four
skinfolds converted to %fat with Siri; the Heath-Carter endomorphy and
ectomorphy components (mesomorphy is **not** computed — it needs bone diameters
the reports don't measure); corrected girths (girth minus the skinfold at that
site) and the limb muscle areas built from them; and Du Bois body surface area.

The report PDFs themselves are **not** in this repo — they are personal medical
documents and stay outside it. Regenerate the CSVs by pointing the script at
wherever they live:

```bash
python3 tools/nutrition_pdf_to_csv.py /path/to/reports -o data/body/body
```

## 3. Two conventions that had to be reconciled

### Season boundaries

The extraction script starts a season on **1 August**; `gps/seasons.py` starts
it on **1 July**. An assessment taken in July falls in that gap: the script
labels it with the season that just ended, but under the GPS convention it
belongs to the new one. The loaders keep the exported label as `season_reported` and
recompute `season` with the GPS convention, so the dashboard's Season selector
filters body and GPS data consistently instead of splitting one season across
two selections.

`load_season_summary` is the exception: its rows are already aggregated under
the August-start convention, and re-tagging a summary row would misattribute
the assessments behind it. It keeps `season_reported` only.

### Column naming

`body_wide.csv` appends the unit to each header (`Peso (kg)`), while the long
files keep metric and unit in separate columns (`Peso`, `kg`). `strip_unit_suffix`
normalizes the wide headers so callers can name a metric once regardless of
which file it lives in — `Peso` is measured, `Massa Gorda` is derived, and
`body_long` looks in both.

## 4. Corrections are applied, and shown

The extraction script sanity-checks each metric against a plausible range. Where
the true figure has been confirmed against the source it applies a correction —
and keeps the printed value in `value_original` rather than overwriting it.
**A corrected dataset that cannot show what it corrected is just an unsourced
one**, so `applied_corrections` surfaces the full audit trail and the dashboard
puts it in a Data quality expander.

Confirmed corrections are listed in **`data/body/corrections.json`** — local and
gitignored with the rest of `data/body/`, because each entry is a dated personal
measurement. The extraction script reads it on every run, so a fix survives
re-extraction without the value ever being committed. Format:

```json
[{"date": "YYYY-MM-DD", "metric": "Perímetro Cintura", "value": 0.0, "why": "printed with an extra digit"}]
```

A typical case is a girth printed with an extra leading digit (a three-digit
waist in centimetres). It also shows why dependent figures matter: the
waist/hip ratio printed beside it was computed from the wrong waist, so the
script recomputes it from the corrected value — one transcription fix
propagates.

`implausible_rows` re-derives the range check as a second line of defence.
Anything still listed there was flagged but **not** confirmed, and should be
treated as missing along with everything derived from it. It is currently empty,
which is the expected state.

## 5. Smallest worthwhile change

`MEANINGFUL_CHANGE` gives a per-metric threshold below which a change is inside
caliper/scale noise — 0.8 kg for body mass, 0.5 kg for the mass compartments,
4 mm for the skinfold sum, 1.0 cm for waist and thigh girth. It is mirrored
from the extraction script, which is where it is applied to produce
`body_changes.csv`'s `meaningful_change` column.

**These are practitioner judgement about repeatability, not figures from a
published typical-error study.** A metric with no entry gets a blank flag rather
than a guessed one. The dashboard marks sub-threshold changes as *(noise)*
rather than hiding them.

## 6. Reading the colours

The dashboard tints changes green or red. That needs a direction per metric, and
`data_store` declares one explicitly:

- **`LOWER_IS_BETTER`** — fat mass and every estimator of it, skinfold sums, the
  central-adiposity girths and ratios, endomorphy.
- **`HIGHER_IS_BETTER`** — lean and muscle mass, their height- and weight-scaled
  indices, the corrected (fat-free) limb girths and areas.
- **Neutral** — everything else, *deliberately*. Body mass, height, BMI, girths
  that mix muscle and fat, the somatotype linearity component and every
  methodological cross-check are directionless for a footballer. **A heavier
  reading is not "better" than a lighter one**, and colouring it green would
  assert a goal this data does not contain.

A change is only called better or worse when two conditions hold together: it
cleared that metric's `MEANINGFUL_CHANGE` threshold, *and* the metric has a
direction. Otherwise it reads *within noise* or *no direction*. The dashboard
also shows the classification itself in an expander — a green arrow means
nothing without knowing which way the metric is supposed to move.

`verdict_counts` reports improved/regressed against the count of **directional**
metrics, not the total: metrics that can't improve don't belong in the
denominator.

Both baselines are offered — *first assessment in scope* and *previous
assessment* — because they routinely disagree. Fat mass can be down across a
season while up since the last check, and reporting only one of those is how a
summary becomes misleading.

## 7. How it joins to GPS

### As-of, backward only

The two datasets have very different cadences — ~140 GPS sessions per season
against an assessment every 3–9 weeks. `attach_body_state` tags each session
with the most recent assessment **at or before** its date, because that is the
body that ran it. Using the nearest assessment in either direction would let a
later measurement explain an earlier session.

`days_since_assessment` is kept so a stale tag stays visible. Beyond
`max_staleness_days` (default 120) the body columns are blanked: an assessment
four months old describes a different athlete, and carrying it forward
indefinitely would invent a measurement that was never taken.

### Assessment windows

`assessment_windows` is the closest this data comes to a nutrition view: one row
per gap between consecutive assessments, pairing the football played in that
block with how the body moved across it.

Columns: window start and end, days, sessions, km per week and football kcal
per day from the GPS side, then the change (Δ) in each selected body metric
across the block.

The load and the body change are deliberately **side by side and never divided
into each other**. With no intake data and a handful of blocks, a "kcal per kg
lost" figure would read as a calculation when it would be a coincidence.

A block with zero sessions is an off-season gap between assessments, not
missing data — the body record starts a year before the GPS record, so the
whole of 2024/25 has assessments and no sessions.

### Calories

`calories` is the **GPS unit's own estimate of the football energy cost**. It
excludes resting metabolism and everything done off the pitch, and
device-estimated expenditure is approximate even for what it does cover. Use
`football_kcal_per_day` as a relative signal ("this block was heavier than that
one") and never as a kcal budget.

## 8. Does body composition relate to running output?

That question gets its own tab and its own module,
[`body/performance_link.py`](../src/football_stats/body/performance_link.py).

**Alignment.** Each assessment is paired with the *average* GPS output over a
window **before** it. Before, because a body measurement describes the state the
athlete arrived in; averaged, because a window with 12 sessions and one with 6
would otherwise differ on volume alone, which is a fact about the fixture list.
The window length is a **dashboard control**, defaulting to 28 days (the
chronic-load window used by ACWR), because it is the single lever on the thing
that actually limits this analysis — how many assessments have any training
behind them. A short window describes a real training block; a long one pairs
more assessments but blurs across blocks. The trade-off belongs to the reader.

**Method.** Spearman rank correlation (no linearity assumed, not dragged by one
pre-season outlier), every p-value carried alongside a Benjamini-Hochberg
q-value computed over the **whole** grid tested, and `n` plus a `reliability`
tier on every row. With ~60 body metrics against 8 performance metrics the grid
is several hundred tests; a handful clear p<0.05 from noise alone, and reporting
the strongest few without correction is how a search becomes a "finding".

**Analysed at the power that exists, not withheld until it is comfortable.** An
earlier version dropped every pair below `MIN_PAIRS` (8). On this dataset that
meant *every* pair, so the tab showed nothing at all — a threshold chosen for a
study design, silently deleting a real record. The floor is now
`ABSOLUTE_MIN_PAIRS` (4), which is simply where a rank correlation stops
existing, and `MIN_PAIRS` marks where a coefficient becomes *worth acting on*
rather than where it becomes visible:

| n | `reliability` |
| --- | --- |
| 8+ | worth acting on |
| 6–7 | indicative |
| 4–5 | anecdotal |
| <4 | not testable (dropped) |

**Coverage is still the binding constraint**, and is reported as two separate
questions rather than one: `analysable` (can this run at all) and `well_powered`
(does its output carry weight). Collapsing them is what suppressed the tab.

| Lookback | Assessments paired | Max n | Survive FDR |
| --- | --- | --- | --- |
| 14 d | 6 / 22 | 6 | 1 |
| 28 d | 6 / 22 | 6 | 0 |
| 42–90 d | 7 / 22 | 7 | 0 |
| 120 d | 8 / 22 | 8 | 0 |

The limiting factor is **overlap, not method**: the body record starts about a
year before the GPS record, so most assessments have nothing to pair with.

**The one survivor is a worked example of why the tiers exist.** At a 14-day
window, `Rácio Músculo/Gordura` vs. `distance_per_min` comes out at
**rho = −1.000, n = 6** and clears FDR. It is not a finding: with 6 points there
are only 720 possible rank orderings and one of them is the perfect one, and the
p-value clears correction precisely because it is computed as though the sample
were adequate. `summarise_findings` names this case explicitly
(`suspect_survivors`), and the dashboard renders a survivor found at low power
in **amber rather than green** — styling it as a conclusion would undo the rest
of the module. Widen the window by one step and it disappears.

**What is supported today** is the phase comparison, which the calendar gives
for free:

| Phase | Assessments | Sessions | Mean distance | Mean sprints |
| --- | --- | --- | --- | --- |
| 1ª volta | 8 | 39 | 6215 m | 12.3 |
| 2ª volta | 7 | 46 | 5046 m | 8.0 |

Distance down ~19% and sprint count down ~35% in the second half of the season,
across more sessions. Descriptive, and worth a look — not a finding.

**Even a surviving correlation would not be causal.** Fat mass falls through
pre-season while running volume rises and match minutes climb as fitness
returns. Body composition, training load and the calendar all move together, so
a correlation between any two of them is expected without either driving the
other. The honest reading is always *"these moved together"*.

## 9. What this cannot support

- **Attributing a composition change to training load.** Load is one input among
  many, and the others aren't recorded.
- **Attributing it to diet.** Intake is not measured at all.
- **Reading body mass as body composition.** Mass moves with hydration and
  glycogen as much as with fat, which is exactly why the 0.8 kg threshold exists.
- **Correlating a GPS metric against a body metric** as evidence of anything.
  See §8: with the current overlap nothing reaches the sample size at which a
  coefficient carries weight, and it would still be descriptive if it did.

The honest use is descriptive: *this* block looked like *this*, and the body
moved *that* way over it. That is genuinely useful for a conversation with a
nutritionist. It is not a finding.
