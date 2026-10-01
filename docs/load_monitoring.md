# Load monitoring: ACWR, Training Monotony & Strain

`src/football_stats/gps/load_monitoring.py`, surfaced in the GPS dashboard's
**Performance Insights** tab under "Load monitoring". None of this is
SkillCorner methodology (see `docs/skillcorner_metrics.md` for what is) — this
is the general sports-science literature on injury-risk/overtraining
monitoring, which happens to be exactly what session-level GPS load data is
built for.

## The load-proxy substitution — read this first

Every metric here needs one number per session representing "how much work
was done." The field's standard input is **session-RPE** (Rating of Perceived
Exertion, a 1-10 subjective-effort scale the player reports after a session,
multiplied by duration in minutes). This repo's schema **doesn't collect
RPE** — there's no subjective-exertion field — so `total_distance_m` is used
as the load proxy instead, for both ACWR and Monotony/Strain.

This is a real substitution, not a detail to gloss over: distance and
session-RPE correlate but aren't the same thing (RPE also captures perceived
fatigue, psychological load, heat, opponent quality, etc. that pure distance
can't). If an RPE field is ever added to the GPS session schema, these
functions should switch `load_col` to it — they already accept any numeric
column via the `load_col` parameter, so the change is a call-site one, not a
rewrite.

## ACWR — Acute:Chronic Workload Ratio

Gabbett, T.J. (2016). *The training–injury prevention paradox: should
athletes be training smarter and harder?* British Journal of Sports
Medicine, 50(5), 273–280.

**The report uses the weekly form** — `weekly_acwr()`: this Sunday–Saturday
week's load ÷ mean of the previous 4 weeks (uncoupled: the acute week is not
inside its own baseline), summed over every session type. EWMA variant
(Williams et al. 2017, spans 7/28 days) selectable. No ratio for the first 4
weeks of a season, when chronic load is 0, or for a partial final week. Full
definition: [`gps_report.md` §8](gps_report.md#8-weekly-load-and-acwr-gpsload_monitoringpy).

`compute_acwr()` is the daily equivalent (last 7 days ÷ the average 7-day block
over the 28 days *before* them), NaN until that full history exists. It used to
start on day 1 with a coupled chronic window, producing ratios like 0.14 → 1.0
over the first week that measured nothing but the missing history.

| ACWR | Zone (`gps/config.py: ACWR_SAFE_BAND`) |
|---|---|
| `< 0.8` | Below range |
| `0.8 – 1.5` | Within range |
| `> 1.5` | Above range |

The earlier four-zone scheme (0.8–1.3 "optimal", 1.3–1.5 "elevated risk") was
replaced by the single 0.8–1.5 band from Ravé et al. (2020). **ACWR is a
monitoring indicator, not an injury predictor.**

Monotony and strain now use the same Sunday–Saturday weeks as ACWR.

## Training Monotony & Strain

Foster, C. (1998). *Monitoring training in athletes with reference to
overtraining syndrome.* Medicine & Science in Sports & Exercise, 30(7),
1164–1168.

`weekly_monotony_and_strain()` returns one row per calendar week:

- **Monotony** = mean daily load ÷ standard deviation of daily load, over
  that week. High monotony means load barely varies day to day — no
  built-in easier days. Uses sample standard deviation (`ddof=1`, pandas'
  default and the common spreadsheet/coaching-tool convention) — a week
  with only one session has an undefined SD and gets `NaN`, not a
  divide-by-zero artifact or a fake zero.
- **Strain** = weekly total load × monotony. Foster's flag for "a big week
  that was *also* monotonous" — the combination linked to overtraining risk
  more than either figure alone.

**On thresholds**: `MONOTONY_CAUTION_LEVEL = 2.0` is a commonly cited caution
point *when combined with a high weekly load* — not a validated, universal
"danger zone" boundary, and it's presented as such (`classify_monotony()`'s
"High" zone is a prompt to look closer, not an alarm). **Strain has no
standard absolute scale at all** — the literature treats it as relative to an
athlete's own history, which is why `gauges.strain_gauge()` scales to that
athlete's own median week instead of fixed colored risk zones.

## Sources

- Gabbett, T.J. (2016). *Br J Sports Med*, 50(5), 273–280.
- Foster, C. (1998). *Med Sci Sports Exerc*, 30(7), 1164–1168.
- [Session-RPE Method for Training Load Monitoring](https://pmc.ncbi.nlm.nih.gov/articles/PMC5673663/) — on why session-RPE, not distance, is the field's standard load input.
- [A Novel Approach to Training Monotony and Acute-Chronic Workload Index: A Comparative Study in Soccer](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2021.661200/full)
- [Training Monotony and Strain: What the Science Says and How Coaches Can Use It](https://fractall.fit/blog/training-monotony-strain-football-load-monitoring) — source for the "~2.0 caution, not a hard rule" framing and the "pattern indicator, not automatic injury prediction" caveat carried into `classify_monotony()`.
