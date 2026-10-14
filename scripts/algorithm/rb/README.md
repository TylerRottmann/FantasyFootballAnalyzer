# SCRUM-23: Running Back Projection Algorithm

The RB predictor now returns weekly PPR projections through the existing `predict_player` entry point. The final `rb_model.pkl` was trained on 3,150 eligible games from 2023, 2024, and 2025 for the 2026 projection season. This follows the QB/WR gradient-boosting model configuration and position predictor response format.

## Implementation

- `feature_names.py` defines one ordered list of 153 numeric features for training and inference.
- `../features/rb_features.py` reads player production, team totals, historical matchups, and schedules. It builds rolling windows over the last 1, 3, 5, and 8 recorded games and the current season.
- `rb_model.py` creates, trains, saves, and loads the model. The artifact records its feature order, training seasons, and PPR scoring. Loading rejects a changed feature order.
- `rb_predictor.py` builds model inputs and returns the existing player, position, season, week, projection, status, and feature fields.
- `train_rb_model.py` selects the three completed seasons before `--projection-season`, evaluates the most recent season using a separate model trained on the preceding two, then trains the saved model on all three seasons. Training requires usable data from each season and rejects entirely empty features.
- `backtest_rb_model.py` compares the saved model with the last-three-game average on a season after its training window. It rejects attempts to present training seasons as held-out results.
- `../predictor.py` adds the RB import and routing entry. QB, WR, and the TE placeholder retain their existing behavior.
- `../backtest.py` adds optional position and season filters and labels saved-model replay results. Existing default positions and seasons are preserved.
- `../../tests/test_rb_algorithm.py` covers leakage boundaries, feature order, null handling, workload calculations, matchup recovery, byes, response statuses, routing, model serialization, and evaluation boundaries.

## Verified source mappings

RBs are identified using `players.position = 'RB'`. Rushing production uses `player_weekly_stats.carries`, `rushing_yards`, and `rushing_tds`. Receiving production uses `targets`, `receptions`, `receiving_yards`, and `receiving_tds`. The target is `fantasy_points_ppr`; lost fumbles use `fumbles_lost`. Each of these columns was populated in the inspected RB data.

Touches are carries plus receptions. Opportunities are carries plus targets. Carry share and target share divide player workload by the corresponding sums for all mapped players facing the same opponent in that week and season. This matches the WR target-share mapping, including its limitation: players absent from the imported weekly table can make team totals incomplete. Rate calculations retain paired numerator and denominator observations; zero denominators remain missing.

Team features use `team_weekly_stats.points_for`, `passing_yards`, `rushing_yards`, and `total_yards`. Opponent features use `rb_fantasy_points_allowed`, `rushing_yards_against`, `passing_yards_against`, `points_against`, and `total_yards_against`. Player regular-season rows use `season_type = 'REG'`; team rows use `season_type = 1`; schedule rows use `game_type = 'REG'`.

All performance features use rows with `week < prediction_week`. Target-week rows are used only to identify historical team, opponent, and home/away context. The feature builder normalizes nflverse `LA` to the database's `LAR`. Historical matchups use the team weekly row, then the opponent's scheduled matchup, then a validated imported game ID of the form `season_week_away_home`. Historical lookup failure never substitutes the player's current team.

For upcoming games in the current season, the predictor uses the player's current team and imported schedule. It returns zero only for a bye established by a complete 17-game team schedule. An unresolved matchup returns `matchup_not_found`. Missing artifacts return `model_not_found`. With no earlier recorded games in that season, it returns `insufficient_history`; no Week 1 or rookie fallback is fabricated.

## Training coverage

| Season | Recorded RB games | First recorded games excluded | Training games |
| --- | ---: | ---: | ---: |
| 2023 | 874 | 74 | 800 |
| 2024 | 1,140 | 93 | 1,047 |
| 2025 | 1,426 | 123 | 1,303 |
| Total | 3,440 | 290 | 3,150 |

There were no missing PPR targets or unresolved historical matchups in the three training seasons. Recorded zero-point games are retained. Unrecorded inactive games are not synthesized. Coverage depends on the players and ID mappings present in the shared database, rather than every NFL roster historically.

## Measured performance

Measured against the configured database on October 13, 2026. Lower MAE and RMSE are better. The baseline uses the same test rows as the model.

| Evaluation | Games | Model MAE | Baseline MAE | Model RMSE | Baseline RMSE | Model within 3 points | Baseline within 3 points |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025 held out, trained on 2023–2024 | 1,303 | 4.99 | 4.83 | 6.83 | 7.12 | 42.44% | 49.19% |
| Available 2026 Weeks 2–4, saved 2023–2025 model | 248 | 4.89 | 4.83 | 6.60 | 6.89 | 40.73% | 46.37% |

The model does not beat the last-three-game baseline on MAE or the within-three-point rate in either evaluation. It has lower RMSE in these samples. These results support a working projection pipeline, not a claim of superior prediction accuracy. The holdout was not used to tune model parameters.

The final model's training-set MAE is 2.71 across 3,150 rows. This is an optimistic in-sample fit and is not an estimate of future accuracy. Detailed metrics, including bias and 2/3/5/7-point thresholds, are recorded in `rb_model_metrics.json` and `rb_backtest_2026.json`.

The shared backtest was also run for RBs in 2026: 87 predictions from the existing top-30 selection, MAE 7.25, and 20.69% within three points. This is a different population from the all-eligible-RB evaluation. The existing shared script selects top players using the season's recorded totals, so that retrospective selection should not be treated as an unbiased prospective sample.

## Current data limits and coordination

The shared 2026 player table contains 365 recorded RB games through Week 4. The backtest excludes 117 first recorded games with no earlier player history and evaluates the remaining 248; all their matchups resolve with the validated historical fallback.

The shared 2026 team table contains 30 rows, all in Week 1. Later matchup features therefore use only the available earlier team rows; unavailable histories remain missing and are handled by the gradient-boosting model. The 2026 backtest is provisional and covers only available Weeks 2–4.

The schedule contains 255 games and no Rams games. The schedule importer uses raw `LA` abbreviations against a teams table containing `LAR`, skipping all 17 Rams games. RB inference now avoids false byes for teams with incomplete schedules, but unresolved upcoming matchups still need corrected schedule data. The imports owner should correct this alias and refresh the schedule and team histories. SCRUM-23 does not modify shared database contents or import scripts.

The TE teammate should retain both routing entries when merging changes to `scripts/algorithm/predictor.py`. The shared backtest changes add filters while preserving default behavior; an incoming TE change should retain those arguments if it touches `main`.

## Reproduce

Run from the repository root with its existing environment and database configuration. Python 3.14.7, scikit-learn 1.9.1, NumPy 2.5.3, and joblib 1.6.0 were used for the saved artifact. Keep training and inference dependencies compatible with the artifact.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:PGOPTIONS = '-c default_transaction_read_only=on'
.venv/Scripts/python.exe -m unittest scripts.tests.test_rb_algorithm -v
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe -m scripts.algorithm.rb.train_rb_model --projection-season 2026
.venv/Scripts/python.exe -m scripts.algorithm.rb.backtest_rb_model --season 2026 --output scripts/algorithm/rb/rb_backtest_2026.json
.venv/Scripts/python.exe -m scripts.algorithm.backtest --positions RB --seasons 2026
git diff --check
```

Seventeen focused tests passed, Django's system check reported no issues, and both RB backtest paths completed. Database inspection, training, and evaluation used read-only database sessions. Credentials were not printed. The existing ticket branch matched freshly fetched `origin/dev` before implementation, and no existing local changes were present. No push, pull request, or merge was performed.

## Start/sit integration verification, October 14, 2026

The page displays `FantasyProjection` rows for the league's season, selected week, and model version `v1`. The existing `generate_projections` command calls `predict_player`, persists the projected points and status, and supplies the records used by the current and optimized lineups. Opening the page does not generate missing projections.

The RB projection details endpoint now uses `build_rb_features`, including historical matchup recovery and RB workload shares. The TE details branch retains its previous behavior. This corrects the older generic RB details path, which could disagree with the model's historical team and opponent inputs.

Seven additional tests exercise the actual saved RB model, feature calculations, shared router, generation command, isolated database persistence, page template rendering, current and historical lineup optimization, details response, and roster access checks. The historical source snapshot and Sleeper response use deterministic fixtures. The model and generation, storage, page, and optimizer code run normally. The temporary SQLite database builds current model tables instead of testing the existing PostgreSQL migration history. Test-only flattened context capture works around Django 5.1's context-copy failure on Python 3.14 while preserving actual template rendering.

```powershell
$env:OMP_NUM_THREADS = '2'
.venv/Scripts/python.exe manage.py test scripts.tests.test_rb_start_sit scripts.tests.test_rb_algorithm --settings=scripts.tests.rb_test_settings -v 1
```

All 24 tests passed in the project's existing Python 3.14.7 / Django 5.1.5 environment. Django's system check and the diff whitespace check also passed. The seven integration tests separately passed with temporary Django 5.2.18; installed project dependencies were not changed.

A separate read-only request using an existing connected roster and five real-data RB model predictions rendered the actual start/sit page with HTTP 200 and the expected projected values. These projection records were supplied in memory for that verification request, so the shared database was not modified. This verifies server-rendered values, not a browser click-through or a shared-database refresh.

At inspection, the shared database held 474 RB projection rows, all marked `inactive` for 2026 Week 6; no active RB `ml_model` projections had been persisted. The team must regenerate projections for the desired season and week before verifying the live page with saved RB results. The existing generation command processes all supported positions and updates shared projection rows, so coordinate that run with the data owner. The schedule and team-history limitations above still apply.

These follow-up integration changes are local until committed and pushed to the existing SCRUM-23 pull request. The original implementation was published as commit `04196b2` in PR #30 targeting `dev`.
