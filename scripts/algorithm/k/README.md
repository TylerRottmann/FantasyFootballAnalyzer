# SCRUM-27: Kicker projection model

## Behavior and league scoring

The kicker model predicts 18 kicking stat components rather than fitting one
league's fantasy points. `predict_player` routes `K` to `predict_k` and accepts
optional `scoring_settings` for kickers. Without settings, it returns a named
reference score for training comparisons and universal projection storage.

`generate_projections` now includes kickers and stores their component stat line
in `FantasyProjection.projected_stats`. Start/sit (including historical lineups),
power rankings, and team breakdown rescore a copy of each kicker projection with
the selected league's imported settings. The saved record is not modified when
another league uses different weights. Other positions retain their existing
PPR behavior. The existing lineup optimizer supports the `K` slot.

Supported Sleeper rules include generic and distance-band field goals/misses,
50+ and 60+ bonuses, PAT makes/misses, FG yardage, and FG yards over 30. Rules
add together when the play satisfies them; absent weights contribute zero.
Blocked field goals are added to the correct missed-distance bucket, and blocked
PATs count as misses exactly once. Distance lists are checked against source
counts. Unknown nonzero kicking rules, missing kicker settings, and Yahoo's
nested stat-modifier format return `unsupported_scoring`, with no reference-score
fallback on league pages. Rare offensive plays, fumbles, and special-teams return
points by kickers are outside this kicking-only model.

Scoring references:
- https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available
- https://support.sleeper.com/en/articles/3186339-what-stacks

## Data and features

The source remains `nflreadpy.load_player_stats`, already used by the project.
The existing historical importer excludes `K`, and `player_weekly_stats` has no
FG/PAT columns. Its generic `fantasy_points_ppr` is not used as a kicker target.
`prepare_kicker_data` downloads kicking fields, maps GSIS to Sleeper to existing
database player IDs, and writes a local, ignored `kicker_weekly.json` snapshot.
It never inserts players or writes the shared database. Rebuild the snapshot for
each deployment/database and after source or ID-mapping updates. Inference reads
the local snapshot; it does not download data during a page request.

There are 110 ordered features: prior-game kicking volume, makes, misses,
distance production, and paired accuracy rates over last 1/3/8 games and the
season; plus prior team points, yards, kicking points, opponent points/yards,
opponent kicking points allowed, game count, and home/away context. Team kicking
points are actual scoreboard points, not distance-weighted fantasy points.
All performance inputs use `week < prediction_week`. Missing values stay missing.
Target-week rows identify only historical team/opponent/home context. Historical
team changes never use today's roster to fill missing history. The established
RB matchup safeguards are reused; nflverse's recorded historical team also
recovers context where the imported schedule is incomplete. Missing home/away
in such cases remains missing.

Only recorded regular-season games are used. Zero-stat games remain zero;
inactive/unrecorded games are not fabricated. First recorded games are excluded
from training and return `insufficient_history` at inference. No Week 1 or rookie
fallback is invented. A bye returns zero only with a complete 17-game current
team schedule. Other unresolved matchups return `matchup_not_found`; absent local
source seasons return `data_not_found`; missing artifacts return `model_not_found`.

Snapshot coverage measured October 21, 2026:

| Season | Source regular-season rows | Mapped rows | Training/evaluation rows |
| --- | ---: | ---: | ---: |
| 2023 | 543 | 543 | 504 |
| 2024 | 543 | 543 | 500 |
| 2025 | 543 | 534 | 494 |
| 2026 Weeks 1–6 | 186 | 168 | 138 |

Twenty-seven source rows had no mapping to an existing kicker in the database
(9 in 2025 and 18 in 2026). Those rows are excluded and reported. No usable mapped
rows had missing targets or unresolved historical matchups. Current team context
is incomplete: the shared 2026 team table has only 30 Week 1 rows. The model uses
available earlier team history and leaves absent inputs missing. Existing schedule
imports also omit Rams games; historical source teams recover recorded kicker
games, but unresolved upcoming schedules still require the imports owner to fix
the LA/LAR alias and refresh schedules. No player or team source rows were imported for this ticket. Shared database
structure updates are recorded below.

## Model and measured results

Each component uses a deterministic histogram gradient-boosting regressor
(150 iterations, learning rate 0.05, 7 leaves, L2=1, seed 42). Predictions are
nonnegative fractional expected stats, not rounded event counts. The final model
uses 2023–2025. Feature/target order and training-season metadata are saved and
checked on load. The evaluation model trained on 2023–2024 is never saved over
the final artifact. Hyperparameters were not selected by holdout performance.

Reference scoring is 3 points for FG under 40 yards, 4 for 40–49, 5 for 50+,
1 for PAT made, and -1 per missed FG/PAT (including blocked attempts). These
results do not represent every league's scoring settings.

| Evaluation | Games | Model MAE | Last-three MAE | Model RMSE | Last-three RMSE | Model within 3 | Last-three within 3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025 held out, trained on 2023–2024 | 494 | 4.01 | 4.38 | 5.01 | 5.52 | 44.33% | 44.94% |
| 2026 Weeks 2–6, saved 2023–2025 model | 138 | 4.28 | 4.78 | 5.28 | 5.94 | 37.68% | 42.75% |

The model improves MAE and RMSE in these samples, but has a lower within-three-point
rate than the baseline. Current-season results are provisional. Comparisons use
the same eligible rows for model and baseline; no top-player selection is applied.
Detailed bias and error-threshold metrics, versions, coverage, and source checksum
are in `k_model_metrics.json` and `k_backtest_2026.json`.

## Setup, migration, and reproduction

Run from the repository root, keeping `.env` private:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OMP_NUM_THREADS = '2'
$env:PGOPTIONS = '-c default_transaction_read_only=on'
.\.venv\Scripts\python.exe -m scripts.imports.prepare_kicker_data --seasons 2023 2024 2025 2026
.\.venv\Scripts\python.exe -m scripts.algorithm.k.train_k_model --projection-season 2026
.\.venv\Scripts\python.exe -m scripts.algorithm.k.backtest_k_model --season 2026 --output scripts/algorithm/k/k_backtest_2026.json
.\.venv\Scripts\python.exe -m scripts.algorithm.backtest --positions K --seasons 2026
.\.venv\Scripts\python.exe -m unittest scripts.tests.test_k_algorithm scripts.tests.test_rb_algorithm scripts.tests.test_dst_algorithm -q
.\.venv\Scripts\python.exe manage.py test scripts.tests.test_k_start_sit scripts.tests.test_rb_start_sit --settings=scripts.tests.rb_test_settings
.\.venv\Scripts\python.exe manage.py check
git diff --check
```

The configured shared database was updated on October 21, 2026 through
`leagues.0010_kicker_stats_database_default`:

- `0008` adds `FantasyProjection.projected_stats` for kicking stat components.
- `0009` creates the missing `TeamWeekProjection` table already expected by dev.
  It also corrects an existing migration-state mismatch: 0004 and 0005 recorded
  two differently defined constraints under the same name. The repair resets
  only migration state to the existing, correct four-column uniqueness rule.
  It does not drop or recreate that live database constraint.
- `0010` supplies an empty JSON value at the database level for older clients
  that omit the new field, so teammates running older code can keep saving
  predictions. The model retains its normal application default as well.

The first two updates were applied in a single transaction, with a before/after
checksum of every existing prediction's original fields. All 59,678 predictions
were preserved, including IDs, scores, statuses, and timestamps. The original
uniqueness constraint retained its exact identity and definition. The new team
projection table is empty. The compatibility default was applied and verified
with an older-style insert whose temporary test row was rolled back; all 59,678
predictions remained unchanged. No source-stat imports or forecast generation
were performed during the schema repair.

The same shared database already records these updates as applied. For another
configured database, review its normal pending updates and run the migration
chain through `0010` before using this code. Migration and projection-generation
commands need a normal write-enabled session; the reproduction session above is
read-only. Source snapshots remain local to each installation and must be prepared
before kicker inference. Nothing has been pushed or opened as a pull request.

`makemigrations --check --dry-run` now reports no changes, and `migrate --plan`
reports no pending operations. Three additional regression tests reproduce the
old state mismatch, apply the repair in an isolated database, verify the original
predictions and uniqueness rule survive, and check older-style inserts receive
the empty database default. These tests never use the configured shared database.

Validation: 41 focused kicker/RB/defense algorithm tests and 14 isolated
generation/page tests pass. Tests cover temporal leakage, zero targets, paired
rates, complete-schedule byes, blocked/distance scoring, unsupported settings,
model persistence/schema guards, chronological evaluation, router integration,
saved stat persistence, league-specific rescoring without mutation, lineup use,
rankings, team breakdown, and details responses. The details panel labels kicker
allowed points as scoreboard kicking points rather than PPR. Page tests use a temporary SQLite schema and real saved
models with deterministic historical fixtures; they do not validate the shared
PostgreSQL migration history. The existing RB test was updated to recognize the
teammate's already-implemented TE router.

Python 3.14.0, NumPy 2.5.3, scikit-learn 1.9.1, and joblib 1.6.0 were used for the
artifact. `.venv` now has the pinned requirements and `django-extensions==4.1`.
Django system checks and dependency consistency checks pass. No push, pull request,
merge, or source-data import was performed. The authorized shared schema updates
are described above.

## Live browser verification, October 21, 2026

Signed-in browser checks used the existing league and actual shared data, rather
than test fixtures. The start/sit page originally crashed when a saved defense
projection tried to build a player-details URL with no player ID. Starter and
bench defenses now display their scores without those invalid links. A regression
covers defenses in both current and optimized lineups.

The lineup optimizer also left eligible zero-point players out because an empty
slot tied their score. It now maximizes filled eligible slots first, then projected
points. This also keeps a valid kicker in a required slot when custom penalties
produce a negative projection. Four regression tests cover zero/negative scores,
complete-lineup selection, and genuinely missing positions.

Kickers now appear in both starter/bench ranking chart choices and the team
breakdown position filter. The player grouping includes K, so selecting that
filter displays the kicker instead of hiding it. Browser checks cover prediction
points and the loaded historical-details panel, switching weeks, ranking charts,
and team breakdown tabs. ADP player/position filtering and the waiver page also
load. Weekly Rankings remains a placeholder link; waiver predictions remain
explicit demo values, and ADP's unfiltered page is large (9,357 rows). These existing
features were not redesigned as part of the kicker ticket. Missing Rams schedule
data and unsupported Yahoo kicking settings remain the documented limitations.

Available 2026 kicker forecasts were saved for Weeks 1–18 using a shared source
snapshot and model: 454 model projections, 21 confirmed-bye zeros, and 2,070
inactive zeros following the existing generation convention. There were 178
insufficient-history cases and 49 unresolved matchups; no scores were invented
for those cases. All 59,678 non-kicker projections were verified unchanged. This
was forecast generation, not an import of new source-stat rows.

The existing generation command now accepts a position filter, preserving its
previous all-position default:

```powershell
.\.venv\Scripts\python.exe manage.py generate_projections --season 2026 --week 7 --positions K
.\.venv\Scripts\python.exe manage.py generate_projections --season 2026 --all-weeks --positions K
```

Run these writes in a normal deployment session, not the read-only evaluation
session above. Batch callers of `predict_k` can reuse the same data snapshot and
loaded model without changing the prediction logic. A generation regression
confirms the K-only command leaves other positions and defenses untouched.

Final focused validation includes 48 algorithm/schema/lineup tests and 14 isolated
page/persistence tests (62 total). Screenshots were saved separately for review.
Additional frontend fixes remain local until the feature branch is pushed again.
