"""Regression checks for correcting projection migration state safely."""
import importlib
import os
from unittest import TestCase

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.test_settings')
django.setup()

from django.db.backends.sqlite3.base import DatabaseWrapper
from django.db.migrations.loader import MigrationLoader
from leagues.models import FantasyProjection, TeamWeekProjection


class ProjectionSchemaMigrationTests(TestCase):
    def setUp(self):
        self.loader = MigrationLoader(None)
        self.migration = importlib.import_module(
            'leagues.migrations.0009_reconcile_projection_schema'
        ).Migration('0009_reconcile_projection_schema', 'leagues')
        self.state = self.loader.project_state([
            ('leagues', '0008_fantasyprojection_projected_stats'),
        ])

    def test_state_repair_retains_exactly_the_current_uniqueness_rule(self):
        before = self.state.models[('leagues', 'fantasyprojection')].options['constraints']
        self.assertEqual(len(before), 2)
        operation = self.migration.operations[0]
        self.assertEqual(operation.database_operations, [])
        repaired = self.migration.mutate_state(self.state)
        constraints = repaired.models[('leagues', 'fantasyprojection')].options['constraints']
        self.assertEqual(constraints, FantasyProjection._meta.constraints)
        self.assertEqual(repaired.models[('leagues', 'teamweekprojection')].options['constraints'],
                         TeamWeekProjection._meta.constraints)

    def test_apply_preserves_existing_prediction_and_live_constraint(self):
        # Use a separate in-memory connection, never the configured database.
        connection = DatabaseWrapper({
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:',
            'TIME_ZONE': None, 'CONN_HEALTH_CHECKS': False,
            'CONN_MAX_AGE': 0, 'OPTIONS': {}, 'AUTOCOMMIT': True,
        })
        try:
            # The real database already has the correct constraint, despite the
            # duplicate entries in the migration state. Reproduce that mismatch.
            creation_state = self.state.clone()
            creation_state.models[('leagues', 'fantasyprojection')].options['constraints'] = list(FantasyProjection._meta.constraints)
            model = creation_state.apps.get_model('leagues', 'FantasyProjection')
            with connection.cursor() as cur:
                for table in ('players', 'fantasy_leagues', 'fantasy_rosters'):
                    cur.execute(f'CREATE TABLE {table} (id integer PRIMARY KEY)')
                    cur.execute(f'INSERT INTO {table} (id) VALUES (1)')
            with connection.schema_editor() as editor:
                editor.create_model(model)
            with connection.cursor() as cur:
                cur.execute("""INSERT INTO fantasy_projections
                    (player_id, season, week, projected_fantasy_points, status,
                     model_version, projected_stats, created_at, updated_at)
                    VALUES (1, 2026, 2, 8.5, 'ml_model', 'v1', '{}',
                            '2026-10-21', '2026-10-21')""")
                cur.execute('SELECT * FROM fantasy_projections')
                before = cur.fetchall()
                constraints_before = connection.introspection.get_constraints(cur, 'fantasy_projections')
            with connection.schema_editor() as editor:
                repaired_state = self.migration.apply(self.state, editor)
            with connection.cursor() as cur:
                cur.execute('SELECT * FROM fantasy_projections')
                self.assertEqual(cur.fetchall(), before)
                self.assertEqual(connection.introspection.get_constraints(cur, 'fantasy_projections'), constraints_before)
                cur.execute('SELECT COUNT(*) FROM leagues_teamweekprojection')
                self.assertEqual(cur.fetchone()[0], 0)
                constraints = connection.introspection.get_constraints(cur, 'leagues_teamweekprojection')
                self.assertTrue(constraints['unique_team_week_projection']['unique'])
            default_update = importlib.import_module(
                'leagues.migrations.0010_kicker_stats_database_default'
            ).Migration('0010_kicker_stats_database_default', 'leagues')
            with connection.schema_editor() as editor:
                default_update.apply(repaired_state, editor)
            with connection.cursor() as cur:
                cur.execute('SELECT * FROM fantasy_projections')
                self.assertEqual(cur.fetchall(), before)
                cur.execute("""INSERT INTO fantasy_projections
                    (player_id, season, week, projected_fantasy_points, status,
                     model_version, created_at, updated_at)
                    VALUES (1, 2026, 3, 7.5, 'ml_model', 'v1',
                            '2026-10-21', '2026-10-21')""")
                cur.execute('SELECT projected_stats FROM fantasy_projections WHERE week=3')
                self.assertEqual(cur.fetchone()[0], '{}')
        finally:
            connection.close()

    def test_final_state_includes_database_default_for_older_clients(self):
        final_state = self.loader.project_state([
            ('leagues', '0010_kicker_stats_database_default'),
        ])
        field = final_state.models[('leagues', 'fantasyprojection')].fields['projected_stats']
        self.assertEqual(field.db_default, {})
