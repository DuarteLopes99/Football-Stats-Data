# GPS Dashboard Redesign — Brief for Claude Code

## 0. Who I am and what this is

I'm Duarte, a data scientist and an amateur senior footballer. This repo (`Football-Stats-Data`) has a dashboard in the `statssports/` folder. It is built on **my own GPS data** from matches and training sessions in the 2025/26 season. The data was exported from Excel and converted to CSV. The dashboard is for personal analysis: I want to understand my load, my match demands and my week-to-week progression.

Your job has two parts:
1. **Fix** whatever is broken in the current dashboard (bugs, wrong calculations, fragile code).
2. **Redesign the visuals** so the dashboard looks and reads like the professional GPS dashboards used by clubs and shared online (Power BI / sports-science style reports).

The visual part may need significant changes, such as new chart types, a new layout and a new colour system, to match those references. That is expected and allowed. Keep the **project structure** (folders, entry point, file naming) unless a change is clearly justified. Explain any such change before you make it.

---

## 1. Ground rules

- Work on a new branch: `dashboard-redesign`. **Do not push** and do not merge into `main`. I'll review the diff and commit.
- **Never modify the raw data files.** All cleaning and derivation happens in code.
- This is personal data. Don't send it to any external service or API, and don't add telemetry.
- Keep the existing stack (language, framework, chart library) if it can produce the target visuals. If it clearly can't (for example, no heatmap tables or gauges), propose the smallest change that fixes that and wait for my OK.
- Put every threshold, colour and column mapping in **one config file or module**. Nothing hardcoded inside chart code.
- Don't invent metrics the data doesn't support. If something in this brief needs a column I don't have, skip it, and list it under "not possible with current data" in your final summary.

---

## 2. Phase 1 — Discovery (do this first, then STOP and show me the plan)

1. Read every file in `statssports/` and any shared utilities it imports.
2. Identify the stack, the entry point and how to run it. Run it.
3. Load the CSV(s) and print the following:
   - all column names, dtypes, and the number of rows
   - the date range
   - how sessions are labelled (match vs training) and whether a match-day label exists
   - units (metres or km, km/h or m/s, minutes or hh:mm:ss) and any obvious data issues: decimal commas, Portuguese date formats, duplicates, empty rows, totals rows from the Excel export
4. Map my columns to the metric list in section 3, and show the mapping as a table.
5. Audit the current dashboard and list:
   - bugs and runtime errors
   - wrong or misleading calculations (e.g. averages that should be sums, % change on the wrong baseline, mixing matches with training)
   - code issues (duplication, hardcoded paths, magic numbers)
6. Give me a **numbered plan** covering data fixes, new derived metrics, the new layout, and the files you'll touch. **Wait for my approval before editing.**

---

## 3. Metrics and calculations

These are based on two articles I'm using as references:
- Ravé et al. (2020), *How to Use GPS Data to Monitor Training Load in the "Real World" of Elite Soccer*, Frontiers in Physiology 11:944.
- Reinhardt et al. (2019), *Enhanced sprint performance analysis in soccer: New insights from a GPS-based tracking system*, PLoS ONE.

### 3.1 Core GPS parameters (use whatever subset exists in my data)

| Metric | Definition / default threshold | Notes |
|---|---|---|
| Total Distance | metres | volume |
| HSR | distance at 19.8–25.2 km/h | if the export's HSR band differs, use the export's band and document it in config |
| Sprint distance (SPR) | distance ≥ 25.2 km/h | same rule as above |
| HSR + Sprint | HSR + SPR | used in the weekly change table |
| Max Speed | km/h | intensity / exposure to near-max speed |
| Accelerations | count ≥ +3 m/s² | some literature prefers ±2 m/s²; make it configurable |
| Decelerations | count ≤ −3 m/s² | |
| High-Intensity Actions | Acc + Dec (+ sprints, if a sprint count exists) | |
| Distance per minute | Total Distance / duration (m/min) | intensity |
| Training Load | if the export has a load metric (e.g. Dynamic Stress Load, HML, Player Load), use it; otherwise leave it out | don't invent one |

### 3.2 Match reference (Gref)
- For each metric, **Gref = mean of my 5 best values in official matches**. If I have fewer than 5 matches, use all of them, and show a warning in the UI.
- All "% of match demand" visuals use Gref as their baseline.

### 3.3 Match-day labels
- Label every session relative to the nearest match: `MD`, `MD+1`, `MD+2`, …, `MD-1`.
- Week convention (from Ravé): a microcycle **starts on match day and ends on MD-1**.
- If my data already has a session type or MD column, use it. Otherwise derive it from the dates of match sessions, and make the logic easy to check.

### 3.4 Weekly load and ACWR
- Weekly load = sum of each metric over the microcycle (or the calendar week, if microcycles can't be derived; state which you use).
- **Week-over-week % change.** The reference guideline is that increases of about 10% per week keep load progression safe.
- **ACWR = acute (current week) / chronic (rolling mean of the previous 4 weeks).** Add an EWMA version as an option in config.
  - Show 0.8–1.5 as the "safe" band. Values below 0.8 or above 1.5 are flagged.
  - Add a small caption in the UI: *"ACWR is a monitoring indicator, not an injury predictor."* The article itself notes this limitation.
- Don't compute ACWR until 4 full weeks of data exist. Show "insufficient history" instead.

### 3.5 Sprint profile (only if the data supports it)
- Track max speed over time, sprint count and sprint distance, and season top speed.
- Only if per-second velocity data exists: time to reach 20 / 25 km/h, and average acceleration in the 5–20 and 20–25 km/h bands (Reinhardt et al.). Otherwise skip this and say so.

---

## 4. Visual redesign — mirror professional GPS dashboards

### 4.1 Primary visual reference
The file `docs/references/weekly_change_gps_report.webp` (I'll add it to the repo) is a **"Weekly Change % GPS Report"**, the standard Power BI style used by club sports scientists. Mirror its look:

- **Black background**, white text, **turquoise / teal accent** (around `#3ADBC8`) for section headers and card borders.
- A large centred title at the top.
- **Left sidebar:** player block (name, position, season), then a **date range filter**: two date inputs plus a range slider.
- **Main block — "Weekly Change %" table:**
  - one row per session/date and one column per metric: Total Distance, HSR & Sprint, Max Speed, High-Intensity Actions, Training Load
  - each cell shows a % value, with the background coloured on a **green → yellow → orange → red** heatmap
  - the header bar is filled with the accent colour, with dark bold text; column headings are plain white
- **Below the table: one KPI card per metric**, in a row. Each card has a header bar in the accent colour and:
  - a **semi-circular gauge** (blue fill on a light-grey track) with the period value in the centre and the min/max labels under the ends
  - **Max Speed shown as a big plain number** instead of a gauge
- Rounded card corners, thin accent borders, generous spacing, no gridline clutter.

### 4.2 Other patterns common in online GPS dashboards
Use these for the extra sections:
- **% of match demand bars:** each session (or the MD-day average) as a % of Gref per metric, with a 100% reference line.
- **Weekly load + ACWR:** weekly totals as bars, ACWR as a line on a secondary axis, and the 0.8–1.5 band shaded.
- **Microcycle profile:** load per MD label (MD+1 … MD-1), which shows how the week is shaped around the match.
- **Session detail table:** sortable, with the match/training type tagged, and conditional formatting against Gref.
- **Speed / sprint trend:** max speed per session, with the season best as a dashed line.

### 4.3 Proposed page layout
1. **Header and global filters:** date range, session type (All / Matches / Training), metric selector where relevant.
2. **Weekly Change % table + KPI cards** (section 4.1), the hero section.
3. **Load and ACWR** chart.
4. **% of match demand** and **microcycle profile**, side by side.
5. **Sprint / speed** section.
6. **Session detail** table.

Every section must react to the global filters.

### 4.4 Colour logic (keep it all in config)
- Weekly change heatmap, based on the absolute % change:
  - ≤ 10% → green
  - 10–20% → yellow/amber
  - 20–30% → orange
  - > 30% → red

  Make the scale continuous (interpolated) if the library allows it.
- Gauges: blue fill. The max of the gauge range is `max(2 × Gref, value)`, with a small marker at Gref.
- ACWR: green band 0.8–1.5, red points outside it.
- Matches vs training: use one consistent pair of colours everywhere they're distinguished.
- Readable in the dark theme: minimum contrast, no red/green-only meaning. Always show the number in the cell too.

### 4.5 "% change" definition (be explicit in the UI)
- Default: **vs the same MD label in the previous microcycle**. If that doesn't exist, fall back to **vs the previous session of the same type** and mark the cell with a small dot or tooltip.
- Put a toggle in config (and in the UI, if easy) for **vs Gref** mode.
- Never compare a match with a training session.

---

## 5. Code quality

- Separate the code into: data loading/cleaning → derived metrics → chart builders → layout.
- One `config` module or file for: column mapping, units, thresholds (speed bands, acc/dec, ACWR band, heatmap cut-offs, Gref top-N), colours and fonts.
- Use relative paths. The dashboard must run from a fresh clone with a single documented command.
- Pin or add any new dependencies in the existing requirements file.
- Add short docstrings to the calculation functions (Gref, MD labelling, ACWR, % change).
- Update or add a README section on how to run it, what each section shows, and the definitions and thresholds used.

---

## 6. Validation before you hand back

- Recompute 2 sessions and 1 week by hand (pandas in a scratch script) and confirm that the dashboard shows the same numbers.
- Check the edge cases: weeks without a match, double-match weeks, sessions with missing metrics, fewer than 5 matches for Gref, fewer than 4 weeks for ACWR.
- Run the dashboard, with no errors or warnings in the console. Take screenshots of each section if you can.

---

## 7. What I want back

1. The branch `dashboard-redesign` with the changes (not pushed).
2. A summary **file by file**: what changed and why.
3. The list of **bugs found and how each was fixed**.
4. The list of **assumptions** (column mapping, thresholds, MD logic) and anything **not possible with my current data**.
5. Screenshots, if you could take them.
