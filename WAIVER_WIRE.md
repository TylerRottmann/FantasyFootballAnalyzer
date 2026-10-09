# Waiver wire suggestions

Open `/waivers/` while signed in, or use **Waiver Wire** in the main navigation.
Choose an imported league in the existing header selector.

Availability is the imported player pool minus every roster entry in the active
league, including entries on other owners' rosters. Ownership percentages are not
used. The current importer supports QB, RB, WR, and TE. Availability reflects the
last import, not live waiver claims, deadlines, or platform eligibility rules.
Reconnect the league through the existing import flow to refresh its rosters.
No roster data means availability is unknown, so the page shows an import prompt.

Position, NFL team, inclusive minimum/maximum age, and name search combine.
Unknown ages remain visible unless an age bound is supplied. Invalid inputs show
validation errors. Results use 50-player pages and preserve filters across pages.

`analyzer/waivers.py` reuses `leagues.context_processors.league_selector` for
active-league authorization and fallback. It queries existing `Players`, `Teams`,
and `FantasyRosterPlayer` mappings without changing schemas or imports.

`analyzer/waiver_predictions.py` is the replacement point for real predictions.
Its adapter accepts a player and league and returns `WaiverPrediction` with
`this_week` and `rest_of_season` point values. Current values are deterministic
synthetic examples, independent of stats and league scoring, and explicitly
labeled demo values in the UI. They are not stored in the database.
Both sorts are descending, with player name and ID providing stable tie breaks.
The existing `scripts/algorithm/predictor.py` provides a single upcoming-game
estimate from recent scores and opponent data; it remains unchanged. Real weekly
and season inputs, scoring integration, and combined short/long-term value are
future work.

## Verification

Use a Python version supported by the pinned Django 5.1.5 (Python 3.10–3.13):

```powershell
python manage.py check
python manage.py test --settings=FantasyFootballAnalyzer.test_settings
```

The test settings select an isolated in-memory SQLite database. Tests create the
unmanaged tables only in that test database; no shared schema migrations are
needed. Coverage includes league switching and authorization fallback, all-roster
exclusion, combined filters, unknown ages, malformed input, missing imports,
empty results, both prediction sorts, stable ties, and pagination.

The local Python 3.14 / Django 5.1.5 combination fails in Django's test-context
copying code. The 12 tests pass on Python 3.12 with the same installed Django
code. System checks and read-only page rendering for existing imported leagues
also pass in the current local environment. Dependencies were not changed.
