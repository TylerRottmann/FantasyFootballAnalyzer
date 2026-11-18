"""The existing partial unique indexes cannot serve roster-only reads."""

from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [('leagues', '0014_merge_espn_and_boom_bust')]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    'CREATE INDEX CONCURRENTLY roster_players_roster_idx '
                    'ON fantasy_roster_players (roster_id)',
                    'DROP INDEX CONCURRENTLY roster_players_roster_idx',
                ),
                migrations.RunSQL(
                    'CREATE INDEX CONCURRENTLY roster_players_player_idx '
                    'ON fantasy_roster_players (player_id)',
                    'DROP INDEX CONCURRENTLY roster_players_player_idx',
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name='fantasyrosterplayer',
                    index=models.Index(fields=['roster'], name='roster_players_roster_idx'),
                ),
                migrations.AddIndex(
                    model_name='fantasyrosterplayer',
                    index=models.Index(fields=['player'], name='roster_players_player_idx'),
                ),
            ],
        ),
    ]
