"""Compile real PostgreSQL migration SQL without connecting to a database."""

import importlib
import os
from unittest import TestCase

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FantasyFootballAnalyzer.test_settings')
django.setup()

from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.migrations.loader import MigrationLoader
from django.apps import apps


class QueryIndexMigrationTests(TestCase):
    def test_indexes_compile_and_reverse_including_unmanaged_tables(self):
        loader = MigrationLoader(None)
        connection = DatabaseWrapper({'ENGINE': 'django.db.backends.postgresql', 'NAME': 'unused'})
        # DROP INDEX passes empty parameters; psycopg otherwise opens a cursor
        # just to interpolate them. No interpolation is needed in this test.
        def compose_sql(sql, params):
            self.assertFalse(params)
            return sql
        connection.ops.compose_sql = compose_sql
        cases = [
            ('analyzer', '0012_query_indexes', {
                'playerweeklystats': 'pws_season_type_week_idx',
                'teamweeklystats': 'tws_season_type_week_idx',
                'playerinjuryreport': 'injury_season_week_idx',
                'playersnapcount': 'snaps_season_week_idx',
            }),
            ('leagues', '0015_roster_query_indexes', {
                'fantasyrosterplayer': 'roster_players_roster_idx',
            }),
        ]
        for app, name, expected in cases:
            with self.subTest(migration=name):
                migration = importlib.import_module(f'{app}.migrations.{name}').Migration(name, app)
                self.assertFalse(migration.atomic)
                before = loader.project_state(migration.dependencies)
                with connection.schema_editor(collect_sql=True, atomic=False) as editor:
                    after = migration.apply(before.clone(), editor)
                sql = '\n'.join(editor.collected_sql)
                for model_name, index_name in expected.items():
                    state_indexes = after.models[(app, model_name)].options['indexes']
                    live_indexes = apps.get_model(app, model_name)._meta.indexes
                    self.assertIn(index_name, [index.name for index in state_indexes])
                    self.assertEqual(state_indexes, live_indexes)
                    self.assertIn(index_name, sql)
                count = 4 if app == 'analyzer' else 2
                self.assertEqual(sql.count('CREATE INDEX CONCURRENTLY'), count)
                with connection.schema_editor(collect_sql=True, atomic=False) as editor:
                    migration.unapply(before.clone(), editor)
                self.assertEqual('\n'.join(editor.collected_sql).count('DROP INDEX CONCURRENTLY'), count)
