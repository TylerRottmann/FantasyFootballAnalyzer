from collections import defaultdict
from leagues.services.kicker_scoring import league_projection

from analyzer.models import Teams
from leagues.models import (
    DefenseProjection,
    FantasyMatchup,
    FantasyProjection,
    FantasyRosterPlayer,
    UserLeagueConnection,
)
from leagues.services.power_rankings import REGULAR_SEASON_WEEKS
from scripts.commands.lineup import build_optimized_lineup, get_projection


POSITION_CODES = ("QB", "RB", "WR", "TE", "K", "DEF")


def build_team_breakdown(
    league, roster, current_week, weekly_rankings, user, include_defense=True
):
    """Build the rest-of-season team, schedule, and player breakdown payload."""
    roster_players = list(
        FantasyRosterPlayer.objects.filter(roster=roster)
        .select_related("player", "team")
    )
    if not include_defense:
        roster_players = [entry for entry in roster_players if entry.player_id is not None]
    player_ids = [entry.player_id for entry in roster_players if entry.player_id]
    defense_team_ids = [entry.team_id for entry in roster_players if entry.player_id is None and entry.team_id]
    projections = list(FantasyProjection.objects.filter(
        player_id__in=player_ids,
        season=league.season,
        week__gte=current_week,
        week__lte=REGULAR_SEASON_WEEKS,
        model_version="v1",
    ).select_related("player"))
    defense_projections = list(DefenseProjection.objects.filter(
        team_id__in=defense_team_ids,
        season=league.season,
        week__gte=current_week,
        week__lte=REGULAR_SEASON_WEEKS,
        model_version="v1",
    ).select_related("team"))
    projection_map = {(row.player_id, row.week): league_projection(row, league) for row in projections}
    defense_map = {(row.team_id, row.week): row for row in defense_projections}
    available_weeks = sorted({row.week for row in projections + defense_projections})
    starting_positions = [
        "DEF" if str(position).upper() == "D/ST" else str(position).upper()
        for position in (league.roster_positions or [])
        if str(position).upper() not in {"BN", "IR", "TAXI"}
    ]
    if not include_defense:
        starting_positions = [
            position for position in starting_positions
            if str(position).upper() != "DEF"
        ]
    nfl_teams = Teams.objects.in_bulk({
        entry.player.team_id
        for entry in roster_players
        if entry.player_id and entry.player.team_id
    })

    player_totals = {
        entry.id: {
            "entry": entry,
            "projected_points": 0.0,
            "starting_points": 0.0,
            "starts": 0,
            "flex_starts": 0,
        }
        for entry in roster_players
    }
    starter_points_by_position = defaultdict(float)
    bench_points_by_position = defaultdict(float)
    weekly_projections = []

    for week in available_weeks:
        items = []
        for entry in roster_players:
            if entry.player_id is None:
                prediction = defense_map.get((entry.team_id, week))
                player = None
                team = entry.team
            else:
                prediction = projection_map.get((entry.player_id, week))
                player = entry.player
                team = None
            items.append({
                "player": player,
                "roster_player": entry,
                "prediction": prediction,
                "team": team,
                "is_defense": player is None,
            })

        lineup, _ = build_optimized_lineup(items, starting_positions)
        selected_ids = {
            slot["item"]["roster_player"].id
            for slot in lineup
            if slot["item"] is not None
        }
        starter_points = 0.0
        for slot in lineup:
            item = slot["item"]
            if item is None or item["prediction"] is None:
                continue
            points = get_projection(item)
            entry_id = item["roster_player"].id
            position = item["player"].position if item["player"] else "DEF"
            player_totals[entry_id]["projected_points"] += points
            player_totals[entry_id]["starting_points"] += points
            player_totals[entry_id]["starts"] += 1
            if str(slot["slot"]).upper() in {"FLEX", "SUPER_FLEX"}:
                player_totals[entry_id]["flex_starts"] += 1
            starter_points += points
            starter_points_by_position[position] += points

        for item in items:
            if item["prediction"] is None:
                continue
            entry_id = item["roster_player"].id
            points = get_projection(item)
            if entry_id not in selected_ids:
                player_totals[entry_id]["projected_points"] += points
                position = item["player"].position if item["player"] else "DEF"
                bench_points_by_position[position] += points

        weekly_projections.append({"week": week, "projected_points": starter_points})

    whole_team_points_by_position = {
        position: starter_points_by_position.get(position, 0.0)
        + bench_points_by_position.get(position, 0.0)
        for position in POSITION_CODES
    }
    position_breakdowns = {
        "starters": _position_breakdown(starter_points_by_position),
        "bench": _position_breakdown(bench_points_by_position),
        "whole_team": _position_breakdown(whole_team_points_by_position),
    }

    connection = UserLeagueConnection.objects.filter(
        user=user,
        league=league,
    ).only("platform").first()
    matchups = list(FantasyMatchup.objects.filter(
        league=league,
        roster=roster,
        season=league.season,
        platform=connection.platform if connection else "",
        week__lte=REGULAR_SEASON_WEEKS,
    ).select_related("opponent"))
    matchup_by_week = {matchup.week: matchup for matchup in matchups}
    score_by_roster_week = {
        (row["roster_id"], week_row["week"]): week_row["projected_points"]
        for row in weekly_rankings
        for week_row in row["weeks"]
    }
    schedule = []
    for matchup in sorted(matchups, key=lambda item: item.week):
        opponent_name = (
            matchup.opponent.owner_name or f"Team {matchup.opponent.sleeper_roster_id}"
            if matchup.opponent_id else "Bye"
        )
        game = {
            "week": matchup.week,
            "opponent": opponent_name,
            "is_final": matchup.is_final,
            "team_points": matchup.points,
            "opponent_points": matchup.opponent_points,
            "result": "—",
            "result_type": "pending",
        }
        if matchup.is_final and matchup.points is not None and matchup.opponent_points is not None:
            if matchup.points > matchup.opponent_points:
                game["result"] = "W"
                game["result_type"] = "win"
            elif matchup.points < matchup.opponent_points:
                game["result"] = "L"
                game["result_type"] = "loss"
            else:
                game["result"] = "T"
                game["result_type"] = "tie"
        elif matchup.opponent_id and matchup.week >= current_week:
            team_projection = score_by_roster_week.get((roster.id, matchup.week))
            opponent_projection = score_by_roster_week.get((matchup.opponent_id, matchup.week))
            if team_projection is not None and opponent_projection is not None:
                game["team_points"] = team_projection
                game["opponent_points"] = opponent_projection
                if team_projection > opponent_projection:
                    game["result"] = "W"
                    game["result_type"] = "win"
                elif team_projection < opponent_projection:
                    game["result"] = "L"
                    game["result_type"] = "loss"
                else:
                    game["result"] = "T"
                    game["result_type"] = "tie"
                game["is_projected"] = True
        schedule.append(game)

    ranked_team = dict(next(
        (row for row in weekly_rankings if row["roster_id"] == roster.id),
        {},
    ))
    if ranked_team:
        ranked_team["projected_rank"] = next(
            (index for index, row in enumerate(weekly_rankings, start=1)
             if row["roster_id"] == roster.id),
            None,
        )
    position_averages = ranked_team.get("position_averages", {})
    league_slots = {
        "DEF" if str(position).upper() == "D/ST" else str(position).upper()
        for position in (league.roster_positions or [])
    }
    starter_positions = league_slots.intersection(POSITION_CODES)
    if not include_defense:
        starter_positions.discard("DEF")
    if "FLEX" in league_slots:
        starter_positions.update({"RB", "WR", "TE"})
    if "SUPER_FLEX" in league_slots:
        starter_positions.update({"QB", "RB", "WR", "TE"})
    positions_with_points = {
        position: position_averages.get(position, 0.0)
        for position in starter_positions
    }
    if not any(points > 0 for points in positions_with_points.values()):
        positions_with_points = {}
    strongest_position = max(
        positions_with_points.items(), key=lambda item: item[1], default=None
    )
    weakest_position = min(
        positions_with_points.items(), key=lambda item: item[1], default=None
    )
    player_rows = []
    for total in player_totals.values():
        entry = total["entry"]
        player = entry.player
        team = entry.team if entry.player_id is None else nfl_teams.get(player.team_id)
        if player:
            name = player.full_name
            position = (player.position or "—").upper()
            headshot = player.headshot_url or ""
            position_groups = [position] if position in {"QB", "RB", "WR", "TE"} else []
        else:
            name = team.name if team else "Defense"
            position = "D/ST"
            headshot = ""
            position_groups = ["D/ST"]
        if total["flex_starts"]:
            position_groups.append("FLEX")
        abbreviation = team.abbreviation.lower() if team and team.abbreviation else ""
        player_rows.append({
            "name": name,
            "position": position,
            "position_groups": position_groups,
            "headshot_url": headshot,
            "team_logo_url": (
                f"https://a.espncdn.com/i/teamlogos/nfl/500/{abbreviation}.png"
                if abbreviation else ""
            ),
            "projected_points": round(total["projected_points"], 1),
            "starting_points": round(total["starting_points"], 1),
            "starts": total["starts"],
            "flex_starts": total["flex_starts"],
            "bench_points": round(
                total["projected_points"] - total["starting_points"], 1
            ),
        })
    player_rows.sort(key=lambda row: (row["bench_points"], row["projected_points"]), reverse=True)

    projected_weeks = [
        week for week in weekly_projections
        if (
            week["week"] in matchup_by_week
            and matchup_by_week[week["week"]].opponent_id
            and not matchup_by_week[week["week"]].is_final
            and week["week"] >= current_week
        )
    ]
    highest = max(projected_weeks, key=lambda row: row["projected_points"], default=None)
    lowest = min(projected_weeks, key=lambda row: row["projected_points"], default=None)

    return {
        "position_breakdowns": position_breakdowns,
        "position_codes": POSITION_CODES,
        "schedule": schedule,
        "players": player_rows,
        "projected_weeks": projected_weeks,
        "strongest_week": highest,
        "weakest_week": lowest,
        "strongest_position": (
            {"position": strongest_position[0], "points": strongest_position[1]}
            if strongest_position else None
        ),
        "weakest_position": (
            {"position": weakest_position[0], "points": weakest_position[1]}
            if weakest_position else None
        ),
        "average_weekly_points": (
            round(sum(week["projected_points"] for week in projected_weeks) / len(projected_weeks), 1)
            if projected_weeks else None
        ),
        "current_record": ranked_team,
        "team_name": roster.owner_name or f"Team {roster.sleeper_roster_id}",
        "current_week": current_week,
    }


def _position_breakdown(points_by_position):
    return [
        {"position": position, "points": round(points_by_position.get(position, 0.0), 1)}
        for position in POSITION_CODES
    ]
