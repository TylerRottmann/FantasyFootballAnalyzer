"""Build persisted league-specific player ranks for profile views."""

from collections import defaultdict
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from analyzer.market import (
    PLAYER_POSITIONS,
    _market_recommendation,
    _score_our_defense_projection,
    _score_our_player_projection,
    _score_sleeper_projection,
)
from analyzer.models import PlayerMarketProjection, PlayerMarketRank, Players, Teams
from leagues.models import DefenseProjection, FantasyLeague, FantasyProjection


MODEL_VERSION = "v2_stat"


def _rank_values(points, entities):
    """Return dense overall and within-position ranks for available scores."""
    ordered_keys = sorted(
        points,
        key=lambda key: (
            -points[key],
            entities[key]["name"].casefold(),
            key,
        ),
    )
    overall = {key: rank for rank, key in enumerate(ordered_keys, start=1)}
    by_position = defaultdict(list)
    for key in ordered_keys:
        by_position[entities[key]["position"]].append(key)
    positional = {
        key: rank
        for keys in by_position.values()
        for rank, key in enumerate(keys, start=1)
    }
    return overall, positional


def _rest_of_season(points_by_entity, week):
    """Sum saved weekly scores only when every remaining week is available."""
    required_weeks = range(week, 19)
    totals = {}
    for entity_key, weekly in points_by_entity.items():
        if all(target_week in weekly for target_week in required_weeks):
            totals[entity_key] = round(
                sum(weekly[target_week] for target_week in range(week, 19)), 4
            )
    return totals


class Command(BaseCommand):
    help = (
        "Refresh league-specific weekly and rest-of-season player ranks. "
        "Run after generating model projections or importing Sleeper data."
    )

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=date.today().year)
        parser.add_argument(
            "--weeks",
            nargs="+",
            type=int,
            default=None,
            help="Weeks to snapshot (default: all regular-season weeks).",
        )
        parser.add_argument(
            "--league-ids",
            nargs="+",
            type=int,
            default=None,
            help="Limit refresh to selected FantasyLeague database IDs.",
        )

    def handle(self, *args, **options):
        season = options["season"]
        weeks = tuple(dict.fromkeys(options["weeks"] or range(1, 19)))
        if not 2000 <= season <= 2100:
            raise CommandError("Season must be between 2000 and 2100.")
        if any(week < 1 or week > 18 for week in weeks):
            raise CommandError("Weeks must be between 1 and 18.")

        leagues = FantasyLeague.objects.all().order_by("id")
        if options["league_ids"]:
            leagues = leagues.filter(id__in=options["league_ids"])
        leagues = list(leagues)
        if not leagues:
            self.stdout.write(self.style.WARNING("No leagues found; no market ranks were refreshed."))
            return

        players = list(
            Players.objects.filter(position__in=PLAYER_POSITIONS)
            .exclude(full_name__isnull=True)
            .exclude(full_name="")
            .values("id", "position", "full_name")
        )
        teams = list(
            Teams.objects.filter(is_active=True).values("id", "name", "abbreviation")
        )
        entities = {
            f"player:{player['id']}": {
                "player_id": player["id"],
                "position": player["position"],
                "name": player["full_name"],
            }
            for player in players
        }
        for team in teams:
            entities[f"team:{team['id']}"] = {
                "player_id": None,
                "position": "DST",
                "name": f"{team['name']} D/ST",
            }
        player_ids = [player["id"] for player in players]
        team_ids = [team["id"] for team in teams]

        player_projections = FantasyProjection.objects.filter(
            player_id__in=player_ids,
            season=season,
            week__gte=1,
            week__lte=18,
            model_version=MODEL_VERSION,
        ).select_related("player")
        defense_projections = DefenseProjection.objects.filter(
            team_id__in=team_ids,
            season=season,
            week__gte=1,
            week__lte=18,
            model_version=MODEL_VERSION,
        ).select_related("team")
        # The scoring depends on the league, so retain raw projection rows and
        # score them separately for each league below.
        player_projection_rows = list(player_projections)
        defense_projection_rows = list(defense_projections)
        sleeper_rows = list(PlayerMarketProjection.objects.filter(
            season=season,
            week__gte=1,
            week__lte=18,
        ).filter(
            Q(player_id__in=player_ids) | Q(team_id__in=team_ids)
        ))

        total_saved = 0
        for league in leagues:
            league_our_weekly = defaultdict(dict)
            for projection in player_projection_rows:
                entity_key = f"player:{projection.player_id}"
                points = _score_our_player_projection(projection, league)
                if points is not None:
                    league_our_weekly[entity_key][projection.week] = points
            for projection in defense_projection_rows:
                entity_key = f"team:{projection.team_id}"
                points = _score_our_defense_projection(projection, league)
                if points is not None:
                    league_our_weekly[entity_key][projection.week] = points

            league_sleeper_weekly = defaultdict(dict)
            for source in sleeper_rows:
                entity_key = (
                    f"player:{source.player_id}"
                    if source.player_id else f"team:{source.team_id}"
                )
                points = _score_sleeper_projection(source, league)
                if points is not None:
                    league_sleeper_weekly[entity_key][source.week] = points

            snapshots = []
            for week in weeks:
                weekly_our_points = {
                    key: values[week]
                    for key, values in league_our_weekly.items()
                    if week in values
                }
                weekly_our_overall, weekly_our_position = _rank_values(
                    weekly_our_points, entities
                )

                our_ros_points = _rest_of_season(league_our_weekly, week)
                sleeper_ros_points = _rest_of_season(league_sleeper_weekly, week)
                our_ros_overall, our_ros_position = _rank_values(our_ros_points, entities)
                _, sleeper_ros_position = _rank_values(sleeper_ros_points, entities)

                for player in players:
                    entity_key = f"player:{player['id']}"
                    our_rank = our_ros_overall.get(entity_key)
                    our_position_rank = our_ros_position.get(entity_key)
                    sleeper_position_rank = sleeper_ros_position.get(entity_key)
                    snapshots.append(PlayerMarketRank(
                        league_id=league.id,
                        player_id=player["id"],
                        season=season,
                        week=week,
                        weekly_overall_rank=weekly_our_overall.get(entity_key),
                        weekly_position_rank=weekly_our_position.get(entity_key),
                        rest_of_season_overall_rank=our_rank,
                        rest_of_season_position_rank=our_position_rank,
                        sleeper_rest_of_season_position_rank=sleeper_position_rank,
                        market_signal=_market_recommendation(
                            our_position_rank, sleeper_position_rank
                        ) or "",
                    ))

            if snapshots:
                with transaction.atomic():
                    PlayerMarketRank.objects.bulk_create(
                        snapshots,
                        batch_size=1000,
                        update_conflicts=True,
                        unique_fields=["league_id", "player", "season", "week"],
                        update_fields=[
                            "weekly_overall_rank",
                            "weekly_position_rank",
                            "rest_of_season_overall_rank",
                            "rest_of_season_position_rank",
                            "sleeper_rest_of_season_position_rank",
                            "market_signal",
                            "updated_at",
                        ],
                    )
                total_saved += len(snapshots)
            self.stdout.write(
                f"{league.name}: prepared {len(snapshots)} player rank snapshots."
            )

        self.stdout.write(self.style.SUCCESS(
            f"Refreshed {total_saved} league/player/week rank snapshots for {season}."
        ))
