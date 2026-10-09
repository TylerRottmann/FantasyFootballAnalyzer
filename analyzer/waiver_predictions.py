"""Temporary display projections; no database writes or algorithm dependencies."""
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class WaiverPrediction:
    this_week: float
    rest_of_season: float


def predict_waiver_player(player, league):
    """Replace this adapter with real weekly/ROS predictions when available.

    Values are deterministic synthetic points, NOT estimates from stats, scoring,
    or remaining games. Keep league in the interface for future scoring support.
    """
    seed = sha256(str(player.sleeper_id).encode()).digest()
    return WaiverPrediction(
        this_week=round(3 + int.from_bytes(seed[:2], 'big') % 220 / 10, 1),
        rest_of_season=round(25 + int.from_bytes(seed[2:4], 'big') % 2200 / 10, 1),
    )
