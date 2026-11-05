from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from analyzer.models import PlayerADP, Players


API_URL = "https://api.sleeper.com/projections/nfl/{season}"

FORMATS = {
    "ppr": "adp_ppr",
    "half_ppr": "adp_half_ppr",
    "std": "adp_std",
}

POSITIONS = {"QB", "RB", "WR", "K"}

MINIMUM_EXISTING_COVERAGE = Decimal("0.80")


def valid_adp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

    if not number.is_finite() or not (Decimal("0") < number < Decimal("999")):
        return None

    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Import fantasy football ADP rankings from Sleeper."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=2026)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        season = options["season"]
        dry_run = options["dry_run"]

        if not 2000 <= season <= 2100:
            raise CommandError("Season must be between 2000 and 2100.")

        try:
            response = requests.get(
                API_URL.format(season=season),
                params={"season_type": "regular"},
                timeout=45,
            )
            response.raise_for_status()
            records = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f"Sleeper ADP request failed: {exc}") from exc

        if not isinstance(records, list) or not records:
            raise CommandError("Sleeper returned no usable player records.")

        sleeper_ids = {
            str(record["player_id"])
            for record in records
            if isinstance(record, dict) and record.get("player_id") is not None
        }

        player_lookup = dict(
            Players.objects.filter(
                sleeper_id__in=sleeper_ids,
                position__in=POSITIONS,
            ).values_list("sleeper_id", "id")
        )

        prepared = {}
        unmatched = set()

        for record in records:
            if not isinstance(record, dict):
                continue

            sleeper_id = str(record.get("player_id"))
            player_id = player_lookup.get(sleeper_id)

            if player_id is None:
                unmatched.add(sleeper_id)
                continue

            stats = record.get("stats") or {}
            if not isinstance(stats, dict):
                continue

            for scoring_format, field in FORMATS.items():
                adp = valid_adp(stats.get(field))
                if adp is None:
                    continue

                key = (player_id, scoring_format)
                if key in prepared:
                    raise CommandError(
                        f"Duplicate ADP entry for player {player_id}, "
                        f"format {scoring_format}."
                    )

                prepared[key] = adp

        if not prepared:
            raise CommandError(
                "No valid ADP rankings found. Existing data was not changed."
            )

        existing_count = PlayerADP.objects.filter(
            season=season,
            source="sleeper",
        ).count()

        if existing_count:
            minimum_count = int(
                existing_count * MINIMUM_EXISTING_COVERAGE
            )
            if len(prepared) < minimum_count:
                raise CommandError(
                    f"Refusing incomplete refresh: received "
                    f"{len(prepared)} rankings; expected at least "
                    f"{minimum_count} based on existing data. "
                    f"Existing rankings were preserved."
                )

        counts = {
            scoring_format: sum(
                fmt == scoring_format for _, fmt in prepared
            )
            for scoring_format in FORMATS
        }

        self.stdout.write(
            f"Season: {season} | API records: {len(records)} | "
            f"Matched players: {len(player_lookup)} | "
            f"Unmatched IDs: {len(unmatched)}"
        )

        for scoring_format, count in counts.items():
            self.stdout.write(f"{scoring_format}: {count} valid rankings")

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "DRY RUN complete. No database changes were made."
                )
            )
            return

        now = timezone.now()

        rows = [
            PlayerADP(
                player_id=player_id,
                season=season,
                scoring_format=scoring_format,
                adp=adp,
                source="sleeper",
                updated_at=now,
            )
            for (player_id, scoring_format), adp in prepared.items()
        ]

        with transaction.atomic():
            PlayerADP.objects.bulk_create(
                rows,
                batch_size=500,
                update_conflicts=True,
                unique_fields=[
                    "player",
                    "season",
                    "scoring_format",
                ],
                update_fields=[
                    "adp",
                    "source",
                    "updated_at",
                ],
            )

            stale_deleted = 0

            for scoring_format in FORMATS:
                current_ids = {
                    player_id
                    for player_id, fmt in prepared
                    if fmt == scoring_format
                }

                deleted, _ = (
                    PlayerADP.objects.filter(
                        season=season,
                        source="sleeper",
                        scoring_format=scoring_format,
                    )
                    .exclude(player_id__in=current_ids)
                    .delete()
                )

                stale_deleted += deleted

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported or updated {len(prepared)} ADP rankings. "
                f"Removed {stale_deleted} stale player rankings."
            )
        )
