# Football Stats Data

Two things live in this repo:

1. **Season stats & prediction** — scrape fixtures/results/player stats from
   zerozero.pt, compute league tables, and run a Monte Carlo simulation of the
   remaining fixtures to predict the final table.
2. **GPS performance analysis** — track training/match GPS data (distance, sprints,
   top speed, load, etc.) and analyze trends over a season and across seasons.
   The GPS dashboard also covers **fatigue and mechanical load** (second-half
   sprint retention, accel/decel load, high-speed exposure), pulls in **league
   fixture context** for official matches (opponent, venue, result, and the
   official match-sheet minutes as the per-90 denominator), and tracks
   **body composition** from periodic nutrition reports — including an explicit
   test of whether body composition relates to running output at all.

Both have a Streamlit dashboard. Everything else is a small, tested Python
package (`src/football_stats`) that the dashboards call into — the goal is that
analysis logic lives in reusable functions, not only inside notebook cells.

📖 **Read the full docs before making changes:**
[`docs/gps_report.md`](docs/gps_report.md) ·
[`docs/season_prediction.md`](docs/season_prediction.md) ·
[`docs/gps_analysis.md`](docs/gps_analysis.md) ·
[`docs/skillcorner_metrics.md`](docs/skillcorner_metrics.md) ·
[`docs/position_baselines.md`](docs/position_baselines.md) ·
[`docs/load_monitoring.md`](docs/load_monitoring.md) ·
[`docs/match_context.md`](docs/match_context.md) ·
[`docs/physical_profile.md`](docs/physical_profile.md) ·
[`docs/body_composition.md`](docs/body_composition.md)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip          # venv's bundled pip may be too old for `pip install -e .`
pip install -r requirements.txt
pip install -e .
```

The package targets Python 3.9+. `pip install -e .` needs pip >= 21.3 (PEP 660
editable installs from `pyproject.toml`); macOS's system Python ships a much
older pip inside new venvs, hence the `pip install -U pip` line.

## Quickstart

```bash
streamlit run dashboards/season_dashboard.py   # league table + Monte Carlo prediction
streamlit run dashboards/gps_dashboard.py      # GPS Report + More analysis
pytest tests/                                   # 153 tests, ~3s
```

Run both from the **repo root**: that is where Streamlit picks up the dark theme
in `.streamlit/config.toml` (which also keeps the server on `localhost` only and
usage statistics off).

**One-click launch (macOS):** `tools/open_gps_dashboard.command` starts the GPS
dashboard on port 8520 and opens it in the browser — or just opens it if it's
already running. Link it to the Desktop once:

```bash
ln -s "$PWD/tools/open_gps_dashboard.command" ~/Desktop/"GPS Dashboard.command"
```

Double-click the link; close its Terminal window to stop the dashboard. The dashboards add `src/` to the path themselves, so
they run from a fresh clone after `pip install -r requirements.txt`.

## GPS Report

`dashboards/gps_dashboard.py` opens on the **GPS Report**, a single-page, black,
Power BI-style weekly report modelled on the "Weekly Change % GPS Report" layout
used by club sports scientists. The sidebar holds the player block and
the global filters — season, date range (two date inputs + a slider, kept in
sync), session type (all / official matches / training / practice matches) and a
focus metric — and every section follows them.

| # | Section | What it shows |
|---|---|---|
| 1 | **Weekly change %** + KPI cards | One row per session, one heat-coloured cell per metric (Total Distance, HSR & Sprint, Max Speed, High-Intensity Actions, Distance per Minute): % change vs the same MD label in the previous microcycle, falling back to the previous session of the same type (●). Below it, one card per metric: the average session in range on a semicircle gauge against Gref (Max Speed as a big number). |
| 2 | **Weekly load & ACWR** | Sunday–Saturday weekly load of the focus metric, stacked by session type, rises above +10 % flagged; ACWR in a panel below with the 0.8–1.5 band. |
| 3 | **Match demand & microcycle** | Each session as % of Gref; mean load per MD label for regular microcycles; a % of Gref table by MD day for every report metric. |
| 4 | **Speed & sprint** | Max speed per session against the season best; weekly sprint distance. |
| 5 | **Practice matches** | Friendlies vs official matches as % of Gref — does a friendly reproduce match demand? |
| 6 | **Session detail** | Sortable table, type and MD tagged, cells shaded by % of Gref. |

The **More analysis** page keeps the deeper tabs (monthly, intensity, baselines,
quality, performance insights, physical profile, body composition, body ×
performance, add session), restyled to the same theme and filters.

**Definitions and thresholds** — all in `src/football_stats/gps/config.py`, in
full in [`docs/gps_report.md`](docs/gps_report.md):

- **Bands (STATSports):** HSR & Sprint = distance > 19.8 km/h, sprinting included
  (the export's `high_speed_distance_m`); HSR alone = 19.8–25.2 km/h; Sprint >
  25.2 km/h; accelerations/decelerations beyond ±3 m/s². High-Intensity Actions =
  acc + dec + sprints. Distance per minute = distance ÷ GPS duration (recomputed).
- **Gref** = mean of the best 5 official-match values per metric, this season
  (fewer than 5 → all of them, with a warning; a season without matches borrows
  the previous one's). Unused-substitute matches never count; per-minute rates
  ignore appearances under 20 minutes.
- **MD labels:** official match = MD; up to 2 days after = MD+1/MD+2; otherwise
  MD−n to the next official match; friendlies never anchor. A microcycle runs MD →
  day before the next MD; longer than 10 days = extended.
- **Heat colours** on |% change|: ≤ 10 % green, 10–20 % amber, 20–30 % orange,
  > 30 % red, interpolated.
- **ACWR** = this week ÷ mean of the previous 4 weeks (EWMA selectable), all
  session types, no ratio before 4 full weeks or for a partial final week. Safe
  band 0.8–1.5. *A monitoring indicator, not an injury predictor.*
- **Not possible with this export:** a training-load metric (no Player Load /
  DSL / HML — calories are not load), and time-to-speed or acceleration by speed
  band (no per-second velocity data).

## Regenerating `data/body/` from new nutrition report PDFs

```bash
python3 tools/nutrition_pdf_to_csv.py /path/to/report/pdfs -o data/body/body
```

The report PDFs are personal medical documents and deliberately live **outside**
this repo — only the extracted CSVs are stored here, and **`data/body/` is
gitignored** so those don't reach a remote either. Regenerate it locally with
the command above; it is not something a fresh clone will have. The script is also the
authority on every derived body metric (Durnin & Womersley body density, the
Heath-Carter somatotype components, corrected girths); the `body` package only
reads its output. See [`docs/body_composition.md`](docs/body_composition.md).

## Syncing `gps_sessions.csv` from the STATSports workbook

The source of truth is the STATSports export workbook
`SATS_Football_GPS_Advanced.xlsx`, which lives **outside** the repo (by default
next to it: `../SATS_Football_GPS_Advanced.xlsx`; override with the
`FOOTBALL_GPS_XLSX` environment variable). `data/gps/gps_sessions.csv` is its
tidy sub-product. After updating the workbook:

```bash
python -m football_stats.gps.sync --check   # show added/removed rows, write nothing
python -m football_stats.gps.sync           # rebuild the CSV
```

The workbook is only ever read. **The sync overwrites the CSV, it doesn't merge**
— a session added through the dashboard's "Add Session" form exists only in the
CSV and is lost at the next sync, so add new sessions to the workbook. The
dashboard's sidebar warns when the workbook is newer than the CSV.

## Repository layout

```
Football-Stats-Data/
├── docs/                    # detailed docs — start here for anything beyond a quick run
├── src/football_stats/      # the package: scraping, season, players, gps
├── dashboards/               # Streamlit apps: season_dashboard.py, gps_dashboard.py (shell)
│                             #   + gps_report.py / gps_analysis.py (its two pages)
├── .streamlit/config.toml    # dark theme (mirrors gps/config.py) + usage stats off
├── tools/                    # one-off extractors that write into data/ (not imported by the package)
├── data/
│   ├── seasons/<key>/{raw,processed}/   # per-season fixture data
│   ├── gps/gps_sessions.csv             # every training + match GPS session, one tidy file
│   └── body/                            # body-composition assessments from nutrition reports
└── tests/                    # pytest — includes regression tests for two bugs found while porting
```

## Important instructions

- **Don't edit `data/gps/gps_sessions.csv` by hand** — fix the workbook and
  re-sync (see above). Every threshold, colour and column mapping of the GPS
  report lives in `src/football_stats/gps/config.py`; change it there, not in
  chart code.
- **Adding a season/division is a config change, not a code change** — see
  "Declaring a season" in [`docs/season_prediction.md`](docs/season_prediction.md).
  Don't hardcode a new team or competition name into `season/*.py`.
- **After scraping fresh fixtures**, you still need to re-run the processing step
  (`split_played_remaining` + `save_processed`) to refresh
  `data/seasons/<key>/processed/` — the scraper only writes `raw/`. See step 3 of
  the season-prediction doc.
- **`mansores_2025_26` is only partially seeded** (Mansores' own games only, not
  other teams' games against each other) — the season dashboard shows an in-app
  banner about this. Don't treat other teams' standings rows as accurate until
  you've run the scraper for full coverage.
- **Every chart is Plotly** (`gps/charts.py`, and the `plot_*` methods in
  `gps/analyzer.py`), styled with the `gps_dark` template. Render with
  `st.plotly_chart(fig, theme=None)` — without `theme=None` Streamlit's own theme
  overrides the template's colours.
- **A GPS "game" session's `competition_type` decides whether it's an official
  match or a practice match** (`"Campeonato"`/`"Taça"` → official,
  `"Treino"`/missing → practice) — get it right when adding a session, since
  every chart/table in the GPS dashboard splits on this, not on `session_kind`
  alone. See "Match category" in [`docs/gps_analysis.md`](docs/gps_analysis.md#4-match-category-official-vs-practice-vs-training).
- **GPS analysis is season-scoped** (a season = Jul 1–Jun 30). Weekly
  aggregation uses Sunday–Saturday calendar weeks computed from the dates, never
  the hand-typed `week` column, and Gref, MD labels and ACWR are computed per
  season. See §5 of
  [`docs/gps_analysis.md`](docs/gps_analysis.md#5-seasons-why-raw-month-numbers-were-wrong-and-what-replaced-them).
- **`.venv/` is gitignored on purpose** — don't commit it. Regenerate with the
  Setup steps above on a fresh clone.
- **`.gitignore` ignores `*.csv` by default and then re-includes `data/gps/` and
  `data/seasons/`.** Those two are the repo's actual dataset and are tracked;
  without the `!` lines a future scrape would write a CSV that git silently
  ignored. `data/body/` is excluded as a whole directory rather than by
  extension, because `body_analysis.xlsx` is the same personal health record in
  another container.
- **Don't badge a metric as "SkillCorner" without checking
  [`docs/skillcorner_metrics.md`](docs/skillcorner_metrics.md) first.** Only
  per-90 normalization and percentile-based comparison are directly borrowed
  from their actual open-source toolkit; `robust_top_speed` is explicitly an
  *adaptation* of PSV-99, not the metric itself. ACWR, Training Monotony, and
  Training Strain are general sports science (Gabbett 2016; Foster 1998), not
  SkillCorner's — they live in `gps/load_monitoring.py`, not
  `gps/skillcorner_metrics.py`. See
  [`docs/load_monitoring.md`](docs/load_monitoring.md) ·
[`docs/match_context.md`](docs/match_context.md) ·
[`docs/physical_profile.md`](docs/physical_profile.md) ·
[`docs/body_composition.md`](docs/body_composition.md) before extending either
  module.
- **Use `minutes_game_zerozero`, not `duration_min`, as the per-90 denominator
  for matches.** The first is official match-sheet time, the second is how long
  the GPS unit was recording. The gap between them is **instrumentation, not
  error** — the unit goes on early and gets forgotten after the whistle, giving
  a consistent median **+7 min** overhang. The dashboard's single per-90 table
  runs `add_per90_columns(minutes_col="official_minutes")`, which prefers the
  match sheet and falls back to GPS runtime for training (which has no match
  sheet); `minutes_source` says which was used per row. The one case that *does*
  cost data is a **negative** overhang (unit under-recorded, so the totals
  themselves are short) — currently one match, 2025-11-16.
- **The right denominator makes cameos read as absurd, and that must be
  flagged.** 2070 m in 9 official minutes is 20 700 m per 90. `MINUTES_FLOOR`
  (20 min) is where a rate stops being a measurement: aggregates
  (`output_by_result`, `output_by_venue`) **exclude** those rows, per-session
  listings **keep** them and set `short_appearance`. Both read the same
  constant. Don't hardcode a second one.
- **There is no Match Context tab** — it was organised around where data came
  from rather than around a question. Opponent/venue/result now sit on the
  Overview session rows, the result/venue splits in Intensity, and per-90 plus
  the overhang audit in Performance Insights.
- **Match context comes from `session_type`, not from the fixture scrape.**
  `gps/match_label.py` parses `"Jornada 11 - Vila Viçosa (FORA) 2-3"` into
  opponent / venue / score / result. It resolves **38 of 38** game sessions
  including friendlies; the fixture join managed 13 of 26 official matches and
  no friendlies at all, because the scrape stops at 2026-01-17 — which is why
  those Overview columns used to read blank. `match_link`'s fixture functions
  are kept (still the only source of the league's own `competition`/`matchweek`)
  but are no longer wired into any tab.
- **The scoreline is written home-first, not your-team-first.** An away `0-2` is
  a **win**. This is pinned against the 13 matches the scrape independently
  recorded — venue 13/13, result 13/13, scoreline 12/13. The one scoreline
  disagreement is 2025-11-02 (label `5-1`, scrape `5-0`; both a win), so one of
  the two records has a typo.
- **Don't let the add-session form write a freehand label for a game.** It takes
  opponent/venue/goals/matchweek as fields and composes the label with
  `build_match_label()`, which round-trips through `parse_match_label()`. A
  label in any other shape silently loses its match context everywhere.
  See [`docs/match_context.md`](docs/match_context.md).
- **Exclude sub-50-minute appearances from second-half retention.** Three
  matches show 18–25 first-half sprints then zero, and all three are 45-minute
  outings — a half-time substitution, not a collapse. Including them drags the
  median from 0.55 to 0.45. `gps/fatigue.second_half_retention()` guards this;
  see [`docs/physical_profile.md`](docs/physical_profile.md).
- **Distance is a metabolic proxy only.** ACWR, monotony and strain all run on
  `total_distance_m` and are blind to the mechanical cost of changing speed.
  `gps/fatigue.add_mechanical_load()` adds that axis, and `compute_acwr()`
  accepts `load_col="mechanical_load"` to monitor it — the two ratios routinely
  disagree, which is the point.
- **Fixture data is about the team; GPS data is about one player.** The fixture
  link adds opponent/venue/result *context* to a match session — it does not
  make a team result a measure of individual performance. Splits by result or
  venue always report `n`, and with the current data that `n` is 4 vs. 1.
  Don't read them as findings.
- **`data/body/` is anthropometry, not intake.** No file in this repo records
  what was eaten, so nothing here measures diet — only what the body did.
  Assessment-to-GPS joins are as-of and backward-only (a session is described by
  the *previous* assessment, never a later one), and load is shown next to body
  change rather than divided into it. See
  [`docs/body_composition.md`](docs/body_composition.md).
- **Don't colour a body metric green without checking its direction.**
  `body.data_store` declares `LOWER_IS_BETTER` / `HIGHER_IS_BETTER` explicitly,
  and everything else is **neutral on purpose** — body mass, BMI and mixed
  muscle/fat girths have no good direction for a footballer, and a heavier
  reading is not "better" than a lighter one. A change is only called better or worse when it also
  clears that metric's `MEANINGFUL_CHANGE` threshold.
- **Corrections to body data are applied *and shown*.** The extraction script
  keeps the printed figure in `value_original`;
  `body.data_store.applied_corrections()` surfaces the audit trail, and
  `implausible_rows()` (currently empty) catches anything flagged but not
  confirmed. Confirmed fixes live in the gitignored `data/body/corrections.json`
  (they are dated personal values), and a fix propagates to any ratio derived
  from the corrected figure.
- **Body-vs-performance is underpowered, and is analysed anyway.** Only 6 of 22
  assessments have training in the default 28-day lookback window, 2 short of
  `performance_link.MIN_PAIRS`. That threshold no longer *hides* results — it
  labels them: every row carries `n` and a `reliability` tier, and the hard
  floor is `ABSOLUTE_MIN_PAIRS` (4), where a rank correlation stops existing.
  The limit is overlap, not method: the body record starts a year before the GPS
  record, and the lookback window is a dashboard control so the reader can trade
  window precision for pair count. Everything carries FDR-corrected q-values
  across the whole grid — ~60 body metrics × 8 performance metrics is several
  hundred tests, and a few will always clear p<0.05 by chance. **A survivor
  found at low power renders amber, not green**: at a 14-day window one pair
  hits rho = −1.000 on n = 6 and clears FDR, which is what six points look like,
  not a relationship.
- **Body metrics are read off the files, not hand-listed**, and grouped into
  families (`data_store.METRIC_FAMILIES`) that drive the Body Composition tab.
  This took the selectable set from 48 to 62 — the eight individual skinfold
  sites and the raw girths were never in the hand-written list, despite being
  the measurements every fat estimate is built from.
- **`gps/position_baselines.py` replaced the old spreadsheet baseline** (a
  single unsourced set of numbers) with position-specific figures from
  published research. Training baselines are *estimated* from the match
  baseline (one flat ratio per metric, not position-specific — no study was
  found for that), and top speed isn't split by position at all (no reliable
  per-position data found) — both gaps are deliberate, not oversights. See
  [`docs/position_baselines.md`](docs/position_baselines.md) before adding a
  number here; don't add position-specific figures without a citation.

## Known bugs fixed while porting

Both were caught by testing against real data, not by inspection — see
`tests/test_fixtures.py` and `tests/test_predictor.py`.

1. **Home/away score swap** — the source notebooks read `Result` (always
   "home score-away score") as if it were "tracked-team score-opponent score",
   silently flipping the outcome of every away fixture. Fixed in `season/fixtures.py`.
2. **Double-averaging in the predictor** — the source notebook's final merge
   divided already-averaged simulation stats by `n_simulations` a second time,
   producing nonsensical predicted values (e.g. `Draws_Predicted: 965`). Fixed in
   `season/predictor.py`.

Full explanation of both, with the exact numbers, in
[`docs/season_prediction.md`](docs/season_prediction.md#known-bugs-fixed).

## What's outside this repo

The parent `StatsSports/` folder (this repo lives inside it) still has:

- **`Logos/`**, **`champions_analysys.ipynb`**, **`champions_utils.py`**,
  **`Jogos_Vitoias_Fermedo.xlsx`** — a multi-season "champions" comparison across
  years, built on a hand-formatted spreadsheet. Not part of either focus area
  above and not ported here; a reasonable future extension once there's a
  reproducible (non-hand-edited) source for multi-season historical data.
- **`_archive/`** — the original exploratory notebooks and intermediate xlsx/csv
  exports this repo's `src/football_stats` package was built from (scraping
  notebooks, `football_performance_analysis.py`, the original
  `SATS_Football_GPS_Advanced.xlsx`, etc.). Kept for reference; nothing in this
  repo depends on it.
