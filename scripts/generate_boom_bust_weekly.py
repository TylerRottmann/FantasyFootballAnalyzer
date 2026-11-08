"""Generate and persist pregame Boom/Bust predictions for an NFL week."""

import argparse
import logging
import os
import sys

import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FantasyFootballAnalyzer.settings")

import django
django.setup()

from analyzer.models import Players
from leagues.services.boom_bust_storage_v2 import save_boom_bust_prediction_v2
from scripts.algorithm.boom_bust.boom_bust_predict_v2 import PlayerUnavailableForPrediction, predict_boom_bust_v2

logger = logging.getLogger(__name__)


def generate_week(season, week):
    players = Players.objects.filter(
        position__in=["QB", "RB", "WR", "TE"],
        team__isnull=False,
    ).order_by("id").iterator(chunk_size=200)

    counts = {"saved": 0, "updated": 0, "skipped": 0, "failed": 0}

    for player in players:
        try:
            result = predict_boom_bust_v2(player, season, week)
            _, created = save_boom_bust_prediction_v2(result)
            counts["saved" if created else "updated"] += 1
        except (
            ValueError,
            LookupError,
            PlayerUnavailableForPrediction,
        ) as exc:
            counts["skipped"] += 1
            logger.info("Skipped player %s: %s", player.id, exc)
        except Exception:
            counts["failed"] += 1
            logger.exception("Prediction failed for player %s", player.id)

    return counts



def get_active_nfl_week():
    """Get the active regular-season week directly from Sleeper."""
    response = requests.get(
        "https://api.sleeper.app/v1/state/nfl",
        timeout=10,
    )
    response.raise_for_status()
    state = response.json()

    if state.get("season_type") != "regular":
        return None

    season = int(state["season"])
    week = int(state["week"])

    if not 2000 <= season <= 2100 or not 1 <= week <= 18:
        raise ValueError("Invalid NFL season or week from Sleeper")

    return season, week


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()

    if args.auto:
        if args.season is not None or args.week is not None:
            parser.error("--auto cannot be combined with --season or --week")
        active = get_active_nfl_week()
        if active is None:
            print("No active NFL regular-season week; skipping.")
            return
        season, week = active
    else:
        if args.season is None or args.week is None:
            parser.error("--season and --week are required without --auto")
        season, week = args.season, args.week

    if not 2000 <= season <= 2100:
        parser.error("Season must be between 2000 and 2100.")
    if not 1 <= week <= 18:
        parser.error("Week must be between 1 and 18.")

    logging.basicConfig(level=logging.INFO)
    counts = generate_week(season, week)

    print(f"Boom/Bust {season} Week {week}: {counts}")
    if counts["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
