"""Index season-wide reads as well as existing player/team-specific lookups."""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [('analyzer', '0011_rename_sleeper_rank_position')]

    operations = [
        # Django skips database operations for unmanaged models. These legacy
        # tables exist in PostgreSQL, so explicitly create their indexes while
        # keeping the migration state consistent with model metadata.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    'CREATE INDEX CONCURRENTLY pws_season_type_week_idx '
                    'ON player_weekly_stats (season, season_type, week)',
                    'DROP INDEX CONCURRENTLY pws_season_type_week_idx',
                ),
                migrations.RunSQL(
                    'CREATE INDEX CONCURRENTLY tws_season_type_week_idx '
                    'ON team_weekly_stats (season, season_type, week)',
                    'DROP INDEX CONCURRENTLY tws_season_type_week_idx',
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name='playerweeklystats',
                    index=models.Index(fields=['season', 'season_type', 'week'], name='pws_season_type_week_idx'),
                ),
                migrations.AddIndex(
                    model_name='teamweeklystats',
                    index=models.Index(fields=['season', 'season_type', 'week'], name='tws_season_type_week_idx'),
                ),
            ],
        ),
        AddIndexConcurrently(
            model_name='playerinjuryreport',
            index=models.Index(fields=['season', 'week'], name='injury_season_week_idx'),
        ),
        AddIndexConcurrently(
            model_name='playersnapcount',
            index=models.Index(fields=['season', 'week'], name='snaps_season_week_idx'),
        ),
    ]
