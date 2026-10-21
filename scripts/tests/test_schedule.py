import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','FantasyFootballAnalyzer.test_settings')
django.setup()
from leagues.services.schedule import confirmed_bye_team_ids
from scripts.imports.import_nfl_schedule import import_nfl_schedule


class ByeDetectionTests(TestCase):
    def byes(self, rows, week):
        with patch('leagues.services.schedule.NFLGame.objects.filter') as query:
            query.return_value.values_list.return_value=rows
            result=confirmed_bye_team_ids(2026,week)
            query.assert_called_once_with(season=2026,game_type='REG')
            return result

    def test_missing_rams_game_does_not_mean_raiders_bye(self):
        rows=[(1,2,w) for w in range(1,19) if w not in (7,13)]
        self.assertNotIn(1,self.byes(rows,7))

    def test_complete_schedule_identifies_only_week_13_as_bye(self):
        rows=[(1,2,w) for w in range(1,19) if w!=13]
        self.assertIn(1,self.byes(rows,13))
        self.assertNotIn(1,self.byes(rows,7))

    def test_duplicate_game_rows_cannot_fake_a_complete_schedule(self):
        rows=[(1,2,w) for w in range(1,19) if w not in (7,13)]
        self.assertNotIn(1,self.byes(rows+rows[:1],7))


class ScheduleImportTests(TestCase):
    def run_import(self, away='LA', home='LV', missing=True, existing=()):
        rams=SimpleNamespace(id=1,abbreviation='LAR')
        raiders=SimpleNamespace(id=2,abbreviation='LV')
        csv='season,game_type,away_team,home_team,gameday,gametime,week\n2026,REG,'+away+','+home+',2026-10-25,13:25,7\n'
        with patch('scripts.imports.import_nfl_schedule.requests.get') as get, \
             patch('scripts.imports.import_nfl_schedule.Teams.objects.all',return_value=[rams,raiders]), \
             patch('scripts.imports.import_nfl_schedule.NFLGame.objects.get_or_create',return_value=(object(),True)) as create, \
             patch('scripts.imports.import_nfl_schedule.NFLGame.objects.update_or_create',return_value=(object(),True)) as update, \
             patch('scripts.imports.import_nfl_schedule.NFLGame.objects.filter') as query:
            get.return_value.text=csv
            query.return_value.values_list.return_value=existing
            import_nfl_schedule(2026,missing_only=missing)
            return create.call_args,update.call_args

    def test_away_rams_alias_is_imported(self):
        created,updated=self.run_import()
        self.assertEqual(created.kwargs['away_team'].abbreviation,'LAR')
        self.assertEqual(created.kwargs['home_team'].abbreviation,'LV')
        self.assertIsNone(updated)

    def test_home_rams_alias_is_imported(self):
        created,_=self.run_import(away='LV',home='LA')
        self.assertEqual(created.kwargs['home_team'].abbreviation,'LAR')

    def test_missing_only_preserves_existing_games(self):
        created,updated=self.run_import(existing=[(2026,7,1,2)])
        self.assertIsNone(created)
        self.assertIsNone(updated)

    def test_normal_import_keeps_existing_update_behavior(self):
        created,updated=self.run_import(missing=False)
        self.assertIsNone(created)
        self.assertEqual(updated.kwargs['away_team'].abbreviation,'LAR')
