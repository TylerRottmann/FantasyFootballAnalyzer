"""Validate game context before Boom/Bust v2 inference."""

VALID_STATUSES = frozenset({"GAME", "BYE", "UNKNOWN"})


class GameContextUnavailable(ValueError):
    """Pregame matchup information is insufficient for prediction."""


class PlayerOnBye(ValueError):
    """The player's team has a verified bye week."""


def validate_prediction_context(features, player=None):
    """Require a complete, internally consistent game context.

    This validator does not independently authenticate schedules or
    player-team assignments. The caller must use a trusted source.
    """
    if not isinstance(features, dict):
        raise GameContextUnavailable("Features must be a dictionary.")

    status = features.get("game_status")

    if status not in VALID_STATUSES:
        raise GameContextUnavailable(
            f"Invalid or missing game status: {status!r}"
        )

    team_id = features.get("team_id")
    opponent_id = features.get("opponent_team_id")
    opponent = features.get("opponent_team")
    is_home = features.get("is_home")

    if team_id is None:
        raise GameContextUnavailable(
            "Player team is unknown; cannot establish a bye or game."
        )

    if status == "UNKNOWN":
        raise GameContextUnavailable(
            "Game matchup is not verified."
        )

    if status == "BYE":
        raise PlayerOnBye(
            "Player has no scheduled game for this week."
        )

    if (
        not isinstance(team_id, int)
        or isinstance(team_id, bool)
        or not isinstance(opponent_id, int)
        or isinstance(opponent_id, bool)
        or team_id <= 0
        or opponent_id <= 0
        or team_id == opponent_id
        or not isinstance(opponent, str)
        or not opponent.strip()
        or type(is_home) is not bool
    ):
        raise GameContextUnavailable(
            "GAME context has missing or inconsistent matchup fields."
        )

    if player is not None:
        if getattr(player, "team_id", None) is None:
            raise GameContextUnavailable(
                "Player has no current team assignment."
            )

        if player.team_id != team_id:
            raise GameContextUnavailable(
                "Matchup team differs from current player team."
            )

    return True
