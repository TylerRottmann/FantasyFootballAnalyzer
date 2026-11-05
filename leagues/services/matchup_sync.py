"""Import weekly schedule and score data into the normalized matchup table."""

from collections import defaultdict

from django.utils import timezone

from leagues.integrations.sleeper import SleeperLeagueService
from leagues.integrations.yahoo import YahooLeagueService
from leagues.models import (
    FantasyMatchup,
    FantasyRoster,
    LeaguePlatformIdentity,
    RosterPlatformIdentity,
    UserLeagueConnection,
    YahooAccount,
)


def _save_week(league, platform, season, week, records):
    """Upsert per-roster matchup rows, with reciprocal scores and opponents."""
    if platform == UserLeagueConnection.PLATFORM_SLEEPER:
        roster_ids = {
            str(roster.sleeper_roster_id): roster.id
            for roster in FantasyRoster.objects.filter(league=league)
        }
    else:
        roster_ids = {
            str(identity.external_id): identity.roster_id
            for identity in RosterPlatformIdentity.objects.filter(
                platform=platform,
                roster__league=league,
            ).select_related("roster")
        }

    grouped = defaultdict(list)
    for row in records:
        if row.get("matchup_id") is not None:
            grouped[str(row["matchup_id"])].append(row)

    now = timezone.now()
    updates = []
    for row in records:
        roster = roster_ids.get(str(row["external_roster_id"]))
        if roster is None:
            continue
        opponents = [
            candidate for candidate in grouped.get(str(row.get("matchup_id")), [])
            if str(candidate["external_roster_id"]) != str(row["external_roster_id"])
        ] if row.get("matchup_id") is not None else []
        opponent_data = opponents[0] if opponents else None
        opponent = (
            roster_ids.get(str(opponent_data["external_roster_id"]))
            if opponent_data else None
        )
        points = row.get("points")
        opponent_points = opponent_data.get("points") if opponent_data else None
        final = bool(row.get("is_final"))
        updates.append(FantasyMatchup(
            league=league,
            roster_id=roster,
            opponent_id=opponent,
            season=season,
            week=week,
            platform=platform,
            external_id=str(row.get("matchup_id") or ""),
            points=points,
            opponent_points=opponent_points,
            is_final=final,
            updated_at=now,
        ))

    FantasyMatchup.objects.bulk_create(
        updates,
        update_conflicts=True,
        unique_fields=["league", "roster", "season", "week", "platform"],
        update_fields=["opponent", "external_id", "points", "opponent_points", "is_final", "updated_at"],
    )
    return len(updates)


def sync_sleeper_matchups(league, start_week=1, end_week=18, current_week=1):
    service = SleeperLeagueService(league.sleeper_league_id)
    roster_ids = {
        str(roster.sleeper_roster_id): roster.id
        for roster in FantasyRoster.objects.filter(league=league)
    }
    imported = 0
    for week in range(start_week, end_week + 1):
        payload = service.get_matchups(week) or []
        records = []
        for row in payload:
            roster_id = str(row.get("roster_id"))
            if roster_id not in roster_ids:
                continue
            records.append({
                "external_roster_id": roster_id,
                "matchup_id": row.get("matchup_id"),
                "points": row.get("points"),
                "is_final": week < current_week and row.get("points") is not None,
            })
        imported += _save_week(
            league,
            UserLeagueConnection.PLATFORM_SLEEPER,
            league.season,
            week,
            records,
        )
    return imported


def _yahoo_matchup_rows(payload, week, is_final):
    """Flatten Yahoo's scoreboard resource into the common matchup shape."""
    rows = []
    matchup_groups = YahooLeagueService._values_named(payload, "matchup")
    matchup_index = 0
    for matchup_group in matchup_groups:
        for matchup in YahooLeagueService._walk(matchup_group):
            if not isinstance(matchup, dict) or "teams" not in matchup:
                continue
            matchup_id = matchup.get("matchup_id") or f"{week}:{matchup_index}"
            matchup_index += 1
            teams = YahooLeagueService._values_named(matchup.get("teams"), "team")
            for team_data in teams:
                if not isinstance(team_data, (dict, list)):
                    continue
                team_key = YahooLeagueService._metadata(team_data, "team_key").get("team_key")
                if not team_key:
                    continue
                points_data = YahooLeagueService._metadata(team_data, "team_points")
                points_value = points_data.get("team_points")
                if isinstance(points_value, dict):
                    points_value = points_value.get("total")
                try:
                    points = float(points_value) if points_value is not None else None
                except (TypeError, ValueError):
                    points = None
                rows.append({
                    "external_roster_id": str(team_key),
                    "matchup_id": str(matchup_id),
                    "points": points,
                    "is_final": is_final and points is not None,
                })
    return rows


def sync_yahoo_matchups(league, user, start_week=1, end_week=18, current_week=1):
    account = YahooAccount.objects.get(user=user)
    service = YahooLeagueService(account)
    identity = LeaguePlatformIdentity.objects.get(
        league=league,
        platform=UserLeagueConnection.PLATFORM_YAHOO,
    )
    imported = 0
    for week in range(start_week, end_week + 1):
        payload = service.get_scoreboard(identity.external_id, week)
        rows = _yahoo_matchup_rows(
            payload,
            week,
            is_final=week < current_week,
        )
        imported += _save_week(
            league,
            UserLeagueConnection.PLATFORM_YAHOO,
            league.season,
            week,
            rows,
        )
    return imported


def sync_connection_matchups(connection, current_week, start_week=1, end_week=18):
    """Sync the schedule/results for one already-connected platform league."""
    options = {
        "start_week": start_week,
        "end_week": end_week,
        "current_week": current_week,
    }
    if connection.platform == UserLeagueConnection.PLATFORM_SLEEPER:
        return sync_sleeper_matchups(connection.league, **options)
    if connection.platform == UserLeagueConnection.PLATFORM_YAHOO:
        return sync_yahoo_matchups(
            connection.league,
            connection.user,
            **options,
        )
    raise ValueError(f"Schedule sync is not supported for {connection.platform}.")
