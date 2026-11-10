"""Database-free regression checks for ESPN import identity handling."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from leagues.integrations.espn import ESPNLeagueService


class ESPNImportIdentityTests(unittest.TestCase):
    def test_repeat_import_reuses_existing_league_and_roster(self):
        service = ESPNLeagueService(
            "123456", 2026,
            swid="{TEST-SWID}",
            espn_s2="test-session",
        )

        fixture = {
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [{"id": 1, "name": "Team Alpha"}],
            "rosters": [{"id": 1, "roster": {"entries": []}}],
            "name": "Test ESPN League",
        }

        league = SimpleNamespace(id=10, season=2026)
        roster = SimpleNamespace(id=20, owner_name="Team Alpha")

        league.save = MagicMock()
        roster.save = MagicMock()

        league_identity = SimpleNamespace(league=league)
        roster_identity = SimpleNamespace(roster=roster)

        def queryset_result(identity):
            qs = MagicMock()
            qs.select_related.return_value = qs
            qs.first.return_value = identity
            return qs

        with (
            patch.object(
                service, "get_league_data", return_value=fixture
            ),
            patch("leagues.integrations.espn.Teams"),
            patch(
                "leagues.integrations.espn.LeaguePlatformIdentity"
            ) as league_model,
            patch(
                "leagues.integrations.espn.RosterPlatformIdentity"
            ) as roster_model,
            patch(
                "leagues.integrations.espn.FantasyLeague"
            ) as fantasy_league,
            patch(
                "leagues.integrations.espn.FantasyRoster"
            ) as fantasy_roster,
            patch(
                "leagues.integrations.espn.Player"
            ) as player_model,
            patch(
                "leagues.integrations.espn.PlayerPlatformIdentity"
            ) as player_identity_model,
            patch(
                "leagues.integrations.espn.FantasyRosterPlayer"
            ),
            patch(
                "leagues.integrations.espn.UserLeagueConnection"
            ) as connections,
        ):
            league_model.objects.filter.return_value = queryset_result(
                league_identity
            )
            roster_model.objects.filter.return_value = queryset_result(
                roster_identity
            )
            player_model.objects.all.return_value = []
            player_identity_model.objects.filter.return_value.select_related.return_value = []

            user = SimpleNamespace(pk=42)

            first = service.import_league(user, owned_team_id="1")
            second = service.import_league(user, owned_team_id="1")

            self.assertIs(first["league"], league)
            self.assertIs(second["league"], league)
            self.assertIs(first["my_roster"], roster)
            self.assertIs(second["my_roster"], roster)

            fantasy_league.objects.create.assert_not_called()
            fantasy_roster.objects.create.assert_not_called()

            self.assertEqual(
                league_model.objects.filter.call_args.kwargs["external_id"],
                "123456:2026",
            )
            self.assertEqual(
                roster_model.objects.filter.call_args.kwargs["external_id"],
                "123456:2026:1",
            )

            connection_kwargs = (
                connections.objects.update_or_create.call_args.kwargs
            )
            self.assertIs(connection_kwargs["user"], user)
            self.assertIs(connection_kwargs["league"], league)
            self.assertEqual(
                connection_kwargs["external_user_id"],
                "123456:2026:1",
            )

            encrypted = connection_kwargs["defaults"][
                "espn_credentials_encrypted"
            ]
            self.assertNotIn("TEST-SWID", encrypted)
            self.assertNotIn("test-session", encrypted)

            from leagues.integrations.espn_credentials import (
                decrypt_espn_credentials,
            )
            self.assertEqual(
                decrypt_espn_credentials(encrypted),
                ("{TEST-SWID}", "test-session"),
            )


    def test_legacy_espn_identities_are_reused(self):
        service = ESPNLeagueService("123456", 2026)

        fixture = {
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [{"id": 1, "name": "Legacy Team"}],
            "rosters": [{"id": 1, "roster": {"entries": []}}],
            "name": "Legacy ESPN League",
        }

        league = SimpleNamespace(id=10, season=2026)
        league.save = MagicMock()

        roster = SimpleNamespace(id=20, league=league)
        roster.save = MagicMock()

        legacy_league_identity = SimpleNamespace(
            league=league,
            external_id="123456",
        )
        legacy_league_identity.save = MagicMock()

        legacy_roster_identity = SimpleNamespace(
            roster=roster,
            external_id="1",
        )
        legacy_roster_identity.save = MagicMock()

        def result(value):
            qs = MagicMock()
            qs.select_related.return_value = qs
            qs.first.return_value = value
            return qs

        with (
            patch.object(service, "get_league_data", return_value=fixture),
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as leagues,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as rosters,
            patch("leagues.integrations.espn.FantasyLeague") as league_model,
            patch("leagues.integrations.espn.FantasyRoster") as roster_model,
            patch("leagues.integrations.espn.Player") as players,
            patch("leagues.integrations.espn.PlayerPlatformIdentity") as player_ids,
            patch("leagues.integrations.espn.FantasyRosterPlayer"),
            patch("leagues.integrations.espn.UserLeagueConnection"),
        ):
            leagues.objects.filter.side_effect = [
                result(None),
                result(legacy_league_identity),
            ]
            rosters.objects.filter.side_effect = [
                result(None),
                result(legacy_roster_identity),
            ]
            players.objects.all.return_value = []
            player_ids.objects.filter.return_value.select_related.return_value = []

            imported = service.import_league(
                SimpleNamespace(pk=42),
                owned_team_id="1",
            )

            self.assertIs(imported["league"], league)
            self.assertIs(imported["my_roster"], roster)

            league_model.objects.create.assert_not_called()
            roster_model.objects.create.assert_not_called()

            self.assertEqual(
                legacy_league_identity.external_id,
                "123456:2026",
            )
            self.assertEqual(
                legacy_roster_identity.external_id,
                "123456:2026:1",
            )

            legacy_league_identity.save.assert_called_once()
            legacy_roster_identity.save.assert_called_once()



    def test_same_team_id_in_different_leagues(self):
        """ESPN Team ID 1 must be distinct across different leagues."""
        from leagues.integrations.espn import RosterPlatformIdentity

        league_a = ESPNLeagueService("123456", 2026)
        league_b = ESPNLeagueService("789012", 2026)

        key_a = f"{league_a.league_id}:{league_a.season}:1"
        key_b = f"{league_b.league_id}:{league_b.season}:1"

        self.assertEqual(key_a, "123456:2026:1")
        self.assertEqual(key_b, "789012:2026:1")
        self.assertNotEqual(key_a, key_b)

        # Both identifiers must fit the existing database field.
        max_length = RosterPlatformIdentity._meta.get_field(
            "external_id"
        ).max_length

        self.assertLessEqual(len(key_a), max_length)
        self.assertLessEqual(len(key_b), max_length)

        # A different season must also produce a different identity.
        league_next_season = ESPNLeagueService("123456", 2027)
        key_next_season = (
            f"{league_next_season.league_id}:"
            f"{league_next_season.season}:1"
        )

        self.assertNotEqual(key_a, key_next_season)



    def test_unresolved_player_does_not_silently_succeed(self):
        """An incomplete roster must not be reported as a full import."""
        service = ESPNLeagueService("123456", 2026)

        fixture = {
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [{"id": 1, "name": "Team Alpha"}],
            "rosters": [{
                "id": 1,
                "roster": {
                    "entries": [{
                        "lineupSlotId": 0,
                        "playerPoolEntry": {
                            "player": {
                                "id": 999001,
                                "fullName": "Unmatched Test Player",
                                "defaultPositionId": 1,
                            }
                        }
                    }]
                }
            }],
            "name": "Test ESPN League",
        }

        league = SimpleNamespace(id=10, season=2026)
        league.save = MagicMock()

        roster = SimpleNamespace(id=20)
        roster.save = MagicMock()

        def queryset_result(identity):
            qs = MagicMock()
            qs.select_related.return_value = qs
            qs.first.return_value = identity
            return qs

        with (
            patch.object(service, "get_league_data", return_value=fixture),
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as leagues,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as rosters,
            patch("leagues.integrations.espn.Player") as players,
            patch("leagues.integrations.espn.PlayerPlatformIdentity") as player_ids,
            patch("leagues.integrations.espn.FantasyRosterPlayer"),
            patch("leagues.integrations.espn.UserLeagueConnection"),
        ):
            leagues.objects.filter.return_value = queryset_result(
                SimpleNamespace(league=league)
            )
            rosters.objects.filter.return_value = queryset_result(
                SimpleNamespace(roster=roster)
            )
            players.objects.all.return_value = []
            player_ids.objects.filter.return_value.select_related.return_value = []

            result = service.import_league(
                SimpleNamespace(pk=42),
                owned_team_id="1",
            )

            self.assertGreater(
                result.get("players_unresolved", 0),
                0,
                "Unresolved ESPN players must be reported explicitly.",
            )

    def test_incomplete_roster_preserves_existing_players(self):
        """An unresolved ESPN player must not erase an existing roster."""
        service = ESPNLeagueService("123456", 2026)

        fixture = {
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [{"id": 1, "name": "Team Alpha"}],
            "rosters": [{
                "id": 1,
                "roster": {
                    "entries": [{
                        "lineupSlotId": 0,
                        "playerPoolEntry": {
                            "player": {
                                "id": 999001,
                                "fullName": "Unmatched Test Player",
                                "defaultPositionId": 1,
                            }
                        }
                    }]
                }
            }],
            "name": "Test ESPN League",
        }

        league = SimpleNamespace(id=10, season=2026)
        league.save = MagicMock()

        roster = SimpleNamespace(id=20)
        roster.save = MagicMock()

        def queryset_result(identity):
            qs = MagicMock()
            qs.select_related.return_value = qs
            qs.first.return_value = identity
            return qs

        with (
            patch.object(service, "get_league_data", return_value=fixture),
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as leagues,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as rosters,
            patch("leagues.integrations.espn.Player") as players,
            patch("leagues.integrations.espn.PlayerPlatformIdentity") as player_ids,
            patch("leagues.integrations.espn.FantasyRosterPlayer") as roster_players,
            patch("leagues.integrations.espn.UserLeagueConnection") as connections,
        ):
            leagues.objects.filter.return_value = queryset_result(
                SimpleNamespace(league=league)
            )
            rosters.objects.filter.return_value = queryset_result(
                SimpleNamespace(roster=roster)
            )
            players.objects.all.return_value = []
            player_ids.objects.filter.return_value.select_related.return_value = []

            result = service.import_league(
                SimpleNamespace(pk=42),
                owned_team_id="1",
            )

            self.assertGreater(result["players_unresolved"], 0)
            self.assertFalse(result["my_roster_complete"])
            connections.objects.update_or_create.assert_not_called()
            roster_players.objects.filter.assert_not_called()
            roster_players.objects.bulk_create.assert_not_called()

    def test_complete_roster_replaces_existing_players(self):
        """A fully resolved ESPN roster must replace outdated players."""
        service = ESPNLeagueService("123456", 2026)

        fixture = {
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [{"id": 1, "name": "Team Alpha"}],
            "rosters": [{
                "id": 1,
                "roster": {
                    "entries": [{
                        "lineupSlotId": 0,
                        "playerPoolEntry": {
                            "player": {
                                "id": 999001,
                                "fullName": "Unmatched Test Player",
                                "defaultPositionId": 1,
                            }
                        }
                    }]
                }
            }],
            "name": "Test ESPN League",
        }

        league = SimpleNamespace(id=10, season=2026)
        league.save = MagicMock()

        roster = SimpleNamespace(id=20)
        roster.save = MagicMock()

        def queryset_result(identity):
            qs = MagicMock()
            qs.select_related.return_value = qs
            qs.first.return_value = identity
            return qs

        with (
            patch.object(service, "get_league_data", return_value=fixture),
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as leagues,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as rosters,
            patch("leagues.integrations.espn.Player") as players,
            patch("leagues.integrations.espn.PlayerPlatformIdentity") as player_ids,
            patch("leagues.integrations.espn.FantasyRosterPlayer") as roster_players,
            patch("leagues.integrations.espn.UserLeagueConnection") as connections,
        ):
            leagues.objects.filter.return_value = queryset_result(
                SimpleNamespace(league=league)
            )
            rosters.objects.filter.return_value = queryset_result(
                SimpleNamespace(roster=roster)
            )
            players.objects.all.return_value = []
            player_ids.objects.filter.return_value.select_related.return_value = [
                SimpleNamespace(
                    external_id="999001",
                    player=SimpleNamespace(id=100, full_name="Unmatched Test Player"),
                )
            ]

            result = service.import_league(
                SimpleNamespace(pk=42),
                owned_team_id="1",
            )

            self.assertEqual(result["players_unresolved"], 0)
            self.assertTrue(result["my_roster_complete"])
            connections.objects.update_or_create.assert_called_once()
            self.assertEqual(result["players_imported"], 1)
            roster_players.objects.filter.assert_called_once_with(
                roster=roster
            )
            roster_players.objects.filter.return_value.delete.assert_called_once()
            roster_players.objects.bulk_create.assert_called_once()
            saved_players = roster_players.objects.bulk_create.call_args.args[0]
            self.assertEqual(len(saved_players), 1)
            roster_players.assert_called_once_with(
                roster=roster,
                player=player_ids.objects.filter.return_value.select_related.return_value[0].player,
                team=None,
                roster_slot="QB",
                created_at=unittest.mock.ANY,
            )


class ESPNCrossTeamCompletenessTests(unittest.TestCase):
    """Other teams' unresolved players must not block my roster."""

    def test_other_team_unresolved_does_not_block_my_roster(self):
        service = ESPNLeagueService("123456", 2026)

        def entry(player_id):
            return {
                "lineupSlotId": 0,
                "playerPoolEntry": {
                    "player": {
                        "id": player_id,
                        "fullName": f"Test Player {player_id}",
                        "defaultPositionId": 1,
                    }
                },
            }

        fixture = {
            "name": "Two Team ESPN League",
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [
                {"id": 1, "name": "My Team"},
                {"id": 2, "name": "Other Team"},
            ],
            "rosters": [
                {"id": 1, "roster": {"entries": [entry(1001)]}},
                {"id": 2, "roster": {"entries": [entry(2002)]}},
            ],
        }

        league = SimpleNamespace(id=10, season=2026)
        league.save = MagicMock()

        my_roster = SimpleNamespace(id=20)
        my_roster.save = MagicMock()
        other_roster = SimpleNamespace(id=21)
        other_roster.save = MagicMock()

        def queryset_result(identity):
            qs = MagicMock()
            qs.select_related.return_value = qs
            qs.first.return_value = identity
            return qs

        with (
            patch.object(service, "get_league_data", return_value=fixture),
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as leagues,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as rosters,
            patch("leagues.integrations.espn.Player") as players,
            patch("leagues.integrations.espn.PlayerPlatformIdentity") as player_ids,
            patch("leagues.integrations.espn.FantasyRosterPlayer") as roster_players,
            patch("leagues.integrations.espn.UserLeagueConnection"),
        ):
            leagues.objects.filter.return_value = queryset_result(
                SimpleNamespace(league=league)
            )

            roster_lookup = MagicMock()
            roster_lookup.select_related.return_value = roster_lookup
            roster_lookup.first.side_effect = [
                SimpleNamespace(roster=my_roster),
                SimpleNamespace(roster=other_roster),
            ]
            rosters.objects.filter.return_value = roster_lookup

            players.objects.all.return_value = []
            player_ids.objects.filter.return_value.select_related.return_value = [
                SimpleNamespace(
                    external_id="1001",
                    player=SimpleNamespace(id=101, full_name="Test Player 1001"),
                )
            ]

            result = service.import_league(
                SimpleNamespace(pk=42),
                owned_team_id="1",
            )

            self.assertIs(result["my_roster"], my_roster)
            self.assertTrue(result["my_roster_complete"])
            self.assertEqual(result["players_unresolved"], 1)
            self.assertEqual(result["players_imported"], 1)

            roster_players.objects.filter.assert_called_once_with(
                roster=my_roster
            )
            roster_players.objects.bulk_create.assert_called_once()


class ESPNImportScoringTests(unittest.TestCase):
    """Verify that ESPN imports persist normalized scoring settings."""

    def test_import_persists_half_ppr_scoring(self):
        from unittest.mock import MagicMock, patch

        from leagues.integrations.espn import ESPNLeagueService

        service = ESPNLeagueService.__new__(ESPNLeagueService)
        service.league_id = "123456"
        service.season = 2026

        settings = {
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 53, "points": 0.5}
                ]
            }
        }

        service.get_league_data = MagicMock(return_value={
            "name": "Half-PPR Test League",
            "league": {"settings": settings},
            "teams": [{"id": 1, "name": "Test Team"}],
            "rosters": [{"id": 1, "roster": {"entries": []}}],
        })

        with (
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as league_ids,
            patch("leagues.integrations.espn.FantasyLeague") as leagues,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as roster_ids,
            patch("leagues.integrations.espn.FantasyRoster") as rosters,
            patch("leagues.integrations.espn.FantasyRosterPlayer"),
            patch("leagues.integrations.espn.Player"),
            patch("leagues.integrations.espn.PlayerPlatformIdentity"),
        ):
            league_ids.objects.filter.return_value.select_related.return_value.first.return_value = None
            roster_ids.objects.filter.return_value.select_related.return_value.first.return_value = None

            user = MagicMock()
            service.import_league(user)

            self.assertTrue(leagues.objects.create.called)
            saved = leagues.objects.create.call_args.kwargs

            self.assertEqual(saved["ppr"], 0.5)
            self.assertEqual(saved["te_premium"], 0.0)
            self.assertEqual(saved["scoring_settings"], settings)


class ESPNMissingRosterTests(unittest.TestCase):
    """Missing ESPN roster payloads must not erase existing players."""

    def test_missing_roster_data_preserves_existing_players(self):
        from unittest.mock import MagicMock, patch

        service = ESPNLeagueService("123456", 2026)

        fixture = {
            "name": "Missing Roster Test League",
            "league": {
                "settings": {
                    "rosterSettings": {
                        "lineupSlotCounts": {"0": 1}
                    }
                }
            },
            "teams": [{"id": 1, "name": "Team Alpha"}],
            "rosters": [],
        }

        league = MagicMock()
        league.season = 2026
        roster = MagicMock()

        with (
            patch.object(service, "get_league_data", return_value=fixture),
            patch("leagues.integrations.espn.Teams"),
            patch("leagues.integrations.espn.LeaguePlatformIdentity") as league_ids,
            patch("leagues.integrations.espn.RosterPlatformIdentity") as roster_ids,
            patch("leagues.integrations.espn.FantasyRosterPlayer") as roster_players,
            patch("leagues.integrations.espn.Player"),
            patch("leagues.integrations.espn.PlayerPlatformIdentity"),
            patch("leagues.integrations.espn.UserLeagueConnection") as connections,
        ):
            league_ids.objects.filter.return_value.select_related.return_value.first.return_value = (
                MagicMock(league=league)
            )
            roster_ids.objects.filter.return_value.select_related.return_value.first.return_value = (
                MagicMock(roster=roster)
            )

            result = service.import_league(
                MagicMock(),
                owned_team_id="1",
            )

            self.assertIs(result["my_roster"], roster)
            self.assertFalse(result["my_roster_complete"])
            connections.objects.update_or_create.assert_not_called()

            roster_players.objects.filter.assert_not_called()
            roster_players.objects.bulk_create.assert_not_called()


    def test_malformed_roster_entries_preserve_existing_players(self):
        """Malformed entries must never erase existing roster data."""

        malformed_entries = [
            None,
            {},
            {"playerPoolEntry": None},
            {"playerPoolEntry": {"player": None}},
            {"playerPoolEntry": {"player": {}}},
        ]

        for malformed_entry in malformed_entries:
            with self.subTest(entry=malformed_entry):
                service = ESPNLeagueService("123456", 2026)

                fixture = {
                    "name": "Malformed Roster Test",
                    "league": {
                        "settings": {
                            "rosterSettings": {
                                "lineupSlotCounts": {"0": 1}
                            }
                        }
                    },
                    "teams": [{"id": 1, "name": "Team Alpha"}],
                    "rosters": [{
                        "id": 1,
                        "roster": {
                            "entries": [malformed_entry]
                        }
                    }],
                }

                league = MagicMock()
                league.season = 2026
                roster = MagicMock()

                with (
                    patch.object(
                        service, "get_league_data", return_value=fixture
                    ),
                    patch("leagues.integrations.espn.Teams"),
                    patch(
                        "leagues.integrations.espn.LeaguePlatformIdentity"
                    ) as league_ids,
                    patch(
                        "leagues.integrations.espn.RosterPlatformIdentity"
                    ) as roster_ids,
                    patch("leagues.integrations.espn.Player"),
                    patch(
                        "leagues.integrations.espn.PlayerPlatformIdentity"
                    ),
                    patch(
                        "leagues.integrations.espn.FantasyRosterPlayer"
                    ) as roster_players,
                    patch(
                        "leagues.integrations.espn.UserLeagueConnection"
                    ) as connections,
                ):
                    league_ids.objects.filter.return_value.select_related.return_value.first.return_value = (
                        MagicMock(league=league)
                    )

                    roster_ids.objects.filter.return_value.select_related.return_value.first.return_value = (
                        MagicMock(roster=roster)
                    )

                    result = service.import_league(
                        MagicMock(),
                        owned_team_id="1",
                    )

                    self.assertEqual(result["players_unresolved"], 1)
                    self.assertFalse(result["my_roster_complete"])
                    self.assertIs(result["my_roster"], roster)

                    roster_players.objects.filter.assert_not_called()
                    roster_players.objects.bulk_create.assert_not_called()
                    connections.objects.update_or_create.assert_not_called()


class ESPNScoringTests(unittest.TestCase):
    """Verify ESPN reception scoring normalization."""

    def test_standard_scoring(self):
        ppr, premium = ESPNLeagueService._scoring_details({
            "scoringSettings": {
                "scoringItems": [{"statId": 53, "points": 0}]
            }
        })
        self.assertEqual(ppr, 0.0)
        self.assertEqual(premium, 0.0)

    def test_half_ppr_scoring(self):
        ppr, premium = ESPNLeagueService._scoring_details({
            "scoringSettings": {
                "scoringItems": [{"statId": 53, "points": 0.5}]
            }
        })
        self.assertEqual(ppr, 0.5)
        self.assertEqual(premium, 0.0)

    def test_full_ppr_scoring(self):
        ppr, premium = ESPNLeagueService._scoring_details({
            "scoringSettings": {
                "scoringItems": [{"statId": 53, "points": 1}]
            }
        })
        self.assertEqual(ppr, 1.0)
        self.assertEqual(premium, 0.0)

    def test_missing_reception_scoring(self):
        ppr, premium = ESPNLeagueService._scoring_details({
            "scoringSettings": {"scoringItems": []}
        })
        self.assertIsNone(ppr)
        self.assertEqual(premium, 0.0)

    def test_ambiguous_reception_scoring(self):
        ppr, premium = ESPNLeagueService._scoring_details({
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 53, "points": 1},
                    {"statId": 53, "points": 1.5},
                ]
            }
        })
        self.assertIsNone(ppr)
        self.assertEqual(premium, 0.0)

    def test_invalid_scoring_values(self):
        ppr, premium = ESPNLeagueService._scoring_details({
            "scoringSettings": {
                "scoringItems": [
                    {"statId": 53, "points": "invalid"},
                    {"statId": "unknown", "points": 1},
                ]
            }
        })
        self.assertIsNone(ppr)
        self.assertEqual(premium, 0.0)



if __name__ == "__main__":
    unittest.main()


class ESPNLineupSlotMappingTests(unittest.TestCase):
    def setUp(self):
        self.service = ESPNLeagueService("123456", 2026)

    def test_standard_lineup_slots(self):
        expected = {
            0: "QB",
            2: "RB",
            4: "WR",
            6: "TE",
            16: "DEF",
            17: "K",
            20: "BN",
            21: "IR",
            23: "FLEX",
        }

        for slot_id, expected_slot in expected.items():
            with self.subTest(slot_id=slot_id):
                self.assertEqual(
                    self.service._lineup_slot_name(slot_id),
                    expected_slot,
                )

    def test_espn_op_slot_maps_to_super_flex(self):
        self.assertEqual(
            self.service._lineup_slot_name(7),
            "SUPER_FLEX",
        )

    def test_unknown_slot_defaults_to_bench(self):
        self.assertEqual(
            self.service._lineup_slot_name(99),
            "BN",
        )
