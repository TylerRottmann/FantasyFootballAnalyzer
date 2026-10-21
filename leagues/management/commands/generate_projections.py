from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from analyzer.models import Teams
from leagues.models import DefenseProjection, FantasyProjection, Player
from scripts.algorithm.predictor import predict_defense, predict_player
from scripts.algorithm.k.feature_names import TARGETS as K_TARGETS


MODEL_VERSION = "v1"
POSITIONS = ["QB", "RB", "WR", "TE", "K"]


class Command(BaseCommand):
    help = "Generate PPR skill-position, reference kicker, and defense projections."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, required=True)
        parser.add_argument("--week", type=int)
        parser.add_argument(
            "--all-weeks",
            action="store_true",
            help="Generate projections for all 18 weeks.",
        )

    def handle(self, *args, **options):
        season = options["season"]
        week = options["week"]
        all_weeks = options["all_weeks"]

        if all_weeks and week is not None:
            raise CommandError(
                "Use either --week or --all-weeks, not both."
            )

        if all_weeks:
            weeks = range(1, 19)
        elif week is not None:
            if not 1 <= week <= 18:
                raise CommandError("Week must be between 1 and 18.")
            weeks = [week]
        else:
            raise CommandError(
                "You must provide either --week or --all-weeks."
            )

        # Load players and their teams in one query.
        players = list(
            Player.objects.filter(
                position__in=POSITIONS
            ).order_by("id")
        )

        if not players:
            self.stdout.write(
                self.style.WARNING("No eligible players found.")
            )
            return

        # Separate players based on whether they have a team.
        players_with_team = [
            player for player in players
            if player.team_id is not None
        ]

        players_without_team = [
            player for player in players
            if player.team_id is None
        ]

        self.stdout.write(f"Total players: {len(players)}")
        self.stdout.write(
            f"Players with a team: {len(players_with_team)}"
        )
        self.stdout.write(
            f"Players without a team: {len(players_without_team)}"
        )

        total_saved = 0
        total_zeroed = 0
        total_skipped = 0
        total_failed = 0

        for current_week in weeks:
            close_old_connections()

            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"========== WEEK {current_week} =========="
                )
            )

            week_saved = 0
            week_zeroed = 0
            week_skipped = 0
            week_failed = 0

            # Players without a team get 0.0 without prediction.
            for player in players_without_team:
                try:
                    FantasyProjection.objects.update_or_create(
                        player=player,
                        season=season,
                        week=current_week,
                        model_version=MODEL_VERSION,
                        defaults={
                            "projected_fantasy_points": 0.0,
                            "status": "inactive",
                            "projected_stats": dict.fromkeys(K_TARGETS, 0) if player.position == "K" else {},
                        },
                    )
                    week_zeroed += 1

                except Exception as exc:
                    week_failed += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Failed to zero projection for "
                            f"{player.full_name}: {exc}"
                        )
                    )

            # Only run the predictor for players assigned to a team.
            for player in players_with_team:
                try:
                    prediction = predict_player(
                        player.id,
                        season,
                        current_week,
                    )

                    if prediction is None:
                        week_skipped += 1
                        continue

                    projected_points = prediction.get(
                        "projected_fantasy_points"
                    )

                    if projected_points is None:
                        week_skipped += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping {player.full_name}: "
                                "no projected points returned."
                            )
                        )
                        continue

                    FantasyProjection.objects.update_or_create(
                        player=player,
                        season=season,
                        week=current_week,
                        model_version=MODEL_VERSION,
                        defaults={
                            "projected_fantasy_points": float(
                                projected_points
                            ),
                            "projected_stats": prediction.get("projected_stats", {}),
                            "status": prediction.get(
                                "status",
                                "projected",
                            ),
                        },
                    )

                    week_saved += 1

                except Exception as exc:
                    week_failed += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Failed for {player.full_name} "
                            f"({player.position}), "
                            f"season {season}, week {current_week}: {exc}"
                        )
                    )

            # --------------------------------------------------
            # D/ST: defenses are teams, so they are projected per
            # team and saved to DefenseProjection.
            # --------------------------------------------------
            for team in Teams.objects.filter(is_active=True).order_by("id"):
                try:
                    prediction = predict_defense(
                        team.id,
                        season,
                        current_week,
                    )

                    projected_points = prediction.get(
                        "projected_fantasy_points"
                    )

                    if projected_points is None:
                        week_skipped += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping {team.abbreviation} D/ST: "
                                f"{prediction.get('status')}."
                            )
                        )
                        continue

                    DefenseProjection.objects.update_or_create(
                        team=team,
                        season=season,
                        week=current_week,
                        model_version=MODEL_VERSION,
                        defaults={
                            "projected_fantasy_points": float(
                                projected_points
                            ),
                            "status": prediction.get("status", "projected"),
                        },
                    )

                    week_saved += 1

                except Exception as exc:
                    week_failed += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Failed for {team.abbreviation} D/ST, "
                            f"season {season}, week {current_week}: {exc}"
                        )
                    )

            total_saved += week_saved
            total_zeroed += week_zeroed
            total_skipped += week_skipped
            total_failed += week_failed

            self.stdout.write(
                self.style.SUCCESS(
                    f"Week {current_week}: "
                    f"{week_saved} projected, "
                    f"{week_zeroed} zeroed, "
                    f"{week_skipped} skipped, "
                    f"{week_failed} failed."
                )
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("Projection generation finished.")
        )
        self.stdout.write(f"Projected: {total_saved}")
        self.stdout.write(f"Zeroed: {total_zeroed}")
        self.stdout.write(f"Skipped: {total_skipped}")
        self.stdout.write(f"Failed: {total_failed}")