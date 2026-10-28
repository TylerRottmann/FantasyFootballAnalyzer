"""Build trade values from saved, league-scored weekly projections."""
from collections import defaultdict
from heapq import nlargest
from itertools import combinations

from analyzer.models import NFLGame, Teams
from leagues.models import (
    DefenseProjection,
    FantasyProjection,
    FantasyRoster,
    FantasyRosterPlayer,
    UserLeagueConnection,
)
from leagues.services.kicker_scoring import league_projection
from leagues.services.power_rankings import REGULAR_SEASON_WEEKS
from scripts.commands.lineup import get_projection


TRADE_PACKAGE_SIZES = (1, 2, 3)
# Search every roster player, but run the expensive weekly lineup optimizer on
# only the strongest marginal-value package for each possible player received.
EXACT_PACKAGES_PER_TARGET = 6
EXACT_TARGETS_FIRST_PASS = 12
EXACT_CANDIDATE_FALLBACK_LIMIT = 100
PACKAGE_SHORTLIST_LIMIT = 60


def build_trade_universe(league, user, current_week):
    """Load all league rosters and saved projections once for a trade request."""
    connection = UserLeagueConnection.objects.filter(
        user=user, league=league,
    ).only("external_user_id", "platform").first()
    if connection is None:
        raise ValueError("You are not connected to this league.")

    rosters = list(
        FantasyRoster.objects.filter(league=league)
        .prefetch_related(
            "roster_players__player",
            "roster_players__team",
        )
        .order_by("sleeper_roster_id")
    )
    if not rosters:
        raise ValueError("No team rosters are available for this league.")

    roster_assets = {
        roster.id: list(roster.roster_players.all())
        for roster in rosters
    }
    player_ids = {
        entry.player_id
        for assets in roster_assets.values()
        for entry in assets
        if entry.player_id
    }
    defense_team_ids = {
        entry.team_id
        for assets in roster_assets.values()
        for entry in assets
        if entry.player_id is None and entry.team_id
    }
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
    projection_map = {
        (row.player_id, row.week): league_projection(row, league)
        for row in projections
    }
    defense_map = {
        (row.team_id, row.week): row
        for row in defense_projections
    }
    weeks = sorted({row.week for row in projections + defense_projections})
    if not weeks:
        raise ValueError("No rest-of-season projections are available for this league.")

    starting_positions = [
        "DEF" if str(slot).upper() == "D/ST" else str(slot).upper()
        for slot in (league.roster_positions or [])
        if str(slot).upper() not in {"BN", "IR", "TAXI"}
    ]
    if not starting_positions:
        raise ValueError("This league has no configured starting lineup slots.")
    eligible_positions = {
        slot for slot in starting_positions
        if slot not in {"FLEX", "SUPER_FLEX"}
    }
    if "FLEX" in starting_positions:
        eligible_positions.update(("RB", "WR", "TE"))
    if "SUPER_FLEX" in starting_positions:
        eligible_positions.update(("QB", "RB", "WR", "TE"))

    nfl_teams = Teams.objects.in_bulk({
        entry.player.team_id
        for assets in roster_assets.values()
        for entry in assets
        if entry.player_id and entry.player.team_id
    } | defense_team_ids)
    bye_by_team = _build_bye_map(league.season)

    states = {}
    for roster in rosters:
        assets = []
        for entry in roster_assets[roster.id]:
            if entry.player_id:
                player = entry.player
                team = nfl_teams.get(player.team_id)
                position = (player.position or "").upper()
                label = player.full_name
                bye_week = bye_by_team.get(player.team_id)
                headshot_url = player.headshot_url or ""
                age = player.age
            else:
                player = None
                team = entry.team or nfl_teams.get(entry.team_id)
                position = "DEF"
                label = f"{team.name} D/ST" if team else "D/ST"
                bye_week = bye_by_team.get(entry.team_id)
                headshot_url = ""
                age = None

            item = {
                "roster_player": entry,
                "player": player,
                "team": team,
                "position": position,
                "label": label,
                "age": age,
                "bye_week": bye_week,
                "headshot_url": headshot_url,
                "projections": {},
                "rest_of_season_points": 0.0,
                "starting_points": 0.0,
                "starts": 0,
            }
            for week in weeks:
                prediction = (
                    projection_map.get((entry.player_id, week))
                    if entry.player_id else defense_map.get((entry.team_id, week))
                )
                item["projections"][week] = prediction
                if prediction is not None:
                    points = get_projection({"prediction": prediction})
                    item["rest_of_season_points"] += points
            assets.append(item)

        states[roster.id] = {
            "roster": roster,
            "assets": assets,
            "baseline_by_week": {},
            "baseline_total": 0.0,
            "baseline_position_starts": defaultdict(int),
            "baseline_position_points": defaultdict(float),
            "eligible_positions": eligible_positions,
        }

    # Baseline optimized lineups give each asset a real starting contribution,
    # and provide the before-trade score used by both features.
    for state in states.values():
        for week in weeks:
            total, started_assets = _optimized_roster_lineup(
                state["assets"], week, starting_positions,
            )
            state["baseline_by_week"][week] = total
            state["baseline_total"] += total
            for asset in started_assets:
                prediction = asset["projections"].get(week)
                if prediction is None:
                    continue
                asset["starting_points"] += get_projection({"prediction": prediction})
                asset["starts"] += 1
                state["baseline_position_starts"][asset["position"]] += 1
                state["baseline_position_points"][asset["position"]] += get_projection({"prediction": prediction})
        state["position_extremes"] = _position_extremes(state)

    user_roster = next((
        state for state in states.values()
        if connection.external_user_id
        and str(state["roster"].owner_sleeper_id) == str(connection.external_user_id)
    ), None)
    if user_roster is None:
        user_roster = next((
            state for state in states.values()
            if state["roster"].owner_name
            and state["roster"].owner_name.casefold() == user.get_username().casefold()
        ), None)
    if user_roster is None:
        raise ValueError("Your fantasy team could not be matched to a roster in this league.")

    return {
        "league": league,
        "user_roster": user_roster,
        "states": states,
        "weeks": weeks,
        "starting_positions": starting_positions,
        "connection": connection,
        "evaluation_cache": {},
        "weekly_evaluation_cache": {},
    }


def generate_best_trades(universe, filters=None, limit=5):
    """Return mutually beneficial 1-for-1, 2-for-1, and 3-for-1 trades."""
    filters = filters or {}
    mine = universe["user_roster"]
    other_states = [
        state for roster_id, state in universe["states"].items()
        if roster_id != mine["roster"].id
    ]
    if not other_states:
        return []

    give_pool = list(mine["assets"])
    receive_by_roster = {
        state["roster"].id: [
            asset for asset in state["assets"]
            if _matches_receive_filters(asset, filters)
        ]
        for state in other_states
    }
    give_required = set(filters.get("give_player_ids", []))
    receive_required = set(filters.get("receive_player_ids", []))
    give_count = filters.get("give_count", 1)
    receive_count = filters.get("receive_count", 1)
    give_sizes = (give_count,) if give_count else TRADE_PACKAGE_SIZES
    receive_sizes = (receive_count,) if receive_count else TRADE_PACKAGE_SIZES
    give_packages = [
        package
        for size in give_sizes
        for package in combinations(give_pool, size)
        if _package_matches_filters(package, filters, "give", give_required)
    ]
    receive_packages_by_roster = {
        state["roster"].id: [
            package
            for size in receive_sizes
            for package in combinations(receive_by_roster[state["roster"].id], size)
            if _package_matches_filters(package, filters, "receive", receive_required)
        ]
        for state in other_states
    }
    if not give_packages or not any(receive_packages_by_roster.values()):
        return []

    # Calculate each player's single-player lineup impact once. Package values
    # can then be screened cheaply before exact lineup scoring.
    marginal_add, marginal_remove = _build_marginal_estimates(
        mine, give_pool, receive_by_roster,
    )
    estimated_candidates = []
    mine_id = mine["roster"].id
    # Bound the expensive pair search after scoring each legal package by its
    # approximate lineup impact. Every eligible asset is considered here.
    give_packages = nlargest(
        PACKAGE_SHORTLIST_LIMIT, give_packages,
        key=lambda package: sum(
            marginal_add.get((next(iter(receive_by_roster)), asset["roster_player"].id), 0.0)
            - marginal_remove.get((mine_id, asset["roster_player"].id), 0.0)
            for asset in package
        ),
    )
    for other in other_states:
        receive_packages = receive_packages_by_roster[other["roster"].id]
        receive_packages = nlargest(
            PACKAGE_SHORTLIST_LIMIT, receive_packages,
            key=lambda package: sum(
                marginal_add.get((mine_id, asset["roster_player"].id), 0.0)
                - marginal_remove.get((other["roster"].id, asset["roster_player"].id), 0.0)
                for asset in package
            ),
        )
        for receive_package in receive_packages:
            package_estimates = []
            for give_package in give_packages:
                give_ids = [asset["roster_player"].id for asset in give_package]
                receive_ids = [asset["roster_player"].id for asset in receive_package]
                you_gain = (
                    sum(marginal_add.get((mine_id, asset_id), 0.0) for asset_id in receive_ids)
                    - sum(marginal_remove.get((mine["roster"].id, asset_id), 0.0) for asset_id in give_ids)
                )
                other_gain = (
                    sum(marginal_add.get((other["roster"].id, asset_id), 0.0) for asset_id in give_ids)
                    - sum(marginal_remove.get((other["roster"].id, asset_id), 0.0) for asset_id in receive_ids)
                )
                position_balance_score, _ = _position_balance_fit(
                    mine, other, give_package, receive_package,
                )
                estimate_key = (
                    position_balance_score,
                    min(you_gain, other_gain),
                    you_gain + other_gain,
                    -len(give_package),
                )
                package_estimates.append((estimate_key, give_package))

            for estimate_key, give_package in nlargest(
                EXACT_PACKAGES_PER_TARGET,
                package_estimates,
                key=lambda row: row[0],
            ):
                estimated_candidates.append((
                    estimate_key,
                    other,
                    give_package,
                    receive_package,
                ))

    # Marginal values score every roster target and package cheaply. Run the
    # exact multiweek optimizer first on the best distinct targets, then expand
    # the exact shortlist only if needed to produce five valid suggestions.
    estimated_candidates.sort(key=lambda row: row[0], reverse=True)
    exact_first_pass = []
    first_pass_receive_ids = set()
    for row in estimated_candidates:
        receive_ids = tuple(sorted(asset["roster_player"].id for asset in row[3]))
        if receive_ids in first_pass_receive_ids:
            continue
        first_pass_receive_ids.add(receive_ids)
        exact_first_pass.append(row)
        if len(exact_first_pass) >= EXACT_TARGETS_FIRST_PASS:
            break

    results = []
    seen_candidates = set()
    seen_by_roster = defaultdict(set)

    def score_estimate(row):
        _, other, give_package, receive_package = row
        identity = (
            other["roster"].id,
            tuple(sorted(asset["roster_player"].id for asset in give_package)),
            tuple(sorted(asset["roster_player"].id for asset in receive_package)),
        )
        if identity in seen_candidates:
            return
        seen_candidates.add(identity)
        _score_candidate(
            universe,
            mine,
            other,
            give_package,
            receive_package,
            results,
            seen_by_roster[other["roster"].id],
            filters,
        )

    for row in exact_first_pass:
        score_estimate(row)

    exact_count = len(exact_first_pass)
    for row in estimated_candidates:
        distinct_receivers = {
            tuple(sorted(asset["roster_player_id"] for asset in candidate["you_get"]))
            for candidate in results
            for asset in candidate["you_get"]
        }
        if len(distinct_receivers) >= limit or exact_count >= EXACT_CANDIDATE_FALLBACK_LIMIT:
            break
        identity = (
            row[1]["roster"].id,
            tuple(sorted(asset["roster_player"].id for asset in row[2])),
            tuple(sorted(asset["roster_player"].id for asset in row[3])),
        )
        if identity in seen_candidates:
            continue
        score_estimate(row)
        exact_count += 1

    results.sort(
        key=lambda row: (
            row["you_gain"],
            row["position_balance_score"],
            row["priority_position_gain"],
            row["other_gain"],
        ),
        reverse=True,
    )

    # Keep the top suggestions diverse: a player offered to the user can only
    # appear in one suggestion, even if several different packages are built
    # around that same target.
    selected = []
    used_receive_ids = set()
    for row in results:
        receive_ids = {
            asset["roster_player_id"]
            for asset in row["you_get"]
        }
        if receive_ids & used_receive_ids:
            continue
        selected.append(row)
        used_receive_ids.update(receive_ids)
        if len(selected) >= limit:
            break
    return selected


def evaluate_trade(universe, team1, team1_outgoing_ids, team2, team2_outgoing_ids):
    """Calculate each team's optimized starter points before and after a trade."""
    team1_outgoing = _resolve_assets(team1, team1_outgoing_ids)
    team2_outgoing = _resolve_assets(team2, team2_outgoing_ids)
    team1_ids = {asset["roster_player"].id for asset in team1_outgoing}
    team2_ids = {asset["roster_player"].id for asset in team2_outgoing}
    if team1_ids & team2_ids:
        raise ValueError("A player cannot be included on both sides of the trade.")
    if not team1_outgoing or not team2_outgoing:
        raise ValueError("Add at least one player to each side of the trade.")

    before1 = team1["baseline_total"]
    before2 = team2["baseline_total"]
    after1 = _evaluate_roster(universe, team1, team1_ids, team2_outgoing)
    after2 = _evaluate_roster(universe, team2, team2_ids, team1_outgoing)
    gain1 = after1 - before1
    gain2 = after2 - before2

    if gain1 > 0.05 and gain2 > 0.05:
        verdict = "fair"
        label = "Fair for both teams"
    elif gain1 > 0.05 or gain2 > 0.05:
        verdict = "one_sided"
        label = "One-sided"
    elif gain1 < -0.05 and gain2 < -0.05:
        verdict = "bad_all_around"
        label = "Both teams regress"
    else:
        verdict = "neutral"
        label = "No meaningful change"

    return {
        "verdict": verdict,
        "label": label,
        "weeks_counted": len(universe["weeks"]),
        "team1": _team_result(team1, before1, after1, gain1),
        "team2": _team_result(team2, before2, after2, gain2),
    }


def serialize_asset(asset, new_team_projected_starts=None):
    """Return the display-safe player/defense fields shared by both UIs."""
    player = asset["player"]
    team = asset["team"]
    abbreviation = team.abbreviation if team else ""
    return {
        "roster_player_id": asset["roster_player"].id,
        "name": asset["label"],
        "position": asset["position"],
        "age": round(float(asset["age"]), 1) if asset["age"] is not None else None,
        "nfl_team": abbreviation,
        "nfl_team_name": team.name if team else "",
        "team_logo_url": (
            f"https://a.espncdn.com/i/teamlogos/nfl/500/{abbreviation.lower()}.png"
            if abbreviation else ""
        ),
        "headshot_url": asset["headshot_url"],
        "rest_of_season_points": round(asset["rest_of_season_points"], 1),
        "starting_points": round(asset["starting_points"], 1),
        "projected_starts": asset["starts"],
        "new_team_projected_starts": new_team_projected_starts,
        "bye_week": asset["bye_week"],
        "fantasy_team": asset["roster_player"].roster.owner_name or "Fantasy team",
    }


def _score_candidate(universe, mine, other, give_package, receive_package, results, seen, filters=None):
    filters = filters or {}
    give_ids = tuple(sorted(asset["roster_player"].id for asset in give_package))
    receive_ids = tuple(sorted(asset["roster_player"].id for asset in receive_package))
    identity = (other["roster"].id, give_ids, receive_ids)
    if identity in seen:
        return
    seen.add(identity)

    you_after = _evaluate_roster(universe, mine, set(give_ids), receive_package)
    other_after = _evaluate_roster(universe, other, set(receive_ids), give_package)
    you_gain = you_after - mine["baseline_total"]
    other_gain = other_after - other["baseline_total"]
    if you_gain <= 0.05 or other_gain <= 0.05:
        return

    give_starts_after, other_position_after, other_position_points_after = _projected_lineup_counts(
        universe, other, set(receive_ids), give_package,
        {asset["roster_player"].id for asset in give_package},
    )
    receive_starts_after, mine_position_after, mine_position_points_after = _projected_lineup_counts(
        universe, mine, set(give_ids), receive_package,
        {asset["roster_player"].id for asset in receive_package},
    )
    positions = ("QB", "RB", "WR", "TE", "K", "DEF")
    position_impact = {}
    for position in positions:
        you_before_position = mine["baseline_position_starts"].get(position, 0)
        other_before_position = other["baseline_position_starts"].get(position, 0)
        you_after_position = mine_position_after.get(position, 0)
        other_after_position = other_position_after.get(position, 0)
        position_impact[position] = {
            "you_before": you_before_position,
            "you_after": you_after_position,
            "you_delta": you_after_position - you_before_position,
            "you_points_before": round(mine["baseline_position_points"].get(position, 0.0), 1),
            "you_points_after": round(mine_position_points_after.get(position, 0.0), 1),
            "other_before": other_before_position,
            "other_after": other_after_position,
            "other_delta": other_after_position - other_before_position,
            "other_points_before": round(other["baseline_position_points"].get(position, 0.0), 1),
            "other_points_after": round(other_position_points_after.get(position, 0.0), 1),
        }
    priority_position = filters.get("prioritize_position")
    priority_position_gain = position_impact.get(priority_position, {}).get("you_delta", 0)
    position_balance_score, position_balance_summary = _position_balance_fit(
        mine, other, give_package, receive_package,
    )
    mine_weekly_after = _evaluate_roster_by_week(
        universe, mine, set(give_ids), receive_package,
    )
    other_weekly_after = _evaluate_roster_by_week(
        universe, other, set(receive_ids), give_package,
    )
    weekly_impact = []
    for week in universe["weeks"]:
        you_before_week = mine["baseline_by_week"].get(week, 0.0)
        other_before_week = other["baseline_by_week"].get(week, 0.0)
        you_after_week = mine_weekly_after.get(week, 0.0)
        other_after_week = other_weekly_after.get(week, 0.0)
        weekly_impact.append({
            "week": week,
            "you_before": round(you_before_week, 1),
            "you_after": round(you_after_week, 1),
            "you_delta": round(you_after_week - you_before_week, 1),
            "other_before": round(other_before_week, 1),
            "other_after": round(other_after_week, 1),
            "other_delta": round(other_after_week - other_before_week, 1),
        })

    results.append({
        "other_roster_id": other["roster"].id,
        "other_team": other["roster"].owner_name or f"Team {other['roster'].sleeper_roster_id}",
        "you_give": [serialize_asset(asset, give_starts_after.get(asset["roster_player"].id, 0)) for asset in give_package],
        "you_get": [serialize_asset(asset, receive_starts_after.get(asset["roster_player"].id, 0)) for asset in receive_package],
        "you_before": round(mine["baseline_total"], 1),
        "you_after": round(you_after, 1),
        "you_gain": round(you_gain, 1),
        "other_before": round(other["baseline_total"], 1),
        "other_after": round(other_after, 1),
        "other_gain": round(other_gain, 1),
        "mutual_gain": round(min(you_gain, other_gain), 1),
        "combined_gain": round(you_gain + other_gain, 1),
        "weeks_counted": len(universe["weeks"]),
        "weekly_impact": weekly_impact,
        "position_impact": position_impact,
        "position_balance_score": position_balance_score,
        "position_balance_summary": position_balance_summary,
        "priority_position_gain": priority_position_gain,
    })


def _projected_lineup_counts(universe, state, outgoing_ids, incoming_assets, target_ids):
    active_assets = [
        asset for asset in state["assets"]
        if asset["roster_player"].id not in outgoing_ids
    ] + list(incoming_assets)
    starts = {asset_id: 0 for asset_id in target_ids}
    position_starts = defaultdict(int)
    position_points = defaultdict(float)
    for week in universe["weeks"]:
        _, started_assets = _optimized_roster_lineup(
            active_assets, week, universe["starting_positions"],
        )
        for asset in started_assets:
            asset_id = asset["roster_player"].id
            if asset["projections"].get(week) is not None:
                if asset_id in starts:
                    starts[asset_id] += 1
                position_starts[asset["position"]] += 1
                position_points[asset["position"]] += get_projection({"prediction": asset["projections"][week]})
    return starts, position_starts, position_points


def _position_extremes(state):
    positions = sorted(state["eligible_positions"])
    if len(positions) < 2:
        return {"strongest": "", "weakest": ""}
    average_points = {
        position: (
            state["baseline_position_points"].get(position, 0.0)
            / state["baseline_position_starts"].get(position, 1)
        )
        for position in positions
    }
    strongest = max(average_points, key=average_points.get)
    weakest = min(average_points, key=average_points.get)
    if strongest == weakest:
        return {"strongest": "", "weakest": ""}
    return {"strongest": strongest, "weakest": weakest}


def _position_balance_fit(mine, other, give_package, receive_package):
    mine_extremes = mine.get("position_extremes") or _position_extremes(mine)
    other_extremes = other.get("position_extremes") or _position_extremes(other)
    given_positions = {asset["position"] for asset in give_package}
    received_positions = {asset["position"] for asset in receive_package}
    flags = (
        bool(mine_extremes["strongest"] and mine_extremes["strongest"] in given_positions),
        bool(mine_extremes["weakest"] and mine_extremes["weakest"] in received_positions),
        bool(other_extremes["strongest"] and other_extremes["strongest"] in received_positions),
        bool(other_extremes["weakest"] and other_extremes["weakest"] in given_positions),
    )
    score = sum(flags)
    other_name = other["roster"].owner_name or "Opponent"
    labels = {"DEF": "D/ST"}
    label = lambda position: labels.get(position, position)
    summary_parts = []
    if flags[0]:
        summary_parts.append(f"You give {label(mine_extremes['strongest'])} strength")
    if flags[1]:
        summary_parts.append(f"You add {label(mine_extremes['weakest'])} need")
    if flags[2]:
        summary_parts.append(f"{other_name} gives {label(other_extremes['strongest'])} strength")
    if flags[3]:
        summary_parts.append(f"{other_name} adds {label(other_extremes['weakest'])} need")
    summary = " · ".join(summary_parts)
    return score, summary


def _evaluate_roster(universe, state, outgoing_ids, incoming_assets):
    incoming_ids = tuple(sorted(asset["roster_player"].id for asset in incoming_assets))
    key = (state["roster"].id, tuple(sorted(outgoing_ids)), incoming_ids)
    cache = universe["evaluation_cache"]
    if key in cache:
        return cache[key]

    total = sum(_evaluate_roster_by_week(universe, state, outgoing_ids, incoming_assets).values())
    cache[key] = total
    return total


def _evaluate_roster_by_week(universe, state, outgoing_ids, incoming_assets):
    incoming_ids = tuple(sorted(asset["roster_player"].id for asset in incoming_assets))
    key = (state["roster"].id, tuple(sorted(outgoing_ids)), incoming_ids)
    cache = universe["weekly_evaluation_cache"]
    if key in cache:
        return cache[key]

    active_assets = [
        asset for asset in state["assets"]
        if asset["roster_player"].id not in outgoing_ids
    ] + list(incoming_assets)
    weekly_scores = {}
    for week in universe["weeks"]:
        weekly_scores[week] = _optimized_roster_total(
            active_assets, week, universe["starting_positions"],
        )
    cache[key] = weekly_scores
    return weekly_scores


def _lineup_item(asset, week):
    return {
        "player": asset["player"],
        "roster_player": asset["roster_player"],
        "prediction": asset["projections"].get(week),
        "team": asset["team"] if asset["player"] is None else None,
        "is_defense": asset["player"] is None,
    }


def _optimized_roster_total(assets, week, starting_positions):
    return _optimized_roster_lineup(assets, week, starting_positions)[0]


def _optimized_roster_lineup(assets, week, starting_positions):
    """Score a lineup using small FLEX allocation combinations.

    Players have one primary position. Enumerating how the FLEX and SUPER_FLEX
    slots are distributed across positions avoids a large player-to-slot DP.
    """
    items = [_lineup_item(asset, week) for asset in assets]
    fixed_counts = defaultdict(int)
    flex_count = 0
    super_flex_count = 0
    for slot in starting_positions:
        if slot == "FLEX":
            flex_count += 1
        elif slot == "SUPER_FLEX":
            super_flex_count += 1
        else:
            fixed_counts[slot] += 1

    fixed_candidates = defaultdict(list)
    for item in items:
        position = "DEF" if item["player"] is None else (item["player"].position or "").upper()
        fixed_candidates[position].append((
            item["roster_player"].id,
            get_projection(item),
        ))
    for candidates in fixed_candidates.values():
        candidates.sort(key=lambda row: row[1], reverse=True)

    def allocations(positions, slots_count):
        rows = []

        def build(index, remaining, values):
            if index == len(positions):
                rows.append(tuple(values))
                return
            for count in range(remaining + 1):
                build(index + 1, remaining - count, values + [count])

        build(0, slots_count, [])
        return rows

    flex_positions = ("RB", "WR", "TE")
    super_flex_positions = ("QB", "RB", "WR", "TE")
    flex_allocations = allocations(flex_positions, flex_count)
    super_flex_allocations = allocations(super_flex_positions, super_flex_count)
    best = (0, 0.0)
    best_ids = set()
    positions = set(fixed_counts) | set(fixed_candidates) | set(flex_positions) | set(super_flex_positions)
    for flex_allocation in flex_allocations:
        flex_by_position = dict(zip(flex_positions, flex_allocation))
        for super_allocation in super_flex_allocations:
            super_by_position = dict(zip(super_flex_positions, super_allocation))
            selected_ids = set()
            filled = 0
            points = 0.0
            for position in positions:
                capacity = (
                    fixed_counts.get(position, 0)
                    + flex_by_position.get(position, 0)
                    + super_by_position.get(position, 0)
                )
                if capacity <= 0:
                    continue
                selected = fixed_candidates.get(position, ())[:capacity]
                selected_ids.update(asset_id for asset_id, _ in selected)
                filled += len(selected)
                points += sum(projection for _, projection in selected)
            candidate = (filled, points)
            if candidate > best:
                best = candidate
                best_ids = selected_ids

    return best[1], [
        asset for asset in assets
        if asset["roster_player"].id in best_ids
    ]


def _packages(assets):
    return [
        package
        for size in TRADE_PACKAGE_SIZES
        for package in combinations(assets, size)
        if len(package) == size
    ]


def _build_marginal_estimates(mine, give_assets, receive_by_roster):
    """Estimate asset add/remove value cheaply before exact lineup scoring.

    A player's saved rest-of-season projection estimates the value of adding
    them; their baseline starter contribution estimates the value of removing
    them. Exact optimized lineups are still used to validate finalists.
    """
    marginal_add = {}
    marginal_remove = {}
    all_receives = [asset for assets in receive_by_roster.values() for asset in assets]
    my_roster_id = mine["roster"].id
    for asset in all_receives:
        marginal_add[(my_roster_id, asset["roster_player"].id)] = asset["rest_of_season_points"]
    for asset in give_assets:
        marginal_remove[(my_roster_id, asset["roster_player"].id)] = asset["starting_points"]

    for roster_id, receive_assets in receive_by_roster.items():
        for asset in give_assets:
            marginal_add[(roster_id, asset["roster_player"].id)] = asset["rest_of_season_points"]
        for asset in receive_assets:
            marginal_remove[(roster_id, asset["roster_player"].id)] = asset["starting_points"]
    return marginal_add, marginal_remove


def _package_matches_filters(package, filters, side, required_ids):
    asset_ids = {asset["roster_player"].id for asset in package}
    if not required_ids.issubset(asset_ids):
        return False
    positions = [
        position for position in filters.get(f"{side}_positions", [])
        if position
    ]
    if len(positions) > len(package):
        return False
    available = list(package)

    def match_position(index):
        if index == len(positions):
            return True
        for asset_index, asset in enumerate(available):
            if asset["position"] != positions[index]:
                continue
            selected = available.pop(asset_index)
            if match_position(index + 1):
                available.insert(asset_index, selected)
                return True
            available.insert(asset_index, selected)
        return False

    return match_position(0)


def _matches_receive_filters(asset, filters):
    if filters.get("min_age") is not None:
        if asset["age"] is None or asset["age"] < filters["min_age"]:
            return False
    if filters.get("max_age") is not None:
        if asset["age"] is None or asset["age"] > filters["max_age"]:
            return False
    if filters.get("exclude_nfl_teams") and asset["team"]:
        if asset["team"].abbreviation.upper() in filters["exclude_nfl_teams"]:
            return False
    elif filters.get("exclude_nfl_teams") and asset["team"] is None:
        return False
    if filters.get("acceptable_bye_weeks"):
        if asset["bye_week"] not in filters["acceptable_bye_weeks"]:
            return False
    return True


def _resolve_assets(state, ids):
    id_set = {int(asset_id) for asset_id in ids}
    if len(id_set) != len(ids):
        raise ValueError("A player can only be added once to a trade side.")
    assets_by_id = {asset["roster_player"].id: asset for asset in state["assets"]}
    missing = id_set - set(assets_by_id)
    if missing:
        raise ValueError("One or more selected players do not belong to that fantasy team.")
    return [assets_by_id[asset_id] for asset_id in id_set]


def _team_result(state, before, after, gain):
    return {
        "roster_id": state["roster"].id,
        "name": state["roster"].owner_name or f"Team {state['roster'].sleeper_roster_id}",
        "before": round(before, 1),
        "after": round(after, 1),
        "gain": round(gain, 1),
    }


def _build_bye_map(season):
    scheduled_weeks = defaultdict(set)
    games = NFLGame.objects.filter(
        season=season, game_type="REG",
    ).values_list("home_team_id", "away_team_id", "week")
    for home_id, away_id, week in games:
        if 1 <= week <= 18:
            scheduled_weeks[home_id].add(week)
            scheduled_weeks[away_id].add(week)
    return {
        team_id: next((week for week in range(1, 19) if week not in weeks), None)
        for team_id, weeks in scheduled_weeks.items()
        if len(weeks) == 17
    }
