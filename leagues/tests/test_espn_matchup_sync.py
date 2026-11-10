"""Regression tests for ESPN matchup synchronization."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch, call

from leagues.services.matchup_sync import (
    sync_connection_matchups,
    sync_espn_matchups,
)


class ESPNMatchupSyncTests(unittest.TestCase):

    def setUp(self):
        self.league = SimpleNamespace(id=9, season=2026)
        self.connection = SimpleNamespace(
            platform="espn",
            league=self.league,
            espn_credentials_encrypted="encrypted-test-value",
        )

    def test_completed_and_future_matchups(self):
        schedule = [
            {
                "id": 101,
                "matchupPeriodId": 1,
                "winner": "HOME",
                "home": {"teamId": 1, "totalPoints": 143.36},
                "away": {"teamId": 2, "totalPoints": 135.46},
            },
            {
                "id": 102,
                "matchupPeriodId": 9,
                "winner": "UNDECIDED",
                "home": {"teamId": 1, "totalPoints": 0.0},
                "away": {"teamId": 3, "totalPoints": 0.0},
            },
        ]

        with (
            patch("leagues.services.matchup_sync.LeaguePlatformIdentity.objects.get") as identity,
            patch("leagues.integrations.espn_credentials.decrypt_espn_credentials",
                  return_value=("{TEST-SWID}", "test-session")) as decrypt,
            patch("leagues.integrations.espn.ESPNLeagueService") as service,
            patch("leagues.services.matchup_sync._save_week", return_value=2) as save,
        ):
            identity.return_value.external_id = "123456:2026"
            service.return_value._get.return_value = {"schedule": schedule}

            imported = sync_espn_matchups(self.connection, current_week=9)

            self.assertEqual(imported, 4)
            decrypt.assert_called_once_with("encrypted-test-value")
            service.assert_called_once_with(
                "123456", "2026",
                swid="{TEST-SWID}", espn_s2="test-session",
            )

            self.assertEqual(save.call_count, 2)

            completed = save.call_args_list[0].args[4]
            future = save.call_args_list[1].args[4]

            self.assertEqual(
                [row["external_roster_id"] for row in completed],
                ["123456:2026:1", "123456:2026:2"],
            )
            self.assertEqual(
                [row["points"] for row in completed],
                [143.36, 135.46],
            )
            self.assertTrue(all(row["is_final"] for row in completed))

            self.assertEqual(
                [row["external_roster_id"] for row in future],
                ["123456:2026:1", "123456:2026:3"],
            )
            self.assertTrue(all(row["points"] is None for row in future))
            self.assertTrue(all(not row["is_final"] for row in future))

    def test_dispatch_uses_espn_importer(self):
        with patch(
            "leagues.services.matchup_sync.sync_espn_matchups",
            return_value=28,
        ) as sync:
            result = sync_connection_matchups(
                self.connection, current_week=9,
            )

        self.assertEqual(result, 28)
        sync.assert_called_once_with(
            self.connection,
            start_week=1,
            end_week=18,
            current_week=9,
        )

    def test_missing_credentials_allows_public_league(self):
        self.connection.espn_credentials_encrypted = None

        with (
            patch("leagues.services.matchup_sync.LeaguePlatformIdentity.objects.get") as identity,
            patch("leagues.integrations.espn.ESPNLeagueService") as service,
            patch("leagues.services.matchup_sync._save_week") as save,
        ):
            identity.return_value.external_id = "123456:2026"
            service.return_value._get.return_value = {"schedule": []}

            with self.assertRaisesRegex(
                ValueError, "empty or invalid matchup schedule"
            ):
                sync_espn_matchups(self.connection)

            service.assert_called_once_with("123456", "2026")
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class ESPNRosterMappingTests(unittest.TestCase):
    """Verify actual matchup construction without writing to a live database."""

    def test_legacy_and_modern_roster_ids(self):
        from leagues.services.matchup_sync import _save_week

        cases = [
            ("legacy", "1", "2", "2127:2026:1", "2127:2026:2"),
            (
                "modern",
                "2075821650:2026:1",
                "2075821650:2026:2",
                "2075821650:2026:1",
                "2075821650:2026:2",
            ),
        ]

        for label, stored_home, stored_away, incoming_home, incoming_away in cases:
            with self.subTest(format=label):
                from leagues.models import FantasyLeague
                league = FantasyLeague(id=9, season=2026)
                identities = [
                    SimpleNamespace(external_id=stored_home, roster_id=74),
                    SimpleNamespace(external_id=stored_away, roster_id=75),
                ]
                records = [
                    {
                        "external_roster_id": incoming_home,
                        "matchup_id": 101,
                        "points": 143.36,
                        "is_final": True,
                    },
                    {
                        "external_roster_id": incoming_away,
                        "matchup_id": 101,
                        "points": 135.46,
                        "is_final": True,
                    },
                ]

                with (
                    patch(
                        "leagues.services.matchup_sync."
                        "RosterPlatformIdentity.objects.filter",
                        return_value=SimpleNamespace(
                            select_related=lambda *_: identities
                        ),
                    ),
                    patch(
                        "leagues.services.matchup_sync."
                        "FantasyMatchup.objects.bulk_create"
                    ) as bulk_create,
                ):
                    imported = _save_week(
                        league, "espn", 2026, 1, records
                    )

                self.assertEqual(imported, 2)
                saved = bulk_create.call_args.args[0]
                self.assertEqual(
                    [(m.roster_id, m.opponent_id) for m in saved],
                    [(74, 75), (75, 74)],
                )
                self.assertEqual(
                    [(m.points, m.opponent_points) for m in saved],
                    [(143.36, 135.46), (135.46, 143.36)],
                )
                self.assertTrue(all(m.is_final for m in saved))


class ESPNValidationTests(unittest.TestCase):
    """Reject incomplete ESPN schedules and unmapped teams."""

    def test_matchup_missing_away_team(self):
        from leagues.models import FantasyLeague

        league = FantasyLeague(id=9, season=2026)
        connection = SimpleNamespace(
            platform="espn",
            league=league,
            espn_credentials_encrypted=None,
        )

        with (
            patch(
                "leagues.services.matchup_sync."
                "LeaguePlatformIdentity.objects.get"
            ) as identity,
            patch(
                "leagues.integrations.espn.ESPNLeagueService"
            ) as service,
            patch(
                "leagues.services.matchup_sync._save_week"
            ) as save,
        ):
            identity.return_value.external_id = "2075821650:2026"
            service.return_value._get.return_value = {
                "schedule": [{
                    "id": 101,
                    "matchupPeriodId": 1,
                    "winner": "HOME",
                    "home": {"teamId": 1, "totalPoints": 100},
                    "away": {},
                }]
            }

            with self.assertRaisesRegex(ValueError, "missing a team"):
                sync_espn_matchups(connection)

            save.assert_not_called()

    def test_missing_matchup_id_rejected(self):
        from leagues.models import FantasyLeague

        league = FantasyLeague(id=9, season=2026)
        connection = SimpleNamespace(
            platform="espn",
            league=league,
            espn_credentials_encrypted=None,
        )

        with (
            patch(
                "leagues.services.matchup_sync."
                "LeaguePlatformIdentity.objects.get"
            ) as identity,
            patch(
                "leagues.integrations.espn.ESPNLeagueService"
            ) as service,
            patch(
                "leagues.services.matchup_sync._save_week"
            ) as save,
        ):
            identity.return_value.external_id = "2075821650:2026"
            service.return_value._get.return_value = {
                "schedule": [{
                    "matchupPeriodId": 1,
                    "winner": "HOME",
                    "home": {"teamId": 1, "totalPoints": 100},
                    "away": {"teamId": 2, "totalPoints": 90},
                }]
            }

            with self.assertRaisesRegex(ValueError, "missing matchup ID"):
                sync_espn_matchups(connection)

            save.assert_not_called()

    def test_unmapped_espn_roster_raises_error(self):
        from leagues.models import FantasyLeague
        from leagues.services.matchup_sync import _save_week

        league = FantasyLeague(id=9, season=2026)

        records = [{
            "external_roster_id": "2075821650:2026:99",
            "matchup_id": 101,
            "points": 100.0,
            "is_final": True,
        }]

        with (
            patch(
                "leagues.services.matchup_sync."
                "RosterPlatformIdentity.objects.filter"
            ) as identities,
            patch(
                "leagues.services.matchup_sync."
                "FantasyMatchup.objects.bulk_create"
            ) as bulk_create,
        ):
            identities.return_value.select_related.return_value = []

            with self.assertRaisesRegex(
                ValueError, "no matching roster"
            ):
                _save_week(league, "espn", 2026, 1, records)

            bulk_create.assert_not_called()


class ESPNOpponentValidationTests(unittest.TestCase):
    """Reject ESPN matchups whose opponent cannot be resolved."""

    def test_unmapped_opponent_rejects_entire_week(self):
        from leagues.models import FantasyLeague
        from leagues.services.matchup_sync import _save_week

        league = FantasyLeague(id=9, season=2026)
        records = [
            {
                "external_roster_id": "2075821650:2026:1",
                "matchup_id": 101,
                "points": 120.0,
                "is_final": True,
            },
            {
                "external_roster_id": "2075821650:2026:99",
                "matchup_id": 101,
                "points": 100.0,
                "is_final": True,
            },
        ]

        with (
            patch(
                "leagues.services.matchup_sync."
                "RosterPlatformIdentity.objects.filter"
            ) as identities,
            patch(
                "leagues.services.matchup_sync."
                "FantasyMatchup.objects.bulk_create"
            ) as bulk_create,
        ):
            identities.return_value.select_related.return_value = [
                SimpleNamespace(
                    external_id="2075821650:2026:1",
                    roster_id=74,
                )
            ]

            with self.assertRaisesRegex(
                ValueError, "no matching roster"
            ):
                _save_week(league, "espn", 2026, 1, records)

            bulk_create.assert_not_called()


    def test_missing_opponent_record_rejected(self):
        from leagues.models import FantasyLeague
        from leagues.services.matchup_sync import _save_week

        league = FantasyLeague(id=9, season=2026)
        records = [{
            "external_roster_id": "2075821650:2026:1",
            "matchup_id": 101,
            "points": 120.0,
            "is_final": True,
        }]

        with (
            patch(
                "leagues.services.matchup_sync."
                "RosterPlatformIdentity.objects.filter"
            ) as identities,
            patch(
                "leagues.services.matchup_sync."
                "FantasyMatchup.objects.bulk_create"
            ) as bulk_create,
        ):
            identities.return_value.select_related.return_value = [
                SimpleNamespace(
                    external_id="2075821650:2026:1",
                    roster_id=74,
                )
            ]

            with self.assertRaisesRegex(
                ValueError, "missing opponent"
            ):
                _save_week(league, "espn", 2026, 1, records)

            bulk_create.assert_not_called()


class ESPNTransactionTests(unittest.TestCase):
    """Ensure ESPN imports execute inside one atomic transaction."""

    def test_week_failure_rolls_back_sync(self):
        from leagues.models import FantasyLeague

        league = FantasyLeague(id=9, season=2026)
        connection = SimpleNamespace(
            platform="espn",
            league=league,
            espn_credentials_encrypted=None,
        )

        schedule = [
            {
                "id": 101,
                "matchupPeriodId": 1,
                "winner": "HOME",
                "home": {"teamId": 1, "totalPoints": 120},
                "away": {"teamId": 2, "totalPoints": 100},
            },
            {
                "id": 102,
                "matchupPeriodId": 2,
                "winner": "AWAY",
                "home": {"teamId": 1, "totalPoints": 90},
                "away": {"teamId": 2, "totalPoints": 110},
            },
        ]

        with (
            patch(
                "leagues.services.matchup_sync."
                "LeaguePlatformIdentity.objects.get"
            ) as identity,
            patch(
                "leagues.integrations.espn.ESPNLeagueService"
            ) as service,
            patch(
                "leagues.services.matchup_sync.transaction.atomic"
            ) as atomic,
            patch(
                "leagues.services.matchup_sync._save_week",
                side_effect=[2, ValueError("Simulated Week 2 failure")],
            ) as save,
        ):
            identity.return_value.external_id = "2075821650:2026"
            service.return_value._get.return_value = {
                "schedule": schedule
            }

            with self.assertRaisesRegex(
                ValueError, "Simulated Week 2 failure"
            ):
                sync_espn_matchups(connection)

            atomic.assert_called_once()
            self.assertEqual(save.call_count, 2)
            self.assertEqual(save.call_args_list[0].args[3], 1)
            self.assertEqual(save.call_args_list[1].args[3], 2)


class ESPNDatabaseRollbackTests(__import__("django.test").test.TestCase):
    """Verify that a failed ESPN sync rolls back real matchup inserts."""

    @classmethod
    def setUpClass(cls):
        from django.db import connection

        from leagues.models import FantasyLeague, FantasyRoster

        with connection.schema_editor() as editor:
            editor.create_model(FantasyLeague)
            editor.create_model(FantasyRoster)

        try:
            super().setUpClass()
        except Exception:
            from leagues.models import FantasyLeague, FantasyRoster

            with connection.schema_editor() as editor:
                editor.delete_model(FantasyRoster)
                editor.delete_model(FantasyLeague)
            raise

    @classmethod
    def tearDownClass(cls):
        from django.db import connection
        from leagues.models import FantasyLeague, FantasyRoster

        try:
            super().tearDownClass()
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(FantasyRoster)
                editor.delete_model(FantasyLeague)

    def test_failed_second_week_rolls_back_first_week(self):
        from django.utils import timezone
        from leagues.models import (
            FantasyLeague,
            FantasyMatchup,
            FantasyRoster,
            LeaguePlatformIdentity,
            RosterPlatformIdentity,
        )

        league = FantasyLeague.objects.create(
            sleeper_league_id="espn-rollback-test",
            name="ESPN Rollback Test",
            season=2026,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

        identity = LeaguePlatformIdentity.objects.create(
            league=league,
            platform="espn",
            external_id="123456:2026",
        )

        roster1 = FantasyRoster.objects.create(
            league=league,
            sleeper_roster_id=1,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        roster2 = FantasyRoster.objects.create(
            league=league,
            sleeper_roster_id=2,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

        RosterPlatformIdentity.objects.create(
            roster=roster1,
            platform="espn",
            external_id="123456:2026:1",
        )
        RosterPlatformIdentity.objects.create(
            roster=roster2,
            platform="espn",
            external_id="123456:2026:2",
        )

        connection = SimpleNamespace(
            platform="espn",
            league=league,
            espn_credentials_encrypted=None,
        )

        schedule = [
            {
                "id": 101,
                "matchupPeriodId": 1,
                "winner": "HOME",
                "home": {"teamId": 1, "totalPoints": 120},
                "away": {"teamId": 2, "totalPoints": 100},
            },
            {
                "id": 102,
                "matchupPeriodId": 2,
                "winner": "AWAY",
                "home": {"teamId": 1, "totalPoints": 90},
                "away": {"teamId": 99, "totalPoints": 110},
            },
        ]

        with patch(
            "leagues.integrations.espn.ESPNLeagueService"
        ) as service:
            service.return_value._get.return_value = {
                "schedule": schedule
            }

            with self.assertRaisesRegex(
                ValueError, "no matching roster"
            ):
                sync_espn_matchups(connection)

        self.assertEqual(
            FantasyMatchup.objects.filter(
                league=league, platform="espn"
            ).count(),
            0,
        )
