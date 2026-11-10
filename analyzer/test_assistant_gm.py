from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from analyzer import assistant_gm as gm


class DetectPositionTests(SimpleTestCase):
    def test_plural_and_phrase_forms(self):
        self.assertEqual(gm._detect_position("best waiver WRs?"), "WR")
        self.assertEqual(gm._detect_position("top tight ends this week"), "TE")
        self.assertEqual(gm._detect_position("best defense to stream"), "DST")

    def test_no_position(self):
        self.assertIsNone(gm._detect_position("how is my team doing"))


class ScoringNoteTests(SimpleTestCase):
    def test_note_only_for_non_ppr_league(self):
        self.assertEqual(gm._scoring_note(gm.ChatContext(league=SimpleNamespace(ppr=1))), "")
        self.assertIn("0.5", gm._scoring_note(gm.ChatContext(league=SimpleNamespace(ppr=0.5))))


class RoutingTests(SimpleTestCase):
    def test_which_is_not_a_greeting(self):
        ctx = gm.ChatContext(week=8, season=2026)
        with mock.patch.object(gm, "_build_context", return_value=ctx), \
             mock.patch.object(gm, "_find_players_in_question", return_value=[]), \
             mock.patch.object(gm, "_answer_my_lineup", return_value="LINEUP") as lineup:
            self.assertEqual(gm.answer_question("Which of my lineup should I change?"), "LINEUP")
            lineup.assert_called_once()


class ExplanationHelperTests(SimpleTestCase):
    def test_ordinal(self):
        self.assertEqual([gm._ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)],
                         ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"])

    def test_projected_line_skips_missing_and_zero(self):
        proj = SimpleNamespace(projected_stats={"receptions": 6.2, "receiving_yards": 78.4, "receiving_tds": 0})
        self.assertEqual(gm._projected_line(proj), "6.2 rec, 78 rec yds")
        self.assertEqual(gm._projected_line(SimpleNamespace(projected_stats={})), "")

    def test_form_note_direction(self):
        player = SimpleNamespace()
        with mock.patch.object(gm, "_recent_avg", return_value=12.0):
            self.assertIn("step up", gm._form_note(player, 16.0, None))
            self.assertIn("dip", gm._form_note(player, 8.0, None))
            self.assertIn("in line", gm._form_note(player, 12.5, None))


class FollowUpTests(SimpleTestCase):
    STATE = {"last_question": "compare Tyreek Hill and Davante Adams", "topic": "compare",
             "players": ["Tyreek Hill", "Davante Adams"], "week": 7, "league_id": None}

    def resolve(self, q, state=None, found=None):
        with mock.patch.object(gm, "_find_players_in_question", return_value=found or []):
            return gm._resolve_follow_up(q, self.STATE if state is None else state)

    def test_no_state_is_unchanged(self):
        self.assertEqual(self.resolve("why?", state={}), ("why?", False, None))

    def test_why_reruns_last_question_with_detail(self):
        self.assertEqual(self.resolve("why?"), (self.STATE["last_question"], True, None))

    def test_new_question_starting_with_why_and_a_name_is_not_expand(self):
        resolved, detail, _ = self.resolve("why should I start Henry", found=[object()])
        self.assertFalse(detail)

    def test_next_week_rewrites_last_question(self):
        resolved, detail, _ = self.resolve("what about next week?")
        self.assertEqual(resolved, "compare Tyreek Hill and Davante Adams week 8")

    def test_explicit_week_replaces_old_week(self):
        state = dict(self.STATE, last_question="top projected RBs week 7")
        resolved, _, _ = self.resolve("week 10", state=state)
        self.assertEqual(resolved, "top projected RBs week 10")

    def test_singular_pronoun_with_two_players_asks_which(self):
        _, _, clarification = self.resolve("what is his matchup?")
        self.assertIn("Tyreek Hill or Davante Adams", clarification)

    def test_pronoun_with_one_player_appends_name(self):
        state = dict(self.STATE, topic="player", players=["Tyreek Hill"])
        resolved, _, _ = self.resolve("how has he done recently?", state=state)
        self.assertEqual(resolved, "how has he done recently? Tyreek Hill")

    def test_position_swap_after_top_list(self):
        state = {"last_question": "top projected RBs", "topic": "top", "players": [], "week": 7}
        resolved, _, _ = self.resolve("what about TEs?", state=state)
        self.assertEqual(resolved, "top projected TEs")


class ReasonLimitTests(SimpleTestCase):
    def test_default_limit_truncates_and_flags(self):
        ctx = gm.ChatContext()
        note = {"tier": "favorable", "text": "matchup text", "rank": 3}
        projection = SimpleNamespace(projected_stats={"receptions": 6.0})
        with mock.patch.object(gm, "_matchup_note", return_value=note), \
             mock.patch.object(gm, "_form_parts", return_value=("form text", True)):
            shown = gm._reasons(SimpleNamespace(), projection, 15.0, ctx, limit=2)
        self.assertEqual(shown, ["matchup text", "form text"])
        self.assertTrue(ctx.cache["truncated"])

    def test_detail_returns_everything(self):
        ctx = gm.ChatContext(detail=True)
        note = {"tier": "neutral", "text": "matchup text", "rank": 15}
        projection = SimpleNamespace(projected_stats={"receptions": 6.0})
        with mock.patch.object(gm, "_matchup_note", return_value=note), \
             mock.patch.object(gm, "_form_parts", return_value=("form text", False)):
            shown = gm._reasons(SimpleNamespace(), projection, 15.0, ctx, limit=1)
        self.assertEqual(len(shown), 3)


def _item(rp_id, name, pos, pts):
    return {"roster_player": SimpleNamespace(id=rp_id),
            "player": SimpleNamespace(full_name=name, position=pos, team_id=rp_id, injury_status=""),
            "prediction": SimpleNamespace(projected_fantasy_points=pts)}


class PairSwapTests(SimpleTestCase):
    def test_slot_reshuffles_are_not_swaps(self):
        wr1, wr2, flex = _item(1, "A", "WR", 18), _item(2, "B", "WR", 15), _item(3, "C", "WR", 12)
        current = [{"slot": "WR", "item": wr1}, {"slot": "WR", "item": wr2}, {"slot": "FLEX", "item": flex}]
        optimized = [{"slot": "WR", "item": wr2}, {"slot": "WR", "item": flex}, {"slot": "FLEX", "item": wr1}]
        self.assertEqual(gm._pair_swaps(current, optimized), [])

    def test_real_swaps_pair_by_position(self):
        qb_out, qb_in = _item(1, "Stafford", "QB", 0), _item(2, "Shough", "QB", 16.9)
        te_out, rb_in = _item(3, "Kraft", "TE", 11.2), _item(4, "Cook", "RB", 14.2)
        current = [{"slot": "QB", "item": qb_out}, {"slot": "FLEX", "item": te_out}]
        optimized = [{"slot": "QB", "item": qb_in}, {"slot": "FLEX", "item": rb_in}]
        pairs = gm._pair_swaps(current, optimized)
        self.assertEqual([(i["player"].full_name, o["player"].full_name) for i, o in pairs],
                         [("Shough", "Stafford"), ("Cook", "Kraft")])


class LineupWarningTests(SimpleTestCase):
    def test_zero_projection_gets_reason(self):
        item = _item(1, "Stafford", "QB", 0.0)
        item["player"].injury_status = "Out"
        with mock.patch.object(gm, "_opponent_info", return_value=None):
            out = gm._lineup_warnings([{"slot": "QB", "item": item}], gm.ChatContext())
        self.assertEqual(len(out), 1)
        self.assertIn("listed as Out", out[0])

    def test_bye_reason(self):
        item = _item(1, "Stafford", "QB", 0.0)
        with mock.patch.object(gm, "_opponent_info", return_value={"bye": True}):
            out = gm._lineup_warnings([{"slot": "QB", "item": item}], gm.ChatContext())
        self.assertIn("bye", out[0])

    def test_healthy_starter_no_warning(self):
        item = _item(1, "Cook", "RB", 14.2)
        self.assertEqual(gm._lineup_warnings([{"slot": "RB", "item": item}], gm.ChatContext()), [])


class ESPNConnectionSwitchTests(SimpleTestCase):
    def test_switching_espn_teams_resets_chat_state(self):
        league = SimpleNamespace(pk=9)
        cream_city = SimpleNamespace(pk=14, league=league)
        bad_girly = SimpleNamespace(pk=15, league=league)

        old_state = {
            "last_question": "compare Player A and Player B",
            "topic": "compare",
            "players": ["Player A", "Player B"],
            "week": 9,
            "league_id": 9,
            "connection_id": 14,
        }

        def route(question, user, selected_league, detail=False, connection=None):
            self.assertEqual(question, "who is my opponent?")
            self.assertIs(selected_league, league)
            self.assertIs(connection, bad_girly)
            return (
                "Bad Girly matchup",
                "matchup",
                [],
                gm.ChatContext(league=league, connection=connection, week=10),
            )

        with mock.patch.object(gm, "_route", side_effect=route) as mocked_route:
            answer, state = gm.answer_with_state(
                "who is my opponent?",
                league=league,
                connection=bad_girly,
                state=old_state,
            )

        self.assertEqual(answer, "Bad Girly matchup")
        self.assertEqual(state["connection_id"], 15)
        self.assertEqual(state["league_id"], 9)
        self.assertEqual(state["last_question"], "who is my opponent?")
        mocked_route.assert_called_once()

class ESPNAssistantGMRosterTests(SimpleTestCase):
    def test_two_espn_connections_use_different_rosters(self):
        league = SimpleNamespace(pk=9, season=2026)
        connections = [
            SimpleNamespace(pk=14, league_id=9, external_user_id="12345:2026:7"),
            SimpleNamespace(pk=15, league_id=9, external_user_id="12345:2026:8"),
        ]

        def make_roster(name):
            player = SimpleNamespace(
                id=1, full_name=name, position="QB", team_id=1
            )
            entry = SimpleNamespace(
                player=player, player_id=1, team=None, team_id=None
            )
            roster_players = mock.MagicMock()
            roster_players.select_related.return_value = [entry]
            return SimpleNamespace(roster_players=roster_players)

        rosters = {
            "12345:2026:7": make_roster("Cream City QB"),
            "12345:2026:8": make_roster("Bad Girly QB"),
        }

        def resolve(connection):
            return rosters[connection.external_user_id]

        with (
            mock.patch(
                "leagues.services.roster_identity.resolve_connection_roster",
                side_effect=resolve,
            ) as resolver,
            mock.patch(
                "leagues.models.FantasyProjection.objects.select_related"
            ) as projections,
            mock.patch(
                "leagues.models.DefenseProjection.objects.filter"
            ) as defenses,
        ):
            projections.return_value.filter.return_value = []
            defenses.return_value = []

            names = []
            for connection in connections:
                ctx = gm.ChatContext(
                    league=league,
                    connection=connection,
                    season=2026,
                    week=10,
                )
                items = gm._my_roster_items(ctx)
                names.append(items[0]["player"].full_name)

        self.assertEqual(names, ["Cream City QB", "Bad Girly QB"])
        self.assertEqual(resolver.call_count, 2)


class ESPNAssistantGMMatchupTests(SimpleTestCase):
    def test_two_espn_teams_have_different_matchups(self):
        league = SimpleNamespace(pk=9, season=2026)
        connections = [
            SimpleNamespace(pk=14, external_user_id="12345:2026:7"),
            SimpleNamespace(pk=15, external_user_id="12345:2026:8"),
        ]
        rosters = {
            "12345:2026:7": SimpleNamespace(id=80),
            "12345:2026:8": SimpleNamespace(id=81),
        }
        opponents = {
            80: SimpleNamespace(id=90, owner_name="Opponent A"),
            81: SimpleNamespace(id=91, owner_name="Opponent B"),
        }
        points = {80: 120, 81: 135, 90: 110, 91: 140}

        def matchup_filter(**kwargs):
            roster = kwargs["roster"]
            result = mock.MagicMock()
            result.select_related.return_value.first.return_value = (
                SimpleNamespace(opponent=opponents[roster.id])
            )
            return result

        def projection_filter(**kwargs):
            result = mock.MagicMock()
            result.order_by.return_value.first.return_value = (
                SimpleNamespace(projected_points=points[kwargs["roster"].id])
            )
            return result

        with (
            mock.patch(
                "leagues.services.roster_identity.resolve_connection_roster",
                side_effect=lambda c: rosters[c.external_user_id],
            ),
            mock.patch(
                "leagues.models.FantasyMatchup.objects.filter",
                side_effect=matchup_filter,
            ) as matchups,
            mock.patch(
                "leagues.models.TeamWeekProjection.objects.filter",
                side_effect=projection_filter,
            ),
        ):
            answers = [
                gm._answer_matchup(
                    gm.ChatContext(
                        league=league, connection=c, season=2026, week=10
                    )
                )
                for c in connections
            ]

        self.assertIn("Opponent A", answers[0])
        self.assertIn("120.0", answers[0])
        self.assertIn("Opponent B", answers[1])
        self.assertIn("135.0", answers[1])
        self.assertEqual(matchups.call_count, 2)
