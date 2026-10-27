"""Trade page and JSON endpoints."""
import json
import hashlib

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from analyzer.models import Teams
from leagues.models import (
    DefenseProjection,
    FantasyProjection,
    FantasyRoster,
    FantasyRosterPlayer,
    UserLeagueConnection,
)
from leagues.services.kicker_scoring import league_projection
from scripts.commands.nflweek import get_current_nfl_week

from .trade_generator import (
    build_trade_universe,
    evaluate_trade,
    generate_best_trades,
    serialize_asset,
)


@login_required
def trades(request):
    connection = _active_connection(request)
    if connection is None:
        return redirect("connect_league")

    request.session["active_league_id"] = connection.league_id
    my_roster = _user_roster(connection)
    if my_roster is None:
        return render(request, "leagues/trades.html", {
            "league": connection.league,
            "my_roster": None,
            "trade_teams": [],
            "give_options": [],
            "receive_options": [],
            "nfl_teams": [],
            "trade_positions": ("QB", "RB", "WR", "TE", "K", "DEF"),
            "bye_weeks": range(1, 19),
            "trade_error": "Your team could not be matched to a roster in this league.",
        })

    rosters = list(FantasyRoster.objects.filter(
        league=connection.league,
    ).prefetch_related("roster_players__player", "roster_players__team").order_by("sleeper_roster_id"))
    give_options = _roster_filter_options([my_roster])
    receive_options = _roster_filter_options([
        roster for roster in rosters if roster.id != my_roster.id
    ])
    nfl_teams = list(Teams.objects.filter(is_active=True).order_by("abbreviation"))
    return render(request, "leagues/trades.html", {
        "league": connection.league,
        "my_roster": my_roster,
        "trade_teams": [roster for roster in rosters if roster.id != my_roster.id],
        "give_options": give_options,
        "receive_options": receive_options,
        "nfl_teams": nfl_teams,
        "trade_positions": ("QB", "RB", "WR", "TE", "K", "DEF"),
        "bye_weeks": range(1, 19),
        "suggestions_url": reverse("trade_suggestions"),
        "player_search_url": reverse("trade_player_search"),
        "calculator_url": reverse("trade_calculate"),
        "my_roster_id": my_roster.id,
    })


@login_required
@require_GET
def trade_suggestions(request):
    connection = _active_connection(request)
    if connection is None:
        return JsonResponse({"error": "Connect a league before using Trades."}, status=400)
    try:
        current_week = _current_week()
        filters = _suggestion_filters(request)
        filter_key = hashlib.md5(request.GET.urlencode().encode("utf-8")).hexdigest()
        cache_key = (
            f"trade_suggestions_v22:{connection.league_id}:{request.user.id}:"
            f"{connection.league.season}:{current_week}:{filter_key}"
        )
        payload = cache.get(cache_key)
        if payload is None:
            universe = build_trade_universe(connection.league, request.user, current_week)
            payload = {
                "league": connection.league.name,
                "current_week": current_week,
                "suggestions": generate_best_trades(universe, filters=filters),
            }
            cache.set(cache_key, payload, timeout=120)
    except ValueError as exc:
        return JsonResponse({"error": str(exc), "suggestions": []}, status=200)
    except Exception:
        return JsonResponse({
            "error": "Trade suggestions could not be generated. Check that current projections are available.",
            "suggestions": [],
        }, status=503)
    return JsonResponse(payload)


@login_required
@require_GET
def trade_player_search(request):
    connection = _active_connection(request)
    if connection is None:
        return JsonResponse({"error": "Connect a league before using Trades."}, status=400)
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    roster_id = request.GET.get("roster_id")
    rosters = FantasyRoster.objects.filter(league=connection.league)
    if roster_id:
        try:
            rosters = rosters.filter(id=int(roster_id))
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid fantasy team."}, status=400)

    entries = list(
        FantasyRosterPlayer.objects.filter(roster__in=rosters)
        .filter(
            Q(player__full_name__icontains=query)
            | Q(team__name__icontains=query)
            | Q(team__abbreviation__icontains=query)
        )
        .select_related("roster", "player", "team")
        .order_by("roster__owner_name", "player__full_name")[:40]
    )
    player_ids = {entry.player_id for entry in entries if entry.player_id}
    defense_ids = {entry.team_id for entry in entries if entry.player_id is None and entry.team_id}
    nfl_team_ids = {
        entry.player.team_id for entry in entries
        if entry.player_id and entry.player.team_id
    } | defense_ids
    nfl_teams = Teams.objects.in_bulk(nfl_team_ids)
    try:
        current_week = _current_week()
    except Exception:
        return JsonResponse({
            "error": "The current NFL week is unavailable. Try again after the league data refreshes.",
            "results": [],
        }, status=503)
    player_projections = list(FantasyProjection.objects.filter(
        player_id__in=player_ids,
        season=connection.league.season,
        week__gte=current_week,
        week__lte=14,
        model_version="v1",
    ).select_related("player"))
    defense_projections = list(DefenseProjection.objects.filter(
        team_id__in=defense_ids,
        season=connection.league.season,
        week__gte=current_week,
        week__lte=14,
        model_version="v1",
    ))
    player_points = {}
    for projection in player_projections:
        scored = league_projection(projection, connection.league)
        if scored.projected_fantasy_points is not None:
            player_points[projection.player_id] = player_points.get(projection.player_id, 0.0) + float(
                scored.projected_fantasy_points
            )
    defense_points = {}
    for projection in defense_projections:
        if projection.projected_fantasy_points is not None:
            defense_points[projection.team_id] = defense_points.get(projection.team_id, 0.0) + float(
                projection.projected_fantasy_points
            )

    results = []
    for entry in entries:
        player = entry.player
        team = nfl_teams.get(player.team_id) if player and player.team_id else entry.team
        abbreviation = team.abbreviation if team else ""
        name = player.full_name if player else (f"{team.name} D/ST" if team else "D/ST")
        results.append({
            "roster_player_id": entry.id,
            "roster_id": entry.roster_id,
            "fantasy_team": entry.roster.owner_name or f"Team {entry.roster.sleeper_roster_id}",
            "name": name,
            "position": (player.position or "").upper() if player else "DEF",
            "age": round(player.age, 1) if player and player.age is not None else None,
            "nfl_team": abbreviation,
            "nfl_team_name": team.name if team else "",
            "headshot_url": player.headshot_url or "" if player else "",
            "team_logo_url": (
                f"https://a.espncdn.com/i/teamlogos/nfl/500/{abbreviation.lower()}.png"
                if abbreviation else ""
            ),
            "rest_of_season_points": round(
                player_points.get(entry.player_id, 0.0)
                if entry.player_id else defense_points.get(entry.team_id, 0.0), 1
            ),
        })
    return JsonResponse({"results": results})


@login_required
@require_POST
def trade_calculate(request):
    connection = _active_connection(request)
    if connection is None:
        return JsonResponse({"error": "Connect a league before using Trades."}, status=400)
    try:
        payload = json.loads(request.body or b"{}")
        team1_roster_id = int(payload.get("team1_roster_id"))
        team2_roster_id = int(payload.get("team2_roster_id"))
        team1_outgoing = payload.get("team1_player_ids") or []
        team2_outgoing = payload.get("team2_player_ids") or []
        if not isinstance(team1_outgoing, list) or not isinstance(team2_outgoing, list):
            raise ValueError("Select players for both teams.")
        current_week = _current_week()
        universe = build_trade_universe(connection.league, request.user, current_week)
        team1 = universe["states"].get(team1_roster_id)
        team2 = universe["states"].get(team2_roster_id)
        if team1 is None or team2 is None or team1_roster_id == team2_roster_id:
            raise ValueError("Select two different teams in this league.")
        return JsonResponse(evaluate_trade(
            universe,
            team1,
            team1_outgoing,
            team2,
            team2_outgoing,
        ))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc) or "Invalid trade details."}, status=400)
    except Exception:
        return JsonResponse({
            "error": "The trade could not be calculated. Check that current projections are available.",
        }, status=503)


def _active_connection(request):
    active_league_id = request.session.get("active_league_id")
    connection = None
    if active_league_id:
        connection = UserLeagueConnection.objects.filter(
            user=request.user,
            league_id=active_league_id,
        ).select_related("league").first()
    if connection is None:
        connection = UserLeagueConnection.objects.filter(
            user=request.user,
        ).select_related("league").order_by("-league__updated_at").first()
    return connection


def _user_roster(connection):
    rosters = FantasyRoster.objects.filter(league=connection.league)
    if connection.external_user_id:
        roster = rosters.filter(owner_sleeper_id=connection.external_user_id).first()
        if roster:
            return roster
    return rosters.filter(owner_name__iexact=connection.user.username).first()


def _roster_filter_options(rosters):
    entries = [entry for roster in rosters for entry in roster.roster_players.all()]
    nfl_team_ids = {
        entry.player.team_id for entry in entries
        if entry.player_id and entry.player.team_id
    } | {
        entry.team_id for entry in entries
        if entry.player_id is None and entry.team_id
    }
    nfl_teams = Teams.objects.in_bulk(nfl_team_ids)
    options = []
    for entry in entries:
        if entry.player_id:
            player = entry.player
            name = player.full_name
            position = (player.position or "").upper()
            nfl_team = nfl_teams.get(player.team_id)
            headshot_url = player.headshot_url or ""
        elif entry.team:
            name = f"{entry.team.name} D/ST"
            position = "DEF"
            nfl_team = entry.team
            headshot_url = ""
        else:
            continue
        options.append({
            "id": entry.id,
            "name": name,
            "label": f"{name} ({position})",
            "team": entry.roster.owner_name or f"Team {entry.roster.sleeper_roster_id}",
            "position": position,
            "nfl_team": nfl_team.abbreviation if nfl_team else "FA",
            "headshot_url": headshot_url,
        })
    return options


def _current_week():
    return get_current_nfl_week()


def _suggestion_filters(request):
    def parse_number(name, cast):
        raw = request.GET.get(name, "").strip()
        if not raw:
            return None
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return None

    def parse_package_fields(side):
        count = parse_number(f"{side}_count", int)
        if count not in (1, 2, 3):
            count = None
        player_ids = []
        for value in request.GET.getlist(f"{side}_player_id"):
            try:
                if value.strip():
                    player_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return {
            f"{side}_player_ids": player_ids,
            f"{side}_positions": [value.upper() for value in request.GET.getlist(f"{side}_position")],
            f"{side}_count": count,
        }

    filters = {
        "min_age": parse_number("min_age", float),
        "max_age": parse_number("max_age", float),
        "exclude_nfl_teams": {
            value.upper() for value in request.GET.getlist("exclude_nfl_teams")
            if value.strip()
        },
        "acceptable_bye_weeks": {
            int(value) for value in request.GET.getlist("bye_week")
            if value.isdigit() and 1 <= int(value) <= 18
        },
        "prioritize_position": (
            request.GET.get("prioritize_position", "").upper()
            if request.GET.get("prioritize_position", "").upper()
            in {"QB", "RB", "WR", "TE", "K", "DEF"}
            else ""
        ),
    }
    filters.update(parse_package_fields("give"))
    filters.update(parse_package_fields("receive"))
    return filters
