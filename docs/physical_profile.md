# Physical profile: fatigue, mechanical load and speed exposure

Module: [`src/football_stats/gps/fatigue.py`](../src/football_stats/gps/fatigue.py) ·
Tests: [`tests/test_fatigue.py`](../tests/test_fatigue.py) ·
Dashboard: **Physical Profile** tab

Every other analysis in this repo is built on `total_distance_m`. That measures
one kind of cost — how much running was done — and is blind to three others.
This doc covers those three, and puts to work columns the schema had been
parsing and then never reading: `sprints_1st_half`, `sprints_2nd_half`, and
`accelerations`/`decelerations` as an independent load axis rather than a
per-90 rate.

---

## 1. Second-half sprint retention

Second-half sprint count ÷ first-half sprint count. 1.00 means output held;
0.50 means it halved after the break.

### The exclusion that makes it a fatigue metric

The naive version of this is wrong, and wrong in a way that looks like a
finding. Three matches in the current data show **18–25 first-half sprints
followed by zero in the second**. Read at face value that is total collapse. All
three are 45-minute appearances: the player was substituted at half time. He
didn't fade, he left.

`second_half_retention` therefore requires `SECOND_HALF_MIN_MINUTES` (50) of
playing time, taken from the **match sheet** where recorded — the GPS unit's
runtime includes the warm-down and would let a 45-minute appearance through as
56 minutes. Including those three matches drags the median from 0.55 to 0.45,
which is the difference between "fades in the second half" and "collapses".

### What it shows

| Category | Matches | Median | Range |
| --- | --- | --- | --- |
| Official match | 6 | **0.50** | 0.23 – 0.56 |
| Practice match | 4 | **0.90** | 0.77 – 1.17 |

Sprint output roughly halves after half time in competitive matches, and holds
in friendlies. That is a real and interpretable split — opponent quality, tempo
and the consequences of easing off all differ — but it is 6 matches against 4.
Read it as the shape of this season, not as a fitness verdict.

Median rather than mean, with the range shown beside it, for the usual reason:
one cameo ratio would move a mean, and a single figure invites being read as a
level.

---

## 2. Mechanical load

`mechanical_load` = accelerations + decelerations: a count of speed *changes*.

Distance is a **metabolic** proxy. Speed changes are the **mechanical** one, and
they are what damages muscle. Two sessions can cover identical distance while
one involves twice the braking, and every load metric on the Performance
Insights tab — ACWR, monotony, strain, all computed on `total_distance_m` —
would call them the same session.

Three derived columns:

- `mechanical_load` — the raw count. Missing, not zero, when neither count was
  recorded.
- `mechanical_load_per_min` — comparable across session lengths.
- `accel_decel_ratio` — accelerations ÷ decelerations.

### The accel:decel ratio

`BALANCED_ACCEL_DECEL` is 0.8–1.25. Below it, braking outpaces accelerating;
decelerating is the eccentric, more damaging half of the pair.

**Current median: 0.78 across 128 sessions — deceleration-dominant**, just below
the band. That is a consistent profile rather than a one-off.

The band is a reasonable symmetry interval, **not** a validated threshold from
the literature, and the device's own thresholds decide what counts as an
acceleration in the first place. Treat it as a prompt to check soreness, not as
a diagnosis.

### ACWR on the mechanical axis

`compute_acwr` already accepted a `load_col`, so the mechanical ACWR is the same
Gabbett ratio computed on speed-change counts. It is plotted **against** the
distance-based one because the point is that they disagree: distance load can
sit comfortably inside the optimal band while mechanical load spikes, which is
exactly the overload a distance-only monitor cannot see.

Both are plotted **over time** rather than as a single gauge — a ratio of 1.35
arrived at from 0.9 means something entirely different from one falling from
1.8, and a gauge shows neither.

---

## 3. High-speed exposure

Share of each month's sessions that reached `NEAR_MAX_SPEED_PCT` (90%) of the
reference top speed.

A **share, not a count**: a month with 18 sessions should not look better than
one with 8 for being busier. The reference is the player's own best in the
current scope, because no external benchmark exists for amateur football.

Regular near-maximal sprinting is a widely used hamstring-injury prevention
target. The notable figure in the current data is **January 2026: 0 of 17
sessions** reached 90% of best — a full month with no near-max exposure, sitting
between months that ran 20–33%.

---

## 4. Training-to-match intensity gap

Training's high-speed and sprint share of total distance, as a percentage of the
same share in that month's official matches. 100% means training reaches match
intensity.

Uses intensity **shares** rather than absolute distances, so a shorter session
isn't penalised for being shorter. Months without both a training session and an
official match are dropped rather than compared against nothing.

Current range: high-speed **54–75%**, sprint **15–60%**, with the sprint gap
falling through April and May. Training gets closer to match intensity on
high-speed running than on sprinting, and the sprinting gap widens as the season
runs out.

---

## What none of this establishes

These are descriptive metrics over one player and one season. A retention of
0.50 does not diagnose a conditioning deficit; a deceleration-dominant ratio
does not predict an injury; a month without near-max exposure is a fact about
that month's sessions, not a risk score. Each is a prompt to look at something —
which is what a dashboard is for — and none is a finding.
