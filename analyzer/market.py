"""League-scoped player market rankings and comparison views."""

from math import ceil, isfinite
from datetime import date
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse

from analyzer.models import PlayerADP, PlayerMarketProjection, Players, Teams
from leagues.models import DefenseProjection, FantasyProjection
from leagues.services.context_processors import league_selector
from leagues.services.scoring import score_projection, score_stat_line
from scripts.commands.nflweek import get_current_nfl_week


PLAYER_POSITIONS = ("QB", "RB", "WR", "TE", "K")
ALL_POSITIONS = (*PLAYER_POSITIONS, "DST")
FLEX_POSITIONS = frozenset({"RB", "WR", "TE"})
PAGE_SIZE = 25
DEFAULT_SORTS = {
    "our_weekly": "desc",
    "sleeper_weekly": "desc",
    "adp": "asc",
    "our_ros": "desc",
    "sleeper_ros": "desc",
}

SLEEPER_SKILL_FIELDS = {
    "passing_yards": "pass_yd",
    "passing_tds": "pass_td",
    "passing_interceptions": "pass_int",
    "passing_2pt_conversions": "pass_2pt",
    "rushing_yards": "rush_yd",
    "rushing_tds": "rush_td",
    "rushing_2pt_conversions": "rush_2pt",
    "carries": "rush_att",
    "targets": "rec_tgt",
    "receptions": "rec",
    "receiving_yards": "rec_yd",
    "receiving_tds": "rec_td",
    "receiving_2pt_conversions": "rec_2pt",
    "fumbles_lost": "fum_lost",
}


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _adp_scoring_format(league):
    settings = league.scoring_settings if league else {}
    rules = settings.get("rules", {}) if isinstance(settings, dict) else {}
    reception_points = rules.get("rec") if isinstance(rules, dict) else None
    if reception_points is None and league:
        reception_points = league.ppr
    reception_points = _finite(reception_points, 1.0)
    if reception_points <= 0.1:
        return "std", "Standard"
    if reception_points <= 0.75:
        return "half_ppr", "Half PPR"
    return "ppr", "Full PPR"


def _normalize_sleeper_stats(position, stats):
    stats = stats if isinstance(stats, dict) else {}
    if position != "K" and position != "DST":
        return {
            field: _finite(stats.get(source_field))
            for field, source_field in SLEEPER_SKILL_FIELDS.items()
        }

    if position == "DST":
        return {
            "sacks": _finite(stats.get("sack")),
            "interceptions": _finite(stats.get("int")),
            "fumble_recoveries": _finite(stats.get("fum_rec")),
            "forced_fumbles": _finite(stats.get("ff")),
            "defensive_tds": _finite(stats.get("def_td")),
            "special_teams_tds": _finite(stats.get("def_st_td")),
            "safeties": _finite(stats.get("safe")),
            "points_allowed": _finite(stats.get("pts_allow")),
        }

    from scripts.algorithm.k.feature_names import BUCKETS

    made_total = _finite(stats.get("fgm"))
    made = {
        "0_19": _finite(stats.get("fgm_0_19")),
        "20_29": _finite(stats.get("fgm_20_29")),
        "30_39": _finite(stats.get("fgm_30_39")),
        "40_49": _finite(stats.get("fgm_40_49")),
        "50_59": _finite(stats.get("fgm_50_59", stats.get("fgm_50p"))),
        "60_": _finite(stats.get("fgm_60p")),
    }
    known_made = sum(made[bucket] for bucket in BUCKETS if bucket != "0_19")
    if not made["0_19"]:
        made["0_19"] = max(0.0, made_total - known_made)

    missed_total = max(0.0, _finite(stats.get("fga")) - made_total)
    missed = {
        "0_19": _finite(stats.get("fgmiss_0_19")),
        "20_29": _finite(stats.get("fgmiss_20_29")),
        "30_39": _finite(stats.get("fgmiss_30_39")),
        "40_49": _finite(stats.get("fgmiss_40_49")),
        "50_59": _finite(stats.get("fgmiss_50_59", stats.get("fgmiss_50p"))),
        "60_": _finite(stats.get("fgmiss_60p")),
    }
    known_missed = sum(missed[bucket] for bucket in BUCKETS if bucket != "0_19")
    if not missed["0_19"]:
        missed["0_19"] = max(0.0, missed_total - known_missed)

    return {
        **{f"fg_made_{bucket}": made[bucket] for bucket in BUCKETS},
        **{f"fg_missed_{bucket}": missed[bucket] for bucket in BUCKETS},
        "pat_made": _finite(stats.get("xpm")),
        "pat_missed": _finite(stats.get("xpmiss")),
        "fg_blocked": 0.0,
        "pat_blocked": 0.0,
        "fg_made_distance": _finite(stats.get("fgm_yds")),
        "fg_made_yards_over_30": _finite(stats.get("fgm_yds_over_30")),
    }


def _score_sleeper_projection(row, league):
    if row is None:
        return None
    if not row.projection_available:
        return 0.0
    stat_line = _normalize_sleeper_stats(row.position, row.projected_stats)
    position = "DEF" if row.position == "DST" else row.position
    try:
        points = score_stat_line(stat_line, league.scoring_settings, position)
    except (TypeError, ValueError):
        settings = league.scoring_settings if isinstance(league.scoring_settings, dict) else {}
        rules = settings.get("rules", {})
        receptions = _finite(rules.get("rec"), _finite(league.ppr, 1.0))
        fallback = (
            row.sleeper_standard if receptions <= 0.1
            else row.sleeper_half_ppr if receptions <= 0.75
            else row.sleeper_ppr
        )
        points = float(fallback)
    return round(float(points), 2) if isfinite(float(points)) else None


def _score_our_player_projection(projection, league):
    if projection.status in {"bye", "inactive", "injury_out", "qb_backup"}:
        return 0.0
    return score_projection({
        "position": projection.player.position,
        "projected_stats": projection.projected_stats,
        "projected_fantasy_points": projection.projected_fantasy_points,
    }, league)


def _score_our_defense_projection(projection, league):
    if projection.status == "bye":
        return 0.0
    try:
        return score_stat_line(projection.projected_stats or {}, league.scoring_settings, "DEF")
    except (TypeError, ValueError):
        return None


def _market_recommendation(our_rank, sleeper_rank):
    """Compare consensus ranks with a rank-gap threshold that widens down-list."""
    if our_rank is None or sleeper_rank is None:
        return None
    rank_gap = sleeper_rank - our_rank
    threshold = max(5, ceil(((our_rank + sleeper_rank) / 2) * 0.05))
    if rank_gap >= threshold:
        return "buy"
    if rank_gap <= -threshold:
        return "sell"
    return "hold"


def _filtered_rows(request):
    context = league_selector(request)
    league = context["active_league"]
    active_market_tab = (
        "short"
        if request.resolver_match.url_name == "market_short_term"
        else "long"
    )
    try:
        week = int(request.GET.get("week") or get_current_nfl_week())
        if not 1 <= week <= 18:
            raise ValueError
    except (RuntimeError, TypeError, ValueError):
        week = 1

    position = request.GET.get("position", "").strip().upper()
    if position not in {"", "FLEX", *ALL_POSITIONS}:
        position = ""
    search = request.GET.get("search", "").strip()[:100]
    team_id = request.GET.get("team", "").strip()
    if not team_id.isdecimal():
        team_id = ""
    signal_filter = request.GET.get("signal", "").strip().lower()
    if active_market_tab != "long" or signal_filter not in {"buy", "hold", "sell"}:
        signal_filter = ""

    context.update({
        "market_season": league.season if league and league.season else date.today().year,
        "market_week": week,
        "selected_position": position,
        "selected_team": team_id,
        "selected_signal": signal_filter,
        "search": search,
        "positions": ALL_POSITIONS,
        "weeks": range(1, 19),
        "teams": Teams.objects.filter(is_active=True).order_by("abbreviation"),
        "page_size": PAGE_SIZE,
        "position_choices": (("", "All positions"), ("FLEX", "FLEX (RB / WR / TE)"))
        + tuple((supported_position, supported_position) for supported_position in ALL_POSITIONS),
        "active_market_tab": active_market_tab,
    })

    if league is None:
        query_without_page = request.GET.copy()
        query_without_page.pop("page", None)
        short_params = query_without_page.copy()
        short_params.pop("signal", None)
        short_query = short_params.urlencode()
        long_query = query_without_page.urlencode()
        short_url = reverse("market_short_term") + (f"?{short_query}" if short_query else "")
        long_url = reverse("market_long_term") + (f"?{long_query}" if long_query else "")
        default_sort = "our_weekly" if context["active_market_tab"] == "short" else "our_ros"
        context.update({
            "short_term_url": short_url,
            "long_term_url": long_url,
            "sort": default_sort,
            "direction": DEFAULT_SORTS[default_sort],
            "sort_urls": {},
            "page_query": query_without_page.urlencode(),
            "adp_scoring_label": "—",
            "market_season": None,
        })
        context.update({
            "market_rows": [],
            "page_obj": Paginator([], PAGE_SIZE).get_page(1),
            "market_error": "Connect a league to use its scoring settings on Market.",
            "has_week_data": False,
            "has_ros_data": False,
        })
        return context

    season = league.season or date.today().year
    context["market_season"] = season
    adp_format, adp_label = _adp_scoring_format(league)
    context["adp_scoring_label"] = adp_label

    players = list(
        Players.objects.filter(position__in=PLAYER_POSITIONS)
        .exclude(full_name__isnull=True)
        .exclude(full_name="")
        .select_related("team")
        .order_by("full_name", "id")
    )
    teams = list(Teams.objects.filter(is_active=True).order_by("abbreviation"))

    rows = []
    rows_by_entity = {}
    for player in players:
        row = {
            "entity_key": f"player:{player.pk}",
            "player": player,
            "team": player.team,
            "display_name": player.full_name,
            "position": player.position,
            "age": player.age,
            "weekly_our": None,
            "weekly_sleeper": None,
            "adp": None,
            "our_ros": None,
            "sleeper_ros": None,
        }
        rows.append(row)
        rows_by_entity[row["entity_key"]] = row

    for team in teams:
        row = {
            "entity_key": f"team:{team.pk}",
            "player": None,
            "team": team,
            "display_name": f"{team.name} D/ST",
            "position": "DST",
            "age": None,
            "weekly_our": None,
            "weekly_sleeper": None,
            "adp": None,
            "our_ros": None,
            "sleeper_ros": None,
        }
        rows.append(row)
        rows_by_entity[row["entity_key"]] = row

    if position == "FLEX":
        rows = [row for row in rows if row["position"] in FLEX_POSITIONS]
    elif position:
        rows = [row for row in rows if row["position"] == position]
    if team_id:
        rows = [row for row in rows if row["team"] and str(row["team"].pk) == team_id]
    if search:
        search_lower = search.casefold()
        rows = [row for row in rows if search_lower in row["display_name"].casefold()]

    player_ids = [row["player"].pk for row in rows if row["player"] is not None]
    defense_team_ids = [row["team"].pk for row in rows if row["position"] == "DST"]

    week_source_rows = list(PlayerMarketProjection.objects.filter(
        season=season,
        week=week,
    ).filter(
        player_id__in=player_ids
    ) | PlayerMarketProjection.objects.filter(
        season=season,
        week=week,
        team_id__in=defense_team_ids,
    )) if rows else []
    sleeper_by_entity_week = {
        (f"player:{source.player_id}" if source.player_id else f"team:{source.team_id}", source.week): source
        for source in week_source_rows
    }
    for row in rows:
        source = sleeper_by_entity_week.get((row["entity_key"], week))
        row["weekly_sleeper"] = _score_sleeper_projection(source, league)

    adp_by_player = dict(PlayerADP.objects.filter(
        season=season,
        scoring_format=adp_format,
        player_id__in=player_ids,
    ).values_list("player_id", "adp")) if player_ids else {}
    for row in rows:
        if row["player"] is not None and row["player"].pk in adp_by_player:
            row["adp"] = float(adp_by_player[row["player"].pk])

    if rows:
        our_player_projections = list(FantasyProjection.objects.filter(
            player_id__in=player_ids,
            season=season,
            week=week,
            model_version="v2_stat",
        ).select_related("player")) if player_ids else []
        our_defense_projections = list(DefenseProjection.objects.filter(
            team_id__in=defense_team_ids,
            season=season,
            week=week,
            model_version="v2_stat",
        ).select_related("team")) if defense_team_ids else []
        for projection in our_player_projections:
            points = _score_our_player_projection(projection, league)
            row = rows_by_entity.get(f"player:{projection.player_id}")
            if row is not None:
                row["weekly_our"] = points
        for projection in our_defense_projections:
            points = _score_our_defense_projection(projection, league)
            row = rows_by_entity.get(f"team:{projection.team_id}")
            if row is not None:
                row["weekly_our"] = points

        market_season_rows = list(PlayerMarketProjection.objects.filter(
            season=season,
            week__gte=week,
            week__lte=18,
        ).filter(
            player_id__in=player_ids
        ) | PlayerMarketProjection.objects.filter(
            season=season,
            week__gte=week,
            week__lte=18,
            team_id__in=defense_team_ids,
        ))
        market_by_entity = {}
        for source in market_season_rows:
            entity_key = f"player:{source.player_id}" if source.player_id else f"team:{source.team_id}"
            market_by_entity.setdefault(entity_key, {})[source.week] = source

        needed_weeks = set(range(week, 19))
        has_ros_data = False
        for row in rows:
            weekly_sources = market_by_entity.get(row["entity_key"], {})
            if needed_weeks.issubset(weekly_sources):
                row["sleeper_ros"] = round(sum(
                    _score_sleeper_projection(weekly_sources[target_week], league)
                    or 0.0
                    for target_week in range(week, 19)
                ), 2)
                has_ros_data = True

        our_player_ros = list(FantasyProjection.objects.filter(
            player_id__in=player_ids,
            season=season,
            week__gte=week,
            week__lte=18,
            model_version="v2_stat",
        ).select_related("player")) if player_ids else []
        our_defense_ros = list(DefenseProjection.objects.filter(
            team_id__in=defense_team_ids,
            season=season,
            week__gte=week,
            week__lte=18,
            model_version="v2_stat",
        ).select_related("team")) if defense_team_ids else []
        our_by_entity = {}
        for projection in our_player_ros:
            entity_key = f"player:{projection.player_id}"
            our_by_entity.setdefault(entity_key, {})[projection.week] = _score_our_player_projection(
                projection, league
            )
        for projection in our_defense_ros:
            entity_key = f"team:{projection.team_id}"
            our_by_entity.setdefault(entity_key, {})[projection.week] = _score_our_defense_projection(
                projection, league
            )
        for row in rows:
            week_points = our_by_entity.get(row["entity_key"], {})
            if needed_weeks.issubset(week_points) and all(
                week_points[target_week] is not None for target_week in range(week, 19)
            ):
                row["our_ros"] = round(sum(
                    week_points[target_week] for target_week in range(week, 19)
                ), 2)
        context["has_week_data"] = bool(week_source_rows or our_player_projections or our_defense_projections)
        context["has_ros_data"] = has_ros_data or any(row["our_ros"] is not None for row in rows)
    else:
        context["has_week_data"] = False
        context["has_ros_data"] = False

    rank_columns = {
        "weekly_our": "weekly_our_rank",
        "weekly_sleeper": "weekly_sleeper_rank",
        "adp": "adp_rank",
        "our_ros": "our_ros_rank",
        "sleeper_ros": "sleeper_ros_rank",
    }
    for value_key, rank_key in rank_columns.items():
        ranked = [row for row in rows if row[value_key] is not None]
        ranked.sort(
            key=lambda row: (
                row[value_key] if value_key == "adp" else -row[value_key],
                row["display_name"].casefold(),
                row["entity_key"],
            )
        )
        position_ranks = defaultdict(int)
        for rank, row in enumerate(ranked, start=1):
            row[rank_key] = rank
            position_ranks[row["position"]] += 1
            row[f"{value_key}_position_rank"] = position_ranks[row["position"]]

    for row in rows:
        row["market_signal"] = _market_recommendation(
            row.get("our_ros_position_rank"),
            row.get("sleeper_ros_position_rank"),
        )

    if signal_filter:
        rows = [row for row in rows if row["market_signal"] == signal_filter]

    sort_keys = (
        ("our_weekly", "weekly_our"),
        ("sleeper_weekly", "weekly_sleeper"),
        ("adp", "adp"),
        ("our_ros", "our_ros"),
        ("sleeper_ros", "sleeper_ros"),
    )
    valid_sorts = {name: field for name, field in sort_keys}
    default_sort = "our_weekly" if request.resolver_match.url_name == "market_short_term" else "our_ros"
    sort = request.GET.get("sort", default_sort)
    if sort not in valid_sorts:
        sort = default_sort
    direction = request.GET.get("direction", DEFAULT_SORTS[sort])
    if direction not in {"asc", "desc"}:
        direction = DEFAULT_SORTS[sort]
    sort_field = valid_sorts[sort]
    rows.sort(
        key=lambda row: (
            row[sort_field] is None,
            row[sort_field] if direction == "asc" else -(row[sort_field] or 0),
            row["display_name"].casefold(),
            row["entity_key"],
        )
    )

    query_without_page = request.GET.copy()
    query_without_page.pop("page", None)
    page_query = query_without_page.urlencode()
    sort_urls = {}
    for key, _field in sort_keys:
        params = query_without_page.copy()
        if params.get("sort") == key:
            next_direction = "asc" if params.get("direction", DEFAULT_SORTS[key]) == "desc" else "desc"
        else:
            next_direction = DEFAULT_SORTS[key]
        params["sort"] = key
        params["direction"] = next_direction
        sort_urls[key] = "?" + params.urlencode()

    page_obj = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    page_range = page_obj.paginator.get_elided_page_range(
        page_obj.number, on_each_side=1, on_ends=1,
    )
    tab_params = request.GET.copy()
    tab_params.pop("page", None)
    short_params = tab_params.copy()
    short_params.pop("signal", None)
    short_query = short_params.urlencode()
    long_query = tab_params.urlencode()
    short_url = reverse("market_short_term") + (f"?{short_query}" if short_query else "")
    long_url = reverse("market_long_term") + (f"?{long_query}" if long_query else "")

    context.update({
        "market_rows": page_obj.object_list,
        "page_obj": page_obj,
        "page_range": page_range,
        "page_query": page_query,
        "sort_urls": sort_urls,
        "sort": sort,
        "direction": direction,
        "short_term_url": short_url,
        "long_term_url": long_url,
        "active_market_tab": "short" if request.resolver_match.url_name == "market_short_term" else "long",
    })
    return context


@login_required
def market_short_term(request):
    context = _filtered_rows(request)
    return render(request, "market/short_term.html", context)


@login_required
def market_long_term(request):
    context = _filtered_rows(request)
    return render(request, "market/long_term.html", context)
