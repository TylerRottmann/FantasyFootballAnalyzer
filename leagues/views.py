import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace

from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldError
from django.db.models import Avg, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import resolve, reverse, Resolver404
from urllib.parse import urlsplit
from django.utils import timezone
import time
from analyzer.models import NFLGame, PlayerWeeklyStats, Teams, TeamWeeklyStats

from .integrations.sleeper import SleeperLeagueService
from .integrations.yahoo import YahooLeagueService
from leagues.services.kicker_scoring import league_projection
from .models import (
    DefenseProjection,
    FantasyLeague,
    FantasyMatchup,
    FantasyRoster,
    FantasyProjection,
    FantasyRosterPlayer,
    Player,
    UserLeagueConnection,
)
from .services.power_rankings import get_saved_power_rankings
from .services.team_breakdown import build_team_breakdown
from .services.matchup_sync import sync_connection_matchups

from scripts.commands.lineup import (
    build_current_lineup,
    build_optimized_lineup,
    get_lineup_total,
)
from scripts.commands.nflweek import get_current_nfl_week


def get_user_league_or_404(user, league_id):
    """Return a league only when it belongs to one of the user's connections."""
    connection = get_object_or_404(
        UserLeagueConnection.objects.select_related("league"),
        user=user,
        league_id=league_id,
    )
    return connection.league


def get_sleeper_playoff_info(league):
    """Return cached playoff-team and first-round-bye counts from Sleeper."""
    cache_key = f"sleeper_playoff_info:{league.sleeper_league_id}"
    missing = object()
    cached = cache.get(cache_key, missing)
    if cached is not missing:
        return cached

    info = None
    try:
        service = SleeperLeagueService(league.sleeper_league_id)
        service.REQUEST_TIMEOUT = 3
        payload = service.get_league() or {}
        settings_data = payload.get("settings") or {}
        playoff_teams = int(settings_data.get("playoff_teams") or 0)
        if playoff_teams > 0:
            bracket_size = 1
            while bracket_size < playoff_teams:
                bracket_size *= 2
            info = {
                "playoff_teams": playoff_teams,
                "first_round_byes": max(0, bracket_size - playoff_teams),
            }
    except (OSError, ValueError, TypeError):
        # The rankings page remains usable if Sleeper metadata is unavailable.
        info = None

    cache.set(cache_key, info, timeout=60 * 60 * 6)
    return info


def get_power_rankings_snapshot(
    league, user, current_week, connection, include_defense=True
):
    """Read the same cached league projection snapshot for rankings and modals."""
    last_matchup_update = FantasyMatchup.objects.filter(
        league=league,
        season=league.season,
        platform=connection.platform if connection else "",
    ).aggregate(updated=Max("updated_at"))["updated"]
    last_sync_timestamp = cache.get(f"matchup_sync:{league.id}:{league.season}")
    if last_sync_timestamp is not None and (
        last_matchup_update is None
        or last_sync_timestamp > last_matchup_update.timestamp()
    ):
        last_matchup_update = datetime.fromtimestamp(
            last_sync_timestamp,
            tz=timezone.get_current_timezone(),
        )
    schedule_sync_needed = (
        last_matchup_update is None
        or last_matchup_update < timezone.now() - timedelta(hours=6)
    )
    schedule_version = last_matchup_update.isoformat() if last_matchup_update else "unsynced"
    defense_mode = "dst-on" if include_defense else "dst-off"
    cache_key = f"power_rankings:{league.id}:{user.id}:{current_week}:{schedule_version}:{defense_mode}"
    snapshot = cache.get(cache_key)
    if snapshot is None:
        snapshot = get_saved_power_rankings(
            league,
            user,
            current_week=current_week,
            include_defense=include_defense,
        )
        cache.set(cache_key, snapshot, timeout=300)
    return snapshot, schedule_sync_needed


# =============================================================
# CONNECT LEAGUE
# =============================================================

@login_required
def connect_league(request):
    context = {}

    if request.method == "POST":
        platform = request.POST.get("platform")

        platform_username = request.POST.get(
            "platform_username", ""
        ).strip()

        league_identifier = request.POST.get(
            "league_identifier", ""
        ).strip()

        if platform == "sleeper":
            try:
                service = SleeperLeagueService(league_identifier)

                result = service.import_league(
                    request.user,
                    platform_username=platform_username,
                )

                connection = UserLeagueConnection.objects.get(
                    user=request.user,
                    league=result["league"],
                )

                roster = FantasyRoster.objects.filter(
                    league=result["league"],
                    owner_sleeper_id=connection.external_user_id,
                ).first()

                if roster is None:
                    context["error"] = (
                        "The league was imported, but your "
                        "roster could not be found."
                    )
                else:
                    request.session["active_league_id"] = (
                        result["league"].id
                    )
                    return redirect("start_sit")

            except Exception as exc:
                context["error"] = str(exc)

        else:
            context["error"] = "Please select a supported platform."

    context["connected_leagues"] = (
        UserLeagueConnection.objects
        .filter(user=request.user)
        .select_related("league")
        .order_by("-league__updated_at")
    )

    return render(request, "leagues/connect.html", context)


# =============================================================
# SELECT LEAGUE
# =============================================================

@login_required
def select_league(request, league_id):
    connection = (
        UserLeagueConnection.objects
        .filter(user=request.user, league_id=league_id)
        .select_related("league")
        .first()
    )

    if connection is None:
        return redirect("connect_league")

    request.session["active_league_id"] = connection.league.id

    referer = request.META.get("HTTP_REFERER")
    if referer:
        try:
            referred_view = resolve(urlsplit(referer).path).url_name
        except Resolver404:
            referred_view = None

        if referred_view in {"power_rankings", "team_breakdown"}:
            return redirect("power_rankings", league_id=connection.league.id)
        return redirect(referer)

    return redirect("start_sit")


def _build_historical_lineups(league, roster, week, starting_positions):
    """Build the played and projected lineups from Sleeper's weekly snapshot."""
    service = SleeperLeagueService(league.sleeper_league_id)
    cache_key = f"sleeper_matchups:{league.sleeper_league_id}:{week}"
    matchups = cache.get(cache_key)
    if matchups is None:
        matchups = service.get_matchups(week)
        cache.set(cache_key, matchups, timeout=60 * 60)

    team_result = next(
        (row for row in matchups if str(row.get("roster_id")) == str(roster.sleeper_roster_id)),
        None,
    )
    if not team_result:
        raise ValueError("Sleeper has no lineup data for this roster and week.")

    sleeper_ids = [str(value) for value in (team_result.get("players") or []) if value]
    human_ids = [value for value in sleeper_ids if not (len(value) == 3 and value.isalpha())]
    db_players = list(Player.objects.filter(sleeper_id__in=human_ids))
    players_by_sleeper_id = {player.sleeper_id: player for player in db_players}
    players_by_id = {player.id: player for player in db_players}
    teams = Teams.objects.in_bulk({p.team_id for p in db_players if p.team_id})

    projection_map = {
        projection.player_id: league_projection(projection, league)
        for projection in FantasyProjection.objects.select_related("player").filter(
            player_id__in=players_by_id,
            season=league.season,
            week=week,
            model_version="v1",
        )
    }

    # Sleeper can provide per-player results using league scoring. Older API
    # responses omit these, so use the app's weekly PPR stats as a fallback.
    points_by_sleeper_id = {
        str(player_id): points
        for player_id, points in (team_result.get("players_points") or {}).items()
    }
    points_basis = "Sleeper league scoring" if points_by_sleeper_id else "PPR stats"
    if not points_by_sleeper_id and db_players:
        weekly_points = PlayerWeeklyStats.objects.filter(
            player_id__in=players_by_id,
            season=league.season,
            week=week,
            season_type="REG",
        ).values_list("player_id", "fantasy_points_ppr")
        for player_id, points in weekly_points:
            player = players_by_id.get(player_id)
            if player and points is not None:
                points_by_sleeper_id[player.sleeper_id] = float(points)

    schedule = NFLGame.objects.filter(
        season=league.season, week=week, game_type="REG",
    ).select_related("home_team", "away_team")
    matchup_by_team_id = {}
    for game in schedule:
        matchup_by_team_id[game.away_team_id] = {
            "opponent": game.home_team, "is_home": False, "game": game,
        }
        matchup_by_team_id[game.home_team_id] = {
            "opponent": game.away_team, "is_home": True, "game": game,
        }

    items_by_sleeper_id = {}
    player_pool = []
    for index, sleeper_id in enumerate(sleeper_ids):
        player = players_by_sleeper_id.get(sleeper_id)
        team = None
        if player is None and len(sleeper_id) == 3 and sleeper_id.isalpha():
            team = Teams.objects.filter(abbreviation__iexact=sleeper_id).first()
        if player is None and team is None:
            continue
        defense_projection = None
        if player is None and team is not None:
            defense_projection = DefenseProjection.objects.filter(
                team=team, season=league.season, week=week,
                model_version="v1",
            ).first()
        item = {
            "player": player,
            "roster_player": SimpleNamespace(id=index + 1, roster_slot="BN"),
            "prediction": (
                projection_map.get(player.id) if player else defense_projection
            ),
            "matchup": matchup_by_team_id.get(player.team_id) if player else None,
            "team": teams.get(player.team_id) if player else team,
            "is_defense": player is None,
            "actual_points": points_by_sleeper_id.get(sleeper_id),
        }
        items_by_sleeper_id[sleeper_id] = item
        player_pool.append(item)

    actual_starters = team_result.get("starters") or []
    actual_lineup = []
    for index, slot in enumerate(starting_positions):
        sleeper_id = str(actual_starters[index]) if index < len(actual_starters) and actual_starters[index] else None
        actual_lineup.append({"slot": slot, "item": items_by_sleeper_id.get(sleeper_id) if sleeper_id else None})

    starter_ids = {
        id(entry["item"]) for entry in actual_lineup if entry["item"] is not None
    }
    played_bench = [item for item in player_pool if id(item) not in starter_ids]
    actual_total = sum(
        float(entry["item"]["actual_points"])
        for entry in actual_lineup
        if entry["item"] is not None and entry["item"]["actual_points"] is not None
    )
    current_projected_total = get_lineup_total(actual_lineup)

    optimized_lineup, projected_total = build_optimized_lineup(
        player_pool, starting_positions,
    )
    optimized_starter_ids = {
        id(entry["item"]) for entry in optimized_lineup if entry["item"] is not None
    }
    optimized_bench = [item for item in player_pool if id(item) not in optimized_starter_ids]
    optimized_actual_total = sum(
        float(entry["item"]["actual_points"])
        for entry in optimized_lineup
        if entry["item"] is not None and entry["item"]["actual_points"] is not None
    )
    return {
        "players": player_pool,
        "current_lineup": actual_lineup,
        "starters": [entry["item"] for entry in actual_lineup if entry["item"]],
        "bench": played_bench,
        "current_total": actual_total,
        "current_projected_total": current_projected_total,
        "optimized_lineup": optimized_lineup,
        "optimized_bench": optimized_bench,
        "optimized_total": projected_total,
        "optimized_actual_total": optimized_actual_total,
        "projections_available": bool(projection_map),
        "points_basis": points_basis,
    }


# =============================================================
# START / SIT
# =============================================================

@login_required
def start_sit(request):
    active_league_id = request.session.get("active_league_id")

    connection = None

    if active_league_id:
        connection = (
            UserLeagueConnection.objects
            .filter(
                user=request.user,
                league_id=active_league_id,
            )
            .select_related("league")
            .first()
        )

    if connection is None:
        connection = (
            UserLeagueConnection.objects
            .filter(user=request.user)
            .select_related("league")
            .order_by("-league__updated_at")
            .first()
        )

    if connection is None:
        return redirect("connect_league")

    league = connection.league
    request.session["active_league_id"] = league.id

    # ---------------------------------------------------------
    # FIND USER'S ROSTER
    # ---------------------------------------------------------

    roster = (
        FantasyRoster.objects
        .filter(
            league=league,
            owner_sleeper_id=connection.external_user_id,
        )
        .first()
    )

    if roster is None:
        messages.error(
            request,
            "Your roster could not be found for this league.",
        )
        return redirect("connect_league")

    # ---------------------------------------------------------
    # CURRENT NFL WEEK
    # ---------------------------------------------------------

    current_week = get_current_nfl_week()

    try:
        week = int(request.GET.get("week", current_week))
    except (TypeError, ValueError):
        week = current_week

    week = max(1, min(18, week))

    # ---------------------------------------------------------
    # GET ROSTER PLAYERS
    # ---------------------------------------------------------

    roster_players = list(
        roster.roster_players
        .select_related("player", "team")
        .all()
    )

    # ---------------------------------------------------------
    # GET UNIVERSAL PROJECTIONS
    # ---------------------------------------------------------

    player_ids = [
        roster_player.player_id
        for roster_player in roster_players
        if roster_player.player_id is not None
    ]

    projections = FantasyProjection.objects.select_related("player").filter(
        player_id__in=player_ids,
        season=league.season,
        week=week,
        model_version="v1",
    )

    projection_map = {
        projection.player_id: league_projection(projection, league)
        for projection in projections
    }

    projections_available = bool(projection_map)
    projections_required = not projections_available

    # ---------------------------------------------------------
    # GET TEAM INFORMATION
    # ---------------------------------------------------------

    team_ids = {
        roster_player.player.team_id
        for roster_player in roster_players
        if (
            roster_player.player is not None
            and roster_player.player.team_id is not None
        )
    }

    team_ids.update(
        roster_player.team_id
        for roster_player in roster_players
        if roster_player.team_id is not None
    )

    teams = Teams.objects.in_bulk(team_ids)

    matchups = {}
    schedule_games = (
        NFLGame.objects
        .filter(season=league.season, week=week)
        .filter(Q(away_team_id__in=team_ids) | Q(home_team_id__in=team_ids))
        .select_related("away_team", "home_team")
        .order_by("id")
    )
    for game in schedule_games:
        matchups.setdefault(game.away_team_id, {
            "opponent": game.home_team,
            "is_home": False,
            "game": game,
        })
        matchups.setdefault(game.home_team_id, {
            "opponent": game.away_team,
            "is_home": True,
            "game": game,
        })

    # ---------------------------------------------------------
    # BUILD PLAYER DATA
    # ---------------------------------------------------------

    players = []

    defense_projection_map = {
        projection.team_id: projection
        for projection in DefenseProjection.objects.filter(
            team_id__in=[
                roster_player.team_id
                for roster_player in roster_players
                if roster_player.player is None
                and roster_player.team_id is not None
            ],
            season=league.season,
            week=week,
            model_version="v1",
        )
    }

    for roster_player in roster_players:
        # D/ST
        if roster_player.player is None:
            defense_team = roster_player.team
            matchup = matchups.get(defense_team.id) if defense_team else None

            players.append({
                "player": None,
                "roster_player": roster_player,
                "prediction": (
                    defense_projection_map.get(defense_team.id)
                    if defense_team else None
                ),
                "matchup": matchup,
                "team": defense_team,
                "is_defense": True,
            })
            continue

        # Normal player
        player = roster_player.player
        prediction = projection_map.get(player.id)

        matchup = matchups.get(player.team_id) if player.team_id else None

        players.append({
            "player": player,
            "roster_player": roster_player,
            "prediction": prediction,
            "matchup": matchup,
            "team": teams.get(player.team_id),
            "is_defense": False,
        })

    # ---------------------------------------------------------
    # STARTING POSITIONS
    # ---------------------------------------------------------

    starting_positions = [
        slot
        for slot in (league.roster_positions or [])
        if slot not in {"BN", "IR", "TAXI"}
    ]

    # ---------------------------------------------------------
    # CURRENT LINEUP
    # ---------------------------------------------------------

    current_lineup = build_current_lineup(
        players,
        starting_positions,
    )

    current_starter_roster_ids = {
        entry["item"]["roster_player"].id
        for entry in current_lineup
        if entry["item"] is not None
    }

    starters = [
        item
        for item in players
        if item["roster_player"].id in current_starter_roster_ids
    ]

    bench = [
        item
        for item in players
        if item["roster_player"].id not in current_starter_roster_ids
    ]

    current_total = get_lineup_total(current_lineup)

    # ---------------------------------------------------------
    # OPTIMIZED LINEUP
    # ---------------------------------------------------------

    optimized_lineup = []
    optimized_total = 0

    if projections_available:
        start_time = time.perf_counter()

        optimized_lineup, optimized_total = build_optimized_lineup(
            players,
            starting_positions,
        )

        print(
            f"OPTIMIZER TOOK "
            f"{time.perf_counter() - start_time:.3f} seconds"
        )

    optimized_roster_ids = {
        entry["item"]["roster_player"].id
        for entry in optimized_lineup
        if entry["item"] is not None
    }

    if projections_available:
        optimized_bench = [
            item
            for item in players
            if item["roster_player"].id not in optimized_roster_ids
        ]
    else:
        optimized_bench = bench

    historical_mode = False
    historical_error = None
    historical_points_basis = "Sleeper league scoring"
    current_projected_total = None
    if week < current_week:
        if connection.platform != UserLeagueConnection.PLATFORM_SLEEPER:
            historical_error = "Historical lineup comparisons are currently available for Sleeper leagues."
        else:
            try:
                historical = _build_historical_lineups(
                    league, roster, week, starting_positions,
                )
                players = historical["players"]
                current_lineup = historical["current_lineup"]
                starters = historical["starters"]
                bench = historical["bench"]
                current_total = historical["current_total"]
                current_projected_total = historical["current_projected_total"]
                optimized_lineup = historical["optimized_lineup"]
                optimized_bench = historical["optimized_bench"]
                optimized_total = historical["optimized_total"]
                optimized_actual_total = historical["optimized_actual_total"]
                historical_points_basis = historical["points_basis"]
                projections_available = historical["projections_available"]
                projections_required = not projections_available
                historical_mode = True
                if not any(item.get("actual_points") is not None for item in players):
                    historical_points_basis = "PPR stats unavailable"
            except Exception:
                historical_error = (
                    "Sleeper's historical lineup could not be loaded. "
                    "The current roster is shown instead."
                )

    # ---------------------------------------------------------
    # TEMPLATE CONTEXT
    # ---------------------------------------------------------

    context = {
        "league": league,
        "roster": roster,
        "players": players,
        "starters": starters,
        "bench": bench,
        "current_lineup": current_lineup,
        "current_total": current_total,
        "optimized_lineup": optimized_lineup,
        "optimized_bench": optimized_bench,
        "optimized_total": optimized_total,
        "season": league.season,
        "week": week,
        "current_week": current_week,
        "weeks": range(1, 19),
        "starting_positions": starting_positions,
        "projections_required": projections_required,
        "projections_available": projections_available,
        "historical_mode": historical_mode,
        "historical_error": historical_error,
        "historical_points_basis": historical_points_basis,
        "current_projected_total": current_projected_total,
        "optimized_actual_total": optimized_actual_total if historical_mode else None,
        "historical_difference": (
            round(optimized_actual_total - current_total, 1)
            if historical_mode and projections_available else None
        ),
        "historical_difference_abs": (
            abs(round(optimized_actual_total - current_total, 1))
            if historical_mode and projections_available else None
        ),
        "algorithm_projection_gaps": (
            historical_mode and any(
                item.get("player") is not None
                and (
                    item.get("prediction") is None
                    or item["prediction"].projected_fantasy_points is None
                )
                for item in players
            )
        ),
    }

    return render(
        request,
        "start_sit/start-sit.html",
        context,
    )


@login_required
def projection_details(request, player_id):
    """Return historical model inputs for a rostered player on demand."""
    active_league_id = request.session.get("active_league_id")
    connection = (
        UserLeagueConnection.objects
        .filter(user=request.user, league_id=active_league_id)
        .select_related("league")
        .first()
    ) if active_league_id else None
    if connection is None:
        return JsonResponse({"error": "Select a connected league first."}, status=404)

    try:
        week = int(request.GET.get("week", 1))
    except (TypeError, ValueError):
        week = 1
    week = max(1, min(18, week))
    league = connection.league

    rostered = FantasyRosterPlayer.objects.filter(
        roster__league=league,
        roster__owner_sleeper_id=connection.external_user_id,
        player_id=player_id,
    ).exists()
    if not rostered:
        return JsonResponse({"error": "Player is not on your active roster."}, status=404)

    player = get_object_or_404(Player, pk=player_id)
    position = (player.position or "").upper()
    if position == "QB":
        from scripts.algorithm.features.qb_features import build_qb_features
        features = build_qb_features(player, league.season, week)
        groups = {
            "player": [
                ("PPR points", "fantasy_points"), ("Pass attempts", "passing_attempts"),
                ("Pass yards", "passing_yards"), ("Pass TD", "passing_tds"),
                ("Interceptions", "interceptions"), ("Rush attempts", "rushing_attempts"),
                ("Rush yards", "rushing_yards"), ("Rush TD", "rushing_tds"),
            ],
            "team": [("Points", "team_points"), ("Pass yards", "team_passing_yards"),
                     ("Rush yards", "team_rushing_yards"), ("Total yards", "team_total_yards")],
        }
        allowed_field = "qb_fantasy_points_allowed"
        recent_allowed_key = "opponent_qb_fantasy_allowed_l3"
    elif position == "WR":
        from scripts.algorithm.features.wr_features import build_wr_features
        features = build_wr_features(player, league.season, week)
        groups = {
            "player": [
                ("PPR points", "fantasy_points"), ("Targets", "targets"),
                ("Receptions", "receptions"), ("Receiving yards", "receiving_yards"),
                ("Receiving TD", "receiving_tds"), ("Target share", "target_share"),
                ("Catch rate", "catch_rate"),
            ],
            "team": [("Points", "team_points"), ("Pass yards", "team_passing_yards"),
                     ("Rush yards", "team_rushing_yards"), ("Total yards", "team_total_yards")],
        }
        allowed_field = "wr_fantasy_points_allowed"
        recent_allowed_key = "opponent_wr_fantasy_allowed_l3"
    elif position == "RB":
        from scripts.algorithm.features.rb_features import build_rb_features
        features = build_rb_features(player, league.season, week)
        groups = {
            "player": [
                ("PPR points", "fantasy_points"), ("Rush attempts", "carries"),
                ("Rush yards", "rushing_yards"), ("Rush TD", "rushing_tds"),
                ("Targets", "targets"), ("Receptions", "receptions"),
                ("Receiving yards", "receiving_yards"), ("Receiving TD", "receiving_tds"),
                ("Touches", "touches"), ("Opportunities", "opportunities"),
                ("Carry share", "carry_share"), ("Target share", "target_share"),
                ("Catch rate", "catch_rate"),
            ],
            "team": [("Points", "team_points"), ("Pass yards", "team_passing_yards"),
                     ("Rush yards", "team_rushing_yards"), ("Total yards", "team_total_yards")],
        }
        allowed_field = "rb_fantasy_points_allowed"
        recent_allowed_key = "opponent_rb_fantasy_allowed_l3"
    elif position == "K":
        from scripts.algorithm.features.k_features import build_k_features
        try:
            features = build_k_features(player, league.season, week)
        except (FileNotFoundError, ValueError):
            return JsonResponse({"error": "Kicker source data is unavailable for this season."}, status=200)
        groups = {
            "player": [("FG attempts", "fg_att"), ("FG made", "fg_made"),
                       ("FG missed (including blocked)", "fg_missed"),
                       ("PAT made", "pat_made"), ("PAT missed (including blocked)", "pat_missed")],
            "team": [("Points", "team_points_for"), ("Total yards", "team_total_yards")],
        }
        allowed_field = "kicking_points_against"
        recent_allowed_key = "opponent_kicking_points_against_l3"
    elif position == "TE":
        stat_keys = [
            ("PPR points", "fantasy_points"), ("Targets", "targets"),
            ("Receptions", "receptions"), ("Receiving yards", "receiving_yards"),
            ("Receiving TD", "receiving_tds"),
        ]
        history = list(PlayerWeeklyStats.objects.filter(
            player_id=player_id, season=league.season, season_type="REG", week__lt=week,
        ).order_by("week"))

        def recent_average(field, rows):
            valid = [getattr(row, field) for row in rows if getattr(row, field) is not None]
            return sum(valid) / len(valid) if valid else None

        features = {"game_status": "BYE", "team_id": player.team_id,
                    "opponent_team_id": None, "opponent_team": None, "is_home": None}
        if player.team_id:
            game = NFLGame.objects.filter(
                season=league.season, week=week, game_type="REG",
            ).filter(Q(home_team_id=player.team_id) | Q(away_team_id=player.team_id)).first()
            if game:
                opponent_id = game.away_team_id if game.home_team_id == player.team_id else game.home_team_id
                opponent = Teams.objects.filter(pk=opponent_id).first()
                features.update(game_status="GAME", opponent_team_id=opponent_id,
                                opponent_team=opponent.abbreviation if opponent else None,
                                is_home=game.home_team_id == player.team_id)
        db_fields = {
            "fantasy_points": "fantasy_points_ppr", "rushing_attempts": "carries",
            "rushing_yards": "rushing_yards", "rushing_tds": "rushing_tds",
            "targets": "targets", "receptions": "receptions",
            "receiving_yards": "receiving_yards", "receiving_tds": "receiving_tds",
        }
        for _, key in stat_keys:
            field = db_fields[key]
            features[f"{key}_l1"] = recent_average(field, history[-1:])
            features[f"{key}_l3"] = recent_average(field, history[-3:])
            features[f"{key}_season"] = recent_average(field, history)
        team_history = list(TeamWeeklyStats.objects.filter(
            team_id=player.team_id, season=league.season, season_type=1, week__lt=week,
        ).order_by("week")) if player.team_id else []
        for label, key, field in [
            ("Points", "team_points", "points_for"), ("Pass yards", "team_passing_yards", "passing_yards"),
            ("Rush yards", "team_rushing_yards", "rushing_yards"), ("Total yards", "team_total_yards", "total_yards"),
        ]:
            features[f"{key}_l3"] = recent_average(field, team_history[-3:])
            features[f"{key}_season"] = recent_average(field, team_history)
        groups = {"player": stat_keys, "team": [(label, key) for label, key, _ in [
            ("Points", "team_points", "points_for"), ("Pass yards", "team_passing_yards", "passing_yards"),
            ("Rush yards", "team_rushing_yards", "rushing_yards"), ("Total yards", "team_total_yards", "total_yards"),
        ]]}
        allowed_field = f"{position.lower()}_fantasy_points_allowed"
        recent_allowed_key = None
    else:
        return JsonResponse({"error": "Detailed stats are not available for this position."}, status=200)

    def values_for(fields):
        return [
            {"label": label, "last": features.get(f"{key}_l1"),
             "last3": features.get(f"{key}_l3"), "season": features.get(f"{key}_season"),
             "percent": key in {"carry_share", "target_share", "catch_rate"}}
            for label, key in fields
        ]

    opponent_id = features.get("opponent_team_id")
    defense_rank = None
    defense_count = 0
    defense_season = None
    recent_allowed = features.get(recent_allowed_key) if recent_allowed_key else None
    if opponent_id:
        recent_defense = list(TeamWeeklyStats.objects.filter(
            team_id=opponent_id, season=league.season, season_type=1, week__lt=week,
        ).order_by("week").values_list(allowed_field, flat=True))
        recent_defense = [float(value) for value in recent_defense[-3:] if value is not None]
        recent_allowed = sum(recent_defense) / len(recent_defense) if recent_defense else None
        ranked = list(
            TeamWeeklyStats.objects.filter(
                season=league.season, season_type=1, week__lt=week,
            ).values("team_id").annotate(avg_allowed=Avg(allowed_field))
            .exclude(avg_allowed__isnull=True).order_by("avg_allowed", "team_id")
        )
        defense_count = len(ranked)
        for rank, row in enumerate(ranked, 1):
            if row["team_id"] == opponent_id:
                defense_rank = rank
                defense_season = row["avg_allowed"]
                break

    team_id = features.get("team_id")
    team_last_game = None
    if team_id:
        team_last_game = (
            TeamWeeklyStats.objects.filter(
                team_id=team_id,
                season=league.season,
                season_type=1,
                week__lt=week,
            ).order_by("-week").first()
        )
    team_stat_rows = values_for(groups["team"])
    team_last_fields = {
        "Points": "points_for",
        "Pass yards": "passing_yards",
        "Rush yards": "rushing_yards",
        "Total yards": "total_yards",
    }
    if team_last_game:
        for row in team_stat_rows:
            row["last"] = getattr(team_last_game, team_last_fields[row["label"]])

    return JsonResponse({
        "position": position,
        "season": league.season,
        "week": week,
        "game_status": features.get("game_status"),
        "opponent": features.get("opponent_team"),
        "home": features.get("is_home"),
        "player_stats": values_for(groups["player"]),
        "team_stats": team_stat_rows,
        "defense": {
            "opponent": features.get("opponent_team"),
            "position_allowed": recent_allowed,
            "season_allowed": defense_season,
            "rank": defense_rank,
            "rank_count": defense_count,
        },
    })


# =============================================================
# YAHOO CONNECT
# =============================================================

@login_required
def yahoo_connect(request):
    state = secrets.token_urlsafe(32)
    request.session["yahoo_oauth_state"] = state

    authorization_url = YahooLeagueService.build_authorization_url(
        state
    )

    return redirect(authorization_url)


# =============================================================
# YAHOO CALLBACK
# =============================================================

@login_required
def yahoo_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")

    expected_state = request.session.pop("yahoo_oauth_state", None)

    if not state or state != expected_state:
        messages.error(
            request,
            "Yahoo authorization failed: invalid state.",
        )
        return redirect("/")

    if not code:
        error = request.GET.get("error", "unknown_error")
        messages.error(
            request,
            f"Yahoo authorization failed: {error}.",
        )
        return redirect("/")

    # Yahoo token exchange will go here.
    return redirect("/")


# =============================================================
# RESYNC LEAGUE
# =============================================================

@login_required
def resync_league(request):
    if request.method != "POST":
        return redirect("start_sit")

    active_league_id = request.session.get("active_league_id")

    if active_league_id is None:
        messages.error(request, "No active league is selected.")
        return redirect("start_sit")

    connection = (
        UserLeagueConnection.objects
        .filter(
            user=request.user,
            league_id=active_league_id,
        )
        .select_related("league")
        .first()
    )

    if connection is None:
        messages.error(
            request,
            "Your active league connection could not be found.",
        )
        return redirect("start_sit")

    if connection.platform != UserLeagueConnection.PLATFORM_SLEEPER:
        messages.error(
            request,
            "Only Sleeper leagues can currently be resynced.",
        )
        return redirect("start_sit")

    try:
        service = SleeperLeagueService(
            connection.league.sleeper_league_id
        )

        service.import_league(
            request.user,
            platform_username=request.user.sleeper_username,
        )

        league = FantasyLeague.objects.get(
            id=connection.league.id
        )

        messages.success(
            request,
            f"{league.name} was successfully resynced with Sleeper.",
        )

    except Exception as exc:
        messages.error(
            request,
            f"Unable to resync league: {exc}",
        )

    return redirect("start_sit")


@login_required
def power_rankings(request, league_id):
    league = get_user_league_or_404(request.user, league_id)
    current_week = get_current_nfl_week()
    connection = UserLeagueConnection.objects.filter(
        user=request.user,
        league=league,
    ).only("platform").first()
    has_defense_slot = any(
        str(position).upper() in {"DEF", "D/ST"}
        for position in (league.roster_positions or [])
    )
    include_defense = (
        request.GET.get("include_defense", "1") != "0"
        if has_defense_slot else False
    )
    cached_rankings, schedule_sync_needed = get_power_rankings_snapshot(
        league, request.user, current_week, connection, include_defense
    )
    rankings, league_average_points, generated_at = cached_rankings
    playoff_info = (
        get_sleeper_playoff_info(league)
        if connection and connection.platform == UserLeagueConnection.PLATFORM_SLEEPER
        else None
    )
    chart_positions = [
        {"value": "QB", "label": "QB starters"},
        {"value": "RB", "label": "RB starters"},
        {"value": "WR", "label": "WR starters"},
        {"value": "TE", "label": "TE starters"},
        {"value": "DEF", "label": "DEF starters"},
        {"value": "BENCH_QB", "label": "Bench QB"},
        {"value": "BENCH_RB", "label": "Bench RB"},
        {"value": "BENCH_WR", "label": "Bench WR"},
        {"value": "BENCH_TE", "label": "Bench TE"},
        {"value": "BENCH_DEF", "label": "Bench DEF"},
        {"value": "BENCH_TOTAL", "label": "Bench total"},
    ]
    if not include_defense:
        chart_positions = [
            position for position in chart_positions
            if position["value"] not in {"DEF", "BENCH_DEF"}
        ]
    position_chart_data = {
        position["value"]: [
            {
                "team": row["team_name"],
                "average": row["position_averages"].get(position["value"], 0.0),
                "is_user_team": row["is_user_team"],
            }
            for row in rankings
        ]
        for position in chart_positions
    }

    return render(request, "leagues/power_rankings.html", {
        "league": league,
        "rankings": rankings,
        "league_average_points": league_average_points,
        "generated_at": generated_at,
        "chart_positions": chart_positions,
        "position_chart_data": position_chart_data,
        "schedule_sync_needed": schedule_sync_needed,
        "playoff_info": playoff_info,
        "has_defense_slot": has_defense_slot,
        "include_defense": include_defense,
        "sync_matchups_url": reverse("sync_matchups", args=[league.id]),
    })


@login_required
def sync_matchups(request, league_id):
    if request.method != "POST":
        return redirect("power_rankings", league_id=league_id)

    connection = get_object_or_404(
        UserLeagueConnection.objects.select_related("league", "user"),
        user=request.user,
        league_id=league_id,
    )
    wants_json = "application/json" in request.headers.get("Accept", "")
    sync_cache_key = f"matchup_sync:{connection.league.id}:{connection.league.season}"
    force_sync = request.POST.get("force") == "1"
    last_sync = cache.get(sync_cache_key)
    if not force_sync and last_sync is not None and timezone.now().timestamp() - last_sync < 6 * 60 * 60:
        if wants_json:
            return JsonResponse({"status": "fresh", "synced": 0})
        return redirect("power_rankings", league_id=league_id)

    lock_key = f"matchup_sync_lock:{connection.league.id}:{connection.league.season}"
    if not cache.add(lock_key, True, timeout=5 * 60):
        if wants_json:
            return JsonResponse({"status": "running", "synced": 0})
        return redirect("power_rankings", league_id=league_id)

    try:
        current_week = get_current_nfl_week()
        imported = sync_connection_matchups(
            connection,
            current_week=current_week,
        )
        cache.set(sync_cache_key, timezone.now().timestamp(), timeout=6 * 60 * 60)
        if wants_json:
            return JsonResponse({"status": "synced", "synced": imported})
        messages.success(request, f"Synced {imported} weekly schedule and result records for {connection.league.name}.")
    except Exception as exc:
        if wants_json:
            return JsonResponse({"status": "error", "error": str(exc)}, status=502)
        messages.error(request, f"Unable to sync schedule and results: {exc}")
    finally:
        cache.delete(lock_key)

    return redirect("power_rankings", league_id=league_id)


@login_required
def team_breakdown(request, league_id, roster_id):
    league = get_user_league_or_404(request.user, league_id)
    roster = get_object_or_404(
        FantasyRoster,
        pk=roster_id,
        league=league,
    )
    connection = UserLeagueConnection.objects.filter(
        user=request.user,
        league=league,
    ).only("platform").first()
    has_defense_slot = any(
        str(position).upper() in {"DEF", "D/ST"}
        for position in (league.roster_positions or [])
    )
    include_defense = (
        request.GET.get("include_defense", "1") != "0"
        if has_defense_slot else False
    )
    current_week = get_current_nfl_week()
    (rankings, _, _), _ = get_power_rankings_snapshot(
        league, request.user, current_week, connection, include_defense
    )
    breakdown = build_team_breakdown(
        league,
        roster,
        current_week,
        rankings,
        request.user,
        include_defense=include_defense,
    )
    context = {
        "league": league,
        "roster": roster,
        "has_defense_slot": has_defense_slot,
        "include_defense": include_defense,
        **breakdown,
    }
    template = (
        "leagues/team_breakdown_modal.html"
        if request.GET.get("modal") == "1"
        else "leagues/team_breakdown.html"
    )
    return render(request, template, {
        **context,
    })
