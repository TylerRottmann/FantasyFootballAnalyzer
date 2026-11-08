"""Import weekly Sleeper projections and recompute rest-of-season totals."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from analyzer.models import PlayerMarketProjection, Players, Teams


API_URL = "https://api.sleeper.com/projections/nfl/{season}/{week}"
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
SLEEPER_POSITION = {"DST": "DEF"}
POINT_FIELDS = {
    "sleeper_ppr": "pts_ppr",
    "sleeper_half_ppr": "pts_half_ppr",
    "sleeper_standard": "pts_std",
}
ROS_FIELDS = {
    "sleeper_ppr": "rest_of_season_ppr",
    "sleeper_half_ppr": "rest_of_season_half_ppr",
    "sleeper_standard": "rest_of_season_standard",
}


def _projection_value(value):
    """Convert a Sleeper points value to a finite, three-decimal number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _json_stats(stats):
    """Keep finite numeric projection statistics safe for JSON storage."""
    if not isinstance(stats, dict):
        return {}
    clean = {}
    for key, value in stats.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            clean[str(key)] = value
        elif isinstance(value, float) and math.isfinite(value):
            clean[str(key)] = value
    return clean


def _recalculate_rest_of_season(season, positions):
    """Refresh each saved week's cumulative projection through Week 18."""
    rows = list(
        PlayerMarketProjection.objects.filter(
            season=season,
            position__in=positions,
        ).order_by("entity_key", "-week")
    )
    totals = defaultdict(lambda: {field: Decimal("0") for field in POINT_FIELDS})
    now = timezone.now()

    for row in rows:
        running = totals[row.entity_key]
        for point_field, ros_field in ROS_FIELDS.items():
            running[point_field] += getattr(row, point_field)
            setattr(row, ros_field, running[point_field])
        row.updated_at = now

    if rows:
        PlayerMarketProjection.objects.bulk_update(
            rows,
            [*ROS_FIELDS.values(), "updated_at"],
            batch_size=1000,
        )
    return len(rows)


class Command(BaseCommand):
    help = (
        "Import Sleeper weekly player projections. Defaults to all supported "
        "positions and Weeks 1-18. Missing player projections are stored as 0."
    )

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=date.today().year)
        parser.add_argument(
            "--positions",
            nargs="+",
            choices=POSITIONS,
            default=None,
            help="Positions to refresh (default: QB RB WR TE K DST).",
        )
        parser.add_argument(
            "--weeks",
            nargs="+",
            type=int,
            default=None,
            help="Regular-season weeks to refresh (default: 1-18).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and validate data without writing to the database.",
        )

    def handle(self, *args, **options):
        season = options["season"]
        positions = tuple(dict.fromkeys(options["positions"] or POSITIONS))
        weeks = tuple(dict.fromkeys(options["weeks"] or range(1, 19)))
        dry_run = options["dry_run"]

        if not 2000 <= season <= 2100:
            raise CommandError("Season must be between 2000 and 2100.")
        if any(week < 1 or week > 18 for week in weeks):
            raise CommandError("Weeks must be between 1 and 18.")

        player_rows = list(
            Players.objects.filter(position__in=positions)
            .values_list("id", "sleeper_id", "position")
        )
        players_by_sleeper_id = {
            str(sleeper_id): (player_id, position)
            for player_id, sleeper_id, position in player_rows
            if sleeper_id
        }
        teams_by_abbreviation = {
            abbreviation.upper(): (team_id, abbreviation.upper())
            for team_id, abbreviation in Teams.objects.filter(is_active=True)
            .values_list("id", "abbreviation")
        }

        if not player_rows and any(position != "DST" for position in positions):
            raise CommandError("No local players were found for these positions.")
        if "DST" in positions and not teams_by_abbreviation:
            raise CommandError("No active NFL teams were found for D/ST import.")

        self.stdout.write(
            f"Season {season}; positions {', '.join(positions)}; "
            f"weeks {', '.join(map(str, weeks))}."
        )

        prepared = []
        rows_by_week = {}
        api_counts = defaultdict(int)
        unmatched = set()
        source_records = 0

        # Fetch and validate every requested response before writing any rows.
        # A failed request therefore cannot erase a successful existing snapshot.
        for week in weeks:
            params = [("season_type", "regular")]
            params.extend(
                ("position[]", SLEEPER_POSITION.get(position, position))
                for position in positions
            )
            try:
                response = requests.get(
                    API_URL.format(season=season, week=week),
                    params=params,
                    headers={"User-Agent": "FantasyFootballAnalyzer/1.0"},
                    timeout=45,
                )
                response.raise_for_status()
                records = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise CommandError(
                    f"Sleeper projection request failed for Week {week}: {exc}"
                ) from exc

            if not isinstance(records, list) or not records:
                raise CommandError(
                    f"Sleeper returned no projection records for Week {week}; "
                    "existing database rows were preserved."
                )

            source_records += len(records)
            week_prepared = {}

            # Seed all known players and active teams with zero. Valid Sleeper
            # projection records below overwrite these values.
            for player_id, sleeper_id, position in player_rows:
                external_id = str(sleeper_id or f"local-{player_id}")
                entity_key = f"player:{player_id}"
                week_prepared[(entity_key, position)] = {
                    "entity_key": entity_key,
                    "external_id": external_id,
                    "player_id": player_id,
                    "team_id": None,
                    "position": position,
                    "season": season,
                    "week": week,
                    "sleeper_ppr": Decimal("0"),
                    "sleeper_half_ppr": Decimal("0"),
                    "sleeper_standard": Decimal("0"),
                    "projected_stats": {},
                    "projection_available": False,
                    "source_provider": "",
                }

            if "DST" in positions:
                for team_id, abbreviation in teams_by_abbreviation.values():
                    entity_key = f"team:{team_id}"
                    week_prepared[(entity_key, "DST")] = {
                        "entity_key": entity_key,
                        "external_id": abbreviation,
                        "player_id": None,
                        "team_id": team_id,
                        "position": "DST",
                        "season": season,
                        "week": week,
                        "sleeper_ppr": Decimal("0"),
                        "sleeper_half_ppr": Decimal("0"),
                        "sleeper_standard": Decimal("0"),
                        "projected_stats": {},
                        "projection_available": False,
                        "source_provider": "",
                    }

            for record in records:
                if not isinstance(record, dict):
                    continue
                source_position = str(
                    (record.get("player") or {}).get("position")
                    or record.get("position")
                    or ""
                ).upper()
                position = "DST" if source_position == "DEF" else source_position
                if position not in positions:
                    continue
                if record.get("season_type", "regular") != "regular":
                    continue
                try:
                    record_week = int(record.get("week", week))
                except (TypeError, ValueError):
                    continue
                if record_week != week:
                    continue

                stats = record.get("stats") or {}
                if not isinstance(stats, dict):
                    continue
                point_values = {
                    field: _projection_value(stats.get(source_field))
                    for field, source_field in POINT_FIELDS.items()
                }
                if not any(value is not None for value in point_values.values()):
                    # Sleeper also returns ADP-only records on this endpoint;
                    # they are already represented by the seeded zero row.
                    continue

                if position == "DST":
                    external_id = str(
                        record.get("player_id")
                        or record.get("team")
                        or (record.get("player") or {}).get("team")
                        or ""
                    ).upper()
                    if external_id == "LA":
                        external_id = "LAR"
                    team_identity = teams_by_abbreviation.get(external_id)
                    if team_identity is None:
                        unmatched.add(f"DST:{external_id}")
                        continue
                    team_id, abbreviation = team_identity
                    entity_key = f"team:{team_id}"
                    identity = (entity_key, "DST")
                    external_id = abbreviation
                    player_id = None
                else:
                    external_id = str(record.get("player_id") or "")
                    player_identity = players_by_sleeper_id.get(external_id)
                    if player_identity is None:
                        unmatched.add(f"{position}:{external_id}")
                        continue
                    player_id, local_position = player_identity
                    if local_position != position:
                        unmatched.add(f"{position}:{external_id}")
                        continue
                    entity_key = f"player:{player_id}"
                    identity = (entity_key, position)
                    team_id = None

                existing = week_prepared.get(identity)
                if existing is None:
                    continue

                if existing["projection_available"]:
                    raise CommandError(
                        f"Duplicate Sleeper projection for {position} "
                        f"{external_id} in Week {week}."
                    )

                existing.update({
                    "external_id": external_id,
                    "player_id": player_id,
                    "team_id": team_id,
                    "sleeper_ppr": point_values["sleeper_ppr"] or Decimal("0"),
                    "sleeper_half_ppr": (
                        point_values["sleeper_half_ppr"] or Decimal("0")
                    ),
                    "sleeper_standard": (
                        point_values["sleeper_standard"] or Decimal("0")
                    ),
                    "projected_stats": _json_stats(stats),
                    "projection_available": True,
                    "source_provider": str(record.get("company") or "")[:50],
                })
                api_counts[position] += 1

            # Keep one row for every entity in every requested week. The
            # database upsert is unique by entity, season, and week; using a
            # list here prevents snapshots from different weeks overwriting
            # each other in memory before they reach the database.
            prepared.extend(week_prepared.values())
            rows_by_week[week] = len(week_prepared)

        self.stdout.write(
            f"Sleeper records received: {source_records}; "
            f"database rows prepared: {len(prepared)} across "
            f"{len(rows_by_week)} weeks."
        )
        self.stdout.write(
            "Rows per week: " + ", ".join(
                f"{week}={rows_by_week[week]}" for week in sorted(rows_by_week)
            )
        )
        for position in positions:
            self.stdout.write(
                f"{position}: {api_counts[position]} matched projections; "
                f"missing projections will be stored as 0."
            )
        if unmatched:
            self.stdout.write(
                f"Unmatched Sleeper identities: {len(unmatched)}."
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                "DRY RUN complete. No database changes were made."
            ))
            return

        now = timezone.now()
        rows = [
            PlayerMarketProjection(
                entity_key=data["entity_key"],
                external_id=data["external_id"],
                player_id=data["player_id"],
                team_id=data["team_id"],
                position=data["position"],
                season=data["season"],
                week=data["week"],
                sleeper_ppr=data["sleeper_ppr"],
                sleeper_half_ppr=data["sleeper_half_ppr"],
                sleeper_standard=data["sleeper_standard"],
                projected_stats=data["projected_stats"],
                projection_available=data["projection_available"],
                source="sleeper",
                source_provider=data["source_provider"],
                updated_at=now,
            )
            for data in prepared
        ]

        try:
            with transaction.atomic():
                PlayerMarketProjection.objects.bulk_create(
                    rows,
                    batch_size=1000,
                    update_conflicts=True,
                    unique_fields=["entity_key", "season", "week"],
                    update_fields=[
                        "external_id",
                        "player",
                        "team",
                        "position",
                        "sleeper_ppr",
                        "sleeper_half_ppr",
                        "sleeper_standard",
                        "projected_stats",
                        "projection_available",
                        "source",
                        "source_provider",
                        "updated_at",
                    ],
                )
                ros_rows = _recalculate_rest_of_season(season, positions)
        except Exception as exc:
            raise CommandError(
                f"Projection import was rolled back: {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Imported or refreshed {len(rows)} weekly projections and "
            f"recalculated rest-of-season totals for {ros_rows} rows."
        ))
