"""Fail-closed pre-kickoff validation for Boom/Bust v2."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scripts.algorithm.boom_bust.boom_bust_context_v2 import (
    GameContextUnavailable,
)
from scripts.algorithm.features.qb_features import get_connection


EASTERN = ZoneInfo("America/New_York")


class GameAlreadyStarted(GameContextUnavailable):
    """The scheduled kickoff is not in the future."""


def validate_before_kickoff(
    season,
    week,
    team_id,
    opponent_team_id,
    is_home,
    now=None,
):
    """Require a unique, future regular-season kickoff.

    Source nflverse gameday/gametime values are interpreted as
    America/New_York local time. Ambiguous or missing kickoff
    information is rejected.
    """
    if (
        type(season) is not int
        or type(week) is not int
        or type(team_id) is not int
        or type(opponent_team_id) is not int
        or type(is_home) is not bool
        or not 1 <= week <= 18
        or team_id <= 0
        or opponent_team_id <= 0
        or team_id == opponent_team_id
    ):
        raise GameContextUnavailable(
            "Invalid kickoff validation context."
        )

    if now is None:
        now = datetime.now(timezone.utc)

    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime.")

    home_id = team_id if is_home else opponent_team_id
    away_id = opponent_team_id if is_home else team_id

    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT game_date, game_time
            FROM nfl_games
            WHERE season = %s
              AND week = %s
              AND game_type = 'REG'
              AND home_team_id = %s
              AND away_team_id = %s
            """,
            (season, week, home_id, away_id),
        )
        games = cursor.fetchall()

    if len(games) != 1:
        raise GameContextUnavailable(
            "A unique scheduled kickoff could not be verified."
        )

    game_date, game_time = games[0]

    if game_date is None or game_time is None:
        raise GameContextUnavailable(
            "Scheduled kickoff date or time is missing."
        )

    if game_time.tzinfo is not None:
        raise GameContextUnavailable(
            "Expected a timezone-naive source kickoff time."
        )

    local_naive = datetime.combine(game_date, game_time)

    local_kickoff = local_naive.replace(tzinfo=EASTERN)

    # Reject DST gaps and folds rather than silently guessing.
    utc_kickoff = local_kickoff.astimezone(timezone.utc)

    roundtrip = utc_kickoff.astimezone(EASTERN)

    if (
        roundtrip.replace(tzinfo=None) != local_naive
        or roundtrip.fold != 0
        or local_naive.replace(
            tzinfo=EASTERN, fold=0
        ).utcoffset() != local_naive.replace(
            tzinfo=EASTERN, fold=1
        ).utcoffset()
    ):
        raise GameContextUnavailable(
            "Scheduled kickoff has an ambiguous or invalid local time."
        )

    if now.astimezone(timezone.utc) >= utc_kickoff:
        raise GameAlreadyStarted(
            "Boom/Bust predictions close at scheduled kickoff."
        )

    return utc_kickoff
