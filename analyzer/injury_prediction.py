"""Estimate injury absence length from historical injury/return episodes.

This module is deliberately independent of Django and network calls. The
refresh/training pipeline supplies normalized historical injury reports and
weeks in which each player appeared, then saves the profiles for projections
to use. A profile is the nearest-rank 75th percentile of *resolved* episodes;
unresolved season-ending cases are handled by the separate season-ending
outlook logic rather than being treated as exact return times.
"""
from __future__ import annotations

from collections import defaultdict
import json
from math import ceil
from pathlib import Path
from typing import Iterable, Mapping


BLOCKING_STATUSES = {"OUT", "DOUBTFUL", "IR", "INJUREDRESERVE", "PUP",
                     "PHYSICALLYUNABLETOPERFORM"}
RETURN_BUFFER_WEEKS = 2
MIN_PROFILE_SAMPLES = 5
MIN_GLOBAL_SAMPLES = 25
REGULAR_SEASON_WEEKS = 18
PROFILE_PATH = Path(__file__).with_name("data") / "injury_duration_profiles.json"


def _normalize(value) -> str:
    return "".join(char for char in str(value or "").upper() if char.isalnum())


def _quantile_75(values: list[int]) -> int:
    """Conservative nearest-rank 75th percentile (always one observed value)."""
    return sorted(values)[max(0, ceil(0.75 * len(values)) - 1)]


def build_injury_episodes(
    reports: Iterable[Mapping],
    appearance_weeks: Mapping[tuple[str, int], Iterable[int]],
) -> list[dict]:
    """Turn weekly injury reports into resolved missed-week episodes.

    Each report needs ``player_id``, ``season``, ``week``, ``position``,
    ``status`` and preferably ``injury_type`` or ``body_part``. The appearance
    mapping is keyed by ``(str(player_id), season)`` and contains weeks with a
    player stats/snap row. A player's return week must be after the first
    blocking report; same-week appearances are treated as conflicting data.

    Consecutive Out/Doubtful/IR/PUP reports are one episode. Episodes without
    an observed return are omitted because they are right-censored, not known
    durations.
    """
    grouped = defaultdict(list)
    for report in reports:
        try:
            player_id = str(report["player_id"])
            season = int(report["season"])
            week = int(report["week"])
            status = _normalize(report.get("status"))
            position = _normalize(report.get("position"))
        except (KeyError, TypeError, ValueError):
            continue
        if not player_id or not 1 <= week <= REGULAR_SEASON_WEEKS:
            continue
        if status not in BLOCKING_STATUSES:
            continue
        injury = _normalize(report.get("injury_type") or report.get("body_part"))
        grouped[(player_id, season)].append({
            "week": week,
            "position": position,
            "injury": injury,
            "status": status,
        })

    episodes = []
    for (player_id, season), rows in grouped.items():
        rows.sort(key=lambda row: row["week"])
        appearances = sorted({int(week) for week in
                              appearance_weeks.get((player_id, season), ())
                              if 1 <= int(week) <= REGULAR_SEASON_WEEKS})
        clusters = []
        for row in rows:
            if not clusters or row["week"] > clusters[-1][-1]["week"] + 1:
                clusters.append([row])
            else:
                clusters[-1].append(row)

        for cluster in clusters:
            start_week = cluster[0]["week"]
            # Avoid learning an absence length from a stale/contradictory
            # report when the player appeared in that same game week.
            if start_week in appearances:
                continue
            return_week = next((week for week in appearances if week > start_week), None)
            if return_week is None:
                continue
            episodes.append({
                "player_id": player_id,
                "season": season,
                "start_week": start_week,
                "return_week": return_week,
                "missed_weeks": return_week - start_week,
                "position": cluster[0]["position"],
                "injury": cluster[0]["injury"],
            })
    return episodes


def build_duration_profiles(episodes: Iterable[Mapping], min_samples: int = MIN_PROFILE_SAMPLES) -> dict:
    """Build exact-injury, position, and global fallback duration profiles.

    Profiles store a conservative 75th-percentile estimate and sample count.
    Exact injury/position profiles require ``min_samples``; a position profile
    requires twice that many samples. The global fallback is always included
    when any resolved training episodes exist.
    """
    exact = defaultdict(list)
    by_position = defaultdict(list)
    all_durations = []
    for row in episodes:
        try:
            duration = int(row["missed_weeks"])
            position = _normalize(row.get("position"))
            injury = _normalize(row.get("injury") or row.get("body_part"))
        except (KeyError, TypeError, ValueError):
            continue
        if duration < 1 or duration >= REGULAR_SEASON_WEEKS:
            continue
        all_durations.append(duration)
        if position:
            by_position[position].append(duration)
            if injury:
                exact[(position, injury)].append(duration)

    profiles = {"exact": {}, "position": {}, "global": None}
    for (position, injury), durations in exact.items():
        if len(durations) >= min_samples:
            profiles["exact"][f"{position}:{injury}"] = {
                "weeks": _quantile_75(durations), "samples": len(durations),
            }
    for position, durations in by_position.items():
        if len(durations) >= min_samples * 2:
            profiles["position"][position] = {
                "weeks": _quantile_75(durations), "samples": len(durations),
            }
    if len(all_durations) >= MIN_GLOBAL_SAMPLES:
        profiles["global"] = {
            "weeks": _quantile_75(all_durations), "samples": len(all_durations),
        }
    return profiles


def save_duration_profiles(profiles: Mapping, path: Path = PROFILE_PATH) -> None:
    """Write generated duration profiles as readable, versioned JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, **profiles}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_duration_profiles(path: Path = PROFILE_PATH) -> dict:
    """Load generated profiles; return an empty profile if none exist yet."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exact": {}, "position": {}, "global": None}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {"exact": {}, "position": {}, "global": None}
    return {
        "exact": payload.get("exact", {}),
        "position": payload.get("position", {}),
        "global": payload.get("global"),
    }


def estimate_absence(
    profiles: Mapping,
    *,
    position: str,
    injury_type: str = "",
    body_part: str = "",
    start_week: int,
    buffer_weeks: int = RETURN_BUFFER_WEEKS,
) -> dict | None:
    """Estimate a zero-projection window, with a two-week default buffer.

    Returns ``None`` when no historical profile exists. ``zero_through_week``
    is inclusive and capped at the end of the regular season. A later confirmed
    active/played report should clear this estimate in the availability layer.
    """
    try:
        start_week = int(start_week)
        buffer_weeks = max(0, int(buffer_weeks))
    except (TypeError, ValueError):
        return None
    if not 1 <= start_week <= REGULAR_SEASON_WEEKS:
        return None

    position_key = _normalize(position)
    injury_key = _normalize(injury_type or body_part)
    exact = profiles.get("exact", {})
    by_position = profiles.get("position", {})
    profile = exact.get(f"{position_key}:{injury_key}") if injury_key else None
    source = "position_injury"
    if profile is None:
        profile = by_position.get(position_key)
        source = "position"
    if profile is None:
        profile = profiles.get("global")
        source = "global"
    if not profile:
        return None

    estimated_missed = max(1, int(profile["weeks"]))
    zero_weeks = estimated_missed + buffer_weeks
    return {
        "estimated_missed_weeks": estimated_missed,
        "buffer_weeks": buffer_weeks,
        "zero_weeks": zero_weeks,
        "zero_through_week": min(REGULAR_SEASON_WEEKS, start_week + zero_weeks - 1),
        "return_week_estimate": start_week + estimated_missed,
        "profile_source": source,
        "sample_count": int(profile["samples"]),
    }
