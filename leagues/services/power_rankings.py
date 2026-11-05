from collections import defaultdict
from leagues.services.kicker_scoring import league_projection
from leagues.services.player_availability import projection_context

from django.db.models import Prefetch

from leagues.models import (
    DefenseProjection,
    FantasyProjection,
    FantasyMatchup,
    FantasyRoster,
    FantasyRosterPlayer,
    UserLeagueConnection,
)
from scripts.commands.lineup import build_optimized_lineup, get_projection

REGULAR_SEASON_WEEKS = 14


def project_team_week(roster_players, player_forecasts, starting_positions, week):
    items = make_lineup_items(roster_players, player_forecasts, week)
    lineup, _ = build_optimized_lineup(items, starting_positions)

    points_by_position = {}
    projected_total = 0.0
    saved_lineup = []

    for entry in lineup:
        item = entry["item"]
        if item is None:
            continue

        points = get_projected_points(item)
        if points is None:
            continue

        position = item["player"].position
        projected_total += points
        points_by_position[position] = (
            points_by_position.get(position, 0.0) + points
        )

        saved_lineup.append({
            "slot": entry["slot"],
            "player_id": item["player"].id,
            "position": position,
            "projected_points": points,
        })

    return {
        "week": week,
        "projected_points": projected_total,
        "points_by_position": points_by_position,
        "lineup": saved_lineup,
    }

def rank_teams(team_week_rows):
    rest_of_season = {}

    for row in team_week_rows:
        roster_id = row["roster_id"]
        summary = rest_of_season.setdefault(roster_id, {
            "projected_points": 0.0,
            "position_points": {},
            "weeks": [],
        })

        summary["projected_points"] += row["projected_points"] or 0.0
        summary["weeks"].append(row)

        for position, points in row["points_by_position"].items():
            summary["position_points"][position] = (
                summary["position_points"].get(position, 0.0) + points
            )

    return sorted(
        rest_of_season.items(),
        key=lambda item: item[1]["projected_points"],
        reverse=True,
    )


def find_below_average_weeks(team_week_rows, league_week_averages, margin=0.20):
    alerts = []

    for row in team_week_rows:
        average = league_week_averages[row["week"]]
        points = row["projected_points"]

        if average and points < average * (1 - margin):
            alerts.append({
                "week": row["week"],
                "projected_points": points,
                "league_average": average,
                "gap": points - average,
                "positions": weak_positions_for_week(row),
            })

    return alerts


def get_saved_power_rankings(league, user, current_week, include_defense=True):
    """Build league rankings from the saved per-player weekly projections."""
    rosters = list(
        FantasyRoster.objects.filter(league=league)
        .prefetch_related(
            Prefetch(
                "roster_players",
                queryset=FantasyRosterPlayer.objects.select_related("player", "team"),
            )
        )
        .order_by("sleeper_roster_id")
    )
    if not rosters:
        return [], 0.0, None

    roster_players = {
        roster.id: list(roster.roster_players.all())
        for roster in rosters
    }
    if not include_defense:
        roster_players = {
            roster_id: [entry for entry in entries if entry.player_id is not None]
            for roster_id, entries in roster_players.items()
        }
    player_ids = {
        entry.player_id
        for entries in roster_players.values()
        for entry in entries
        if entry.player_id is not None
    }
    defense_team_ids = {
        entry.team_id
        for entries in roster_players.values()
        for entry in entries
        if entry.player_id is None and entry.team_id is not None
    }

    projections = list(
        FantasyProjection.objects.filter(
            player_id__in=player_ids,
            season=league.season,
            week__gte=current_week,
            week__lte=REGULAR_SEASON_WEEKS,
            model_version="v1",
        ).select_related("player")
    )
    defense_projections = list(
        DefenseProjection.objects.filter(
            team_id__in=defense_team_ids,
            season=league.season,
            week__gte=current_week,
            week__lte=REGULAR_SEASON_WEEKS,
            model_version="v1",
        ).select_related("team")
    )
    available_weeks = sorted({row.week for row in projections + defense_projections})
    if not available_weeks:
        return [], 0.0, None

    context_for_week = projection_context(league.season, current_week)
    projection_map = {(row.player_id, row.week): league_projection(row, league, context=context_for_week) for row in projections}
    defense_map = {(row.team_id, row.week): row for row in defense_projections}
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
    connection = UserLeagueConnection.objects.filter(
        user=user,
        league=league,
    ).only("external_user_id").first()
    user_external_id = str(connection.external_user_id) if connection and connection.external_user_id else None

    team_rows = []
    generated_at = max(row.updated_at for row in projections + defense_projections)
    for roster in rosters:
        weekly_rows = []
        for week in available_weeks:
            items = []
            has_projection = False
            for entry in roster_players[roster.id]:
                if entry.player_id is None:
                    prediction = defense_map.get((entry.team_id, week))
                    team = entry.team
                    player = None
                else:
                    prediction = projection_map.get((entry.player_id, week))
                    team = None
                    player = entry.player
                has_projection = has_projection or prediction is not None
                items.append({
                    "player": player,
                    "roster_player": entry,
                    "prediction": prediction,
                    "team": team,
                    "is_defense": player is None,
                })

            if not has_projection:
                continue

            lineup, _ = build_optimized_lineup(items, starting_positions)
            starter_roster_player_ids = {
                slot["item"]["roster_player"].id
                for slot in lineup
                if slot["item"] is not None
            }
            position_points = defaultdict(float)
            projected_points = 0.0
            bench_position_points = defaultdict(float)
            bench_projected_points = 0.0
            for slot in lineup:
                item = slot["item"]
                if item is None or item.get("prediction") is None:
                    continue
                points = get_projection(item)
                position = item["player"].position if item["player"] else "DEF"
                projected_points += points
                position_points[position] += points

            for item in items:
                if (
                    item["prediction"] is None
                    or item["roster_player"].id in starter_roster_player_ids
                ):
                    continue
                points = get_projection(item)
                position = item["player"].position if item["player"] else "DEF"
                bench_projected_points += points
                bench_position_points[position] += points

            weekly_rows.append({
                "week": week,
                "projected_points": projected_points,
                "points_by_position": dict(position_points),
                "bench_projected_points": bench_projected_points,
                "bench_points_by_position": dict(bench_position_points),
            })

        if not weekly_rows:
            continue

        position_totals = defaultdict(float)
        for row in weekly_rows:
            for position, points in row["points_by_position"].items():
                position_totals[position] += points

        team_rows.append({
            "roster_id": roster.id,
            "team_name": roster.owner_name or f"Team {roster.sleeper_roster_id}",
            "is_user_team": user_external_id is not None
                and str(roster.owner_sleeper_id) == user_external_id,
            "rest_of_season_points": sum(row["projected_points"] for row in weekly_rows),
            "position_totals": dict(position_totals),
            "weeks": weekly_rows,
        })

    if not team_rows:
        return [], 0.0, generated_at

    team_rows.sort(key=lambda row: row["rest_of_season_points"], reverse=True)
    position_codes = ("QB", "RB", "WR", "TE", "K", "DEF")
    week_averages = defaultdict(list)
    for row in team_rows:
        for week_row in row["weeks"]:
            week_averages[week_row["week"]].append(week_row["projected_points"])
    week_averages = {
        week: sum(points) / len(points)
        for week, points in week_averages.items()
        if points
    }

    connection = UserLeagueConnection.objects.filter(
        user=user, league=league,
    ).only("platform").first()
    matchups = list(FantasyMatchup.objects.filter(
        league=league,
        season=league.season,
        platform=connection.platform if connection else "",
        week__lte=REGULAR_SEASON_WEEKS,
    ).select_related("roster", "opponent"))
    matchup_by_team_week = {
        (matchup.roster_id, matchup.week): matchup
        for matchup in matchups
    }
    weekly_projection_by_team_week = {
        (row["roster_id"], week_row["week"]): week_row["projected_points"]
        for row in team_rows
        for week_row in row["weeks"]
    }
    for row in team_rows:
        row.update({
            "position_totals": {},
            "current_wins": 0,
            "current_losses": 0,
            "current_ties": 0,
            "current_points": 0.0,
            "current_points_against": 0.0,
            "bench_position_totals": {},
            "bench_projected_points": 0.0,
            "projected_wins": 0,
            "projected_losses": 0,
            "projected_ties": 0,
            "projected_points": 0.0,
            "projected_points_against": 0.0,
            "current_games_played": 0,
            "projected_games": 0,
            "projected_weeks": 0,
        })

    ranking_by_roster = {row["roster_id"]: row for row in team_rows}
    for matchup in matchups:
        row = ranking_by_roster.get(matchup.roster_id)
        if row is None:
            continue
        if matchup.is_final and matchup.points is not None and matchup.opponent_points is not None:
            row["current_games_played"] += 1
            row["current_points"] += matchup.points
            row["current_points_against"] += matchup.opponent_points
            if matchup.points > matchup.opponent_points:
                row["current_wins"] += 1
            elif matchup.points < matchup.opponent_points:
                row["current_losses"] += 1
            else:
                row["current_ties"] += 1

    for row in team_rows:
        for week_row in row["weeks"]:
            matchup = matchup_by_team_week.get((row["roster_id"], week_row["week"]))
            opponent = matchup.opponent if matchup else None
            if (
                opponent is None
                or matchup.is_final
                or week_row["week"] < current_week
            ):
                continue
            row["projected_weeks"] += 1
            row["projected_points"] += week_row["projected_points"]
            row["bench_projected_points"] += week_row["bench_projected_points"]
            for position, points in week_row["bench_points_by_position"].items():
                row["bench_position_totals"][position] = (
                    row["bench_position_totals"].get(position, 0.0) + points
                )
            for position, points in week_row["points_by_position"].items():
                row["position_totals"][position] = (
                    row["position_totals"].get(position, 0.0) + points
                )
            opponent_points = weekly_projection_by_team_week.get(
                (opponent.id, week_row["week"])
            )
            if opponent_points is None:
                continue
            row["projected_points_against"] += opponent_points
            row["projected_games"] += 1
            if week_row["projected_points"] > opponent_points:
                row["projected_wins"] += 1
            elif week_row["projected_points"] < opponent_points:
                row["projected_losses"] += 1
            else:
                row["projected_ties"] += 1

    for row in team_rows:
        row["projected_wins"] += row["current_wins"]
        row["projected_losses"] += row["current_losses"]
        row["projected_ties"] += row["current_ties"]
        # Show season totals as actual results to date plus projections for
        # scheduled games that have not been played yet.
        row["projected_total_points"] = (
            row["current_points"] + row["projected_points"]
        )
        row["projected_points_against"] += row["current_points_against"]
        row["rest_of_season_points"] = row["projected_points"]
        row["position_averages"] = {
            position: round(
                row["position_totals"].get(position, 0.0) / row["projected_weeks"],
                2,
            ) if row["projected_weeks"] else 0.0
            for position in position_codes
        }
        row["position_averages"].update({
            f"BENCH_{position}": round(
                row["bench_position_totals"].get(position, 0.0) / row["projected_weeks"],
                2,
            ) if row["projected_weeks"] else 0.0
            for position in position_codes
        })
        row["position_averages"]["BENCH_TOTAL"] = round(
            row["bench_projected_points"] / row["projected_weeks"], 2
        ) if row["projected_weeks"] else 0.0

    team_rows.sort(
        key=lambda row: (
            row["projected_wins"],
            -row["projected_losses"],
            row["projected_total_points"],
        ),
        reverse=True,
    )

    for row in team_rows:
        row["alerts"] = []
        for week_row in row["weeks"]:
            average = week_averages.get(week_row["week"])
            points = week_row["projected_points"]
            if average and points < average * 0.8:
                row["alerts"].append({
                    "week": week_row["week"],
                    "projected_points": points,
                    "league_average": average,
                    "shortfall_pct": (average - points) / average * 100,
                })

    league_average = sum(
        row["rest_of_season_points"] for row in team_rows
    ) / len(team_rows)
    return team_rows, league_average, generated_at
