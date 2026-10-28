import logging
import re
from dataclasses import dataclass
from typing import Any

from django.db.models import Q

from .models import NFLGame, Players, PlayerWeeklyStats, Teams

logger = logging.getLogger(__name__)

POSITION_WORDS = {
    "quarterback": "QB", "quarterbacks": "QB", "qb": "QB", "qbs": "QB",
    "running back": "RB", "running backs": "RB", "rb": "RB", "rbs": "RB",
    "wide receiver": "WR", "wide receivers": "WR", "wr": "WR", "wrs": "WR",
    "tight end": "TE", "tight ends": "TE", "te": "TE", "tes": "TE",
    "kicker": "K", "kickers": "K", "k": "K",
    "defense": "DST", "defenses": "DST", "dst": "DST", "d/st": "DST",
}
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
MODEL_VERSION = "v1"


def _find_players_in_question(question, limit=2):
    """Find player names that are explicitly present in the user's question."""
    cleaned = question.lower()
    # Longest names first avoids matching a short name inside a full name.
    candidates = (
        Players.objects.exclude(full_name__isnull=True)
        .exclude(full_name="")
        .filter(position__in=("QB", "RB", "WR", "TE", "K"))
        .only("id", "full_name", "position", "team_id", "injury_status", "status")
        .order_by("full_name")
    )
    found = []
    for player in candidates.iterator():
        name = (player.full_name or "").strip()
        if len(name) < 3:
            continue
        if re.search(r"(?<![a-z])" + re.escape(name.lower()) + r"(?![a-z])", cleaned):
            found.append(player)
    found.sort(key=lambda p: len(p.full_name or ""), reverse=True)
    unique = []
    seen_ids = set()
    for player in found:
        if player.id not in seen_ids:
            unique.append(player)
            seen_ids.add(player.id)
    return unique[:limit]


def _recent_stats(player, count=4):
    rows = list(
        PlayerWeeklyStats.objects.filter(player_id=player.id, season_type__iexact="REG")
        .exclude(fantasy_points_ppr__isnull=True)
        .order_by("-season", "-week")
        .values("season", "week", "fantasy_points_ppr", "fantasy_points")[:count]
    )
    return rows


def _fmt(value):
    if value is None:
        return "N/A"
    return f"{float(value):.1f}"


def _player_summary(player):
    rows = _recent_stats(player)
    position = player.position or "position unknown"
    status = (player.injury_status or player.status or "").strip()
    result = [f"{player.full_name} ({position})"]
    if status:
        result.append(f"Listed status: {status}.")
    if not rows:
        result.append("I couldn't find recent regular-season fantasy-point records for this player in the database.")
        return " ".join(result)
    points = [r["fantasy_points_ppr"] for r in rows if r["fantasy_points_ppr"] is not None]
    avg = sum(float(x) for x in points) / len(points) if points else None
    result.append(
        f"Average PPR points across the {len(points)} most recent recorded game(s): {_fmt(avg)}."
    )
    result.append(
        "Recent weekly PPR points: " +
        ", ".join(f"Week {r['week']} ({r['season']}): {_fmt(r['fantasy_points_ppr'])}" for r in rows) + "."
    )
    result.append("This is historical performance, not a projection for the upcoming week.")
    return " ".join(result)


def _compare_players(players):
    a, b = players[0], players[1]
    a_rows, b_rows = _recent_stats(a), _recent_stats(b)
    a_vals = [float(r["fantasy_points_ppr"]) for r in a_rows if r["fantasy_points_ppr"] is not None]
    b_vals = [float(r["fantasy_points_ppr"]) for r in b_rows if r["fantasy_points_ppr"] is not None]
    if not a_vals or not b_vals:
        return (
            f"I found {a.full_name} and {b.full_name}, but I don't have enough recent PPR game data "
            "for both players to compare them. Try asking about each player individually."
        )
    a_avg, b_avg = sum(a_vals) / len(a_vals), sum(b_vals) / len(b_vals)
    gap = abs(a_avg - b_avg)
    if gap < 1.0:
        lean = "They are very close based on recent PPR scoring, so I'd treat this as a toss-up."
    elif a_avg > b_avg:
        lean = f"Recent scoring leans toward {a.full_name} by about {gap:.1f} PPR points per game."
    else:
        lean = f"Recent scoring leans toward {b.full_name} by about {gap:.1f} PPR points per game."
    return (
        f"Here's the recent-data comparison (PPR):\n"
        f"• {a.full_name}: {a_avg:.1f} average over {len(a_vals)} recorded game(s).\n"
        f"• {b.full_name}: {b_avg:.1f} average over {len(b_vals)} recorded game(s).\n"
        f"{lean}\n"
        "Important: this is a simple historical comparison, not a full start/sit projection. "
        "It doesn't yet account for opponent matchup, snap share, weather, or your league's scoring settings."
    )


def _position_leaders(question):
    match = re.search(r"\b(qb|rb|wr|te|k|dst|defense|tight end|wide receiver|running back|quarterback)\b", question, re.I)
    if not match:
        return None
    token = match.group(1).lower()
    mapping = {
        "quarterback": "QB", "qb": "QB",
        "running back": "RB", "rb": "RB",
        "wide receiver": "WR", "wr": "WR",
        "tight end": "TE", "te": "TE",
        "k": "K", "dst": "DST", "defense": "DST",
    }
    position = mapping[token]
    player_ids = (
        PlayerWeeklyStats.objects.filter(season_type__iexact="REG")
        .exclude(fantasy_points_ppr__isnull=True)
        .order_by("-season", "-week")
        .values_list("player_id", flat=True)
        .distinct()
    )
    # Avoid claiming these are future projections: this ranks latest recorded weekly performance.
    latest_by_player = {}
    for row in PlayerWeeklyStats.objects.filter(
        player_id__in=player_ids, season_type__iexact="REG"
    ).exclude(fantasy_points_ppr__isnull=True).order_by("-season", "-week").values(
        "player_id", "season", "week", "fantasy_points_ppr"
    ):
        latest_by_player.setdefault(row["player_id"], row)
    ids = list(latest_by_player)
    players = Players.objects.filter(id__in=ids, position__iexact=position)
    ranked = []
    for player in players:
        row = latest_by_player.get(player.id)
        if row:
            ranked.append((float(row["fantasy_points_ppr"]), player, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return f"I couldn't find enough recorded PPR stats to list {position} players."
    lines = [f"Here are players at {position} ranked by their latest recorded regular-season PPR score (not upcoming projections):"]
    for points, player, row in ranked[:5]:
        lines.append(f"• {player.full_name}: {points:.1f} PPR points (Week {row['week']}, {row['season']})")
    return "\n".join(lines)


def _answer_from_history(question):
    """Original history-only answers; used as the fallback when no projection intent matches."""
    q = question.strip()
    lower = q.lower()
    if re.search(r"\b(hello|hi|hey)\b", lower) and len(lower.split()) <= 5:
        return (
            "Hey! I'm Assistant GM, your rule-based fantasy football helper. "
            "Ask me to compare two players, check a player's recent PPR performance, "
            "or list players by position using the stats in our database."
        )

    players = _find_players_in_question(q, limit=2)
    compare_intent = bool(re.search(
        r"\b(compare|start|sit|or|versus|vs\.?|better|between)\b", lower
    ))
    if compare_intent and len(players) >= 2:
        return _compare_players(players)

    if any(word in lower for word in ["top ", "best ", "rank", "leaders", "who are the"]) and not players:
        response = _position_leaders(q)
        if response:
            return response

    if players:
        return _player_summary(players[0])

    if any(word in lower for word in ["trade", "waiver", "pick up", "pickup", "drop"]):
        return (
            "I can help with trade and waiver questions, but I need more structured logic before I can "
            "make a reliable recommendation. For now, try asking me to compare two named players or "
            "summarize a player's recent PPR performance."
        )

    return (
        "I can answer a few data-driven questions right now: compare two players, look up a player's "
        "recent PPR scoring, or list players by position based on recorded weekly stats.\n\n"
        "Try: “Compare [Player A] and [Player B]”, “How has [Player] performed recently?”, "
        "or “Who are the top WRs by their latest recorded score?”"
    )



# ---------------------------------------------------------------------------
# Projection-aware answers (uses the same tables the Start/Sit page reads)
# ---------------------------------------------------------------------------

@dataclass
class ChatContext:
    user: Any = None
    league: Any = None
    season: Any = None
    week: Any = None


def _build_context(question, user, league):
    from leagues.models import FantasyProjection

    season = getattr(league, "season", None)
    if season is None:
        season = FantasyProjection.objects.order_by("-season").values_list("season", flat=True).first()

    week_match = re.search(r"\bweek\s*(\d{1,2})\b", question, re.I)
    if week_match:
        week = max(1, min(18, int(week_match.group(1))))
    else:
        try:
            from scripts.commands.nflweek import get_current_nfl_week
            week = get_current_nfl_week()
        except Exception:
            logger.warning("Could not get current NFL week; using latest projected week", exc_info=True)
            week = (
                FantasyProjection.objects.filter(season=season)
                .order_by("-week").values_list("week", flat=True).first()
            )
    return ChatContext(user=user, league=league, season=season, week=week)


def _detect_position(question):
    lower = question.lower()
    for word in sorted(POSITION_WORDS, key=len, reverse=True):
        if re.search(r"(?<![a-z/])" + re.escape(word) + r"(?![a-z/])", lower):
            return POSITION_WORDS[word]
    return None


def _projection_for(player, ctx):
    """Return this player's projection row for ctx.season/week, or None."""
    from leagues.models import FantasyProjection
    from leagues.services.kicker_scoring import league_projection

    if ctx.season is None or ctx.week is None:
        return None
    projection = (
        FantasyProjection.objects.select_related("player")
        .filter(player_id=player.id, season=ctx.season, week=ctx.week, model_version=MODEL_VERSION)
        .first()
    )
    if projection is None:
        return None
    if ctx.league is not None:
        projection = league_projection(projection, ctx.league)
    return projection


def _points(projection):
    value = getattr(projection, "projected_fantasy_points", None) if projection else None
    return None if value is None else float(value)


def _opponent_label(team_id, ctx):
    if not team_id or ctx.season is None or ctx.week is None:
        return None
    game = (
        NFLGame.objects.filter(season=ctx.season, week=ctx.week, game_type="REG")
        .filter(Q(home_team_id=team_id) | Q(away_team_id=team_id))
        .select_related("home_team", "away_team").first()
    )
    if game is None:
        from leagues.services.schedule import confirmed_bye_team_ids
        return "BYE" if team_id in confirmed_bye_team_ids(ctx.season, ctx.week) else None
    if game.home_team_id == team_id:
        return f"vs {game.away_team.abbreviation}"
    return f"@ {game.home_team.abbreviation}"


def _scoring_note(ctx):
    ppr = getattr(ctx.league, "ppr", None)
    if ctx.league is not None and ppr is not None and float(ppr) != 1.0:
        return (" Note: projections come from the app's standard model and are not fully "
                f"re-scored for your league's {float(ppr):g}-PPR settings.")
    return ""


def _recent_avg(player):
    vals = [float(r["fantasy_points_ppr"]) for r in _recent_stats(player) if r["fantasy_points_ppr"] is not None]
    return (sum(vals) / len(vals)) if vals else None


def _projection_summary(player, ctx):
    projection = _projection_for(player, ctx)
    points = _points(projection)
    head = f"{player.full_name} ({player.position or '?'})"
    opponent = _opponent_label(player.team_id, ctx)
    if opponent == "BYE":
        return f"{head} is on a bye in Week {ctx.week}."
    parts = []
    if points is None:
        parts.append(f"I don't have a Week {ctx.week} projection for {head} yet.")
    else:
        line = f"{head} is projected for {points:.1f} fantasy points in Week {ctx.week}"
        line += f" ({opponent})." if opponent else "."
        parts.append(line)
    status = (player.injury_status or player.status or "").strip()
    if status and status.lower() not in {"active"}:
        parts.append(f"Listed status: {status}.")
    avg = _recent_avg(player)
    if avg is not None:
        parts.append(f"Recent average over the last {len(_recent_stats(player))} games: {avg:.1f} PPR.")
    return " ".join(parts) + (_scoring_note(ctx) if points is not None else "")


def _compare_with_projections(a, b, ctx):
    pa, pb = _points(_projection_for(a, ctx)), _points(_projection_for(b, ctx))
    if pa is None or pb is None:
        return None  # caller falls back to the history-only comparison
    gap = abs(pa - pb)
    if gap < 1.5:
        lean = "That's close enough that I'd call it a toss-up; use matchup and injury news to break the tie."
    else:
        winner = a if pa > pb else b
        lean = f"The model leans {winner.full_name} by {gap:.1f} points."
    lines = [f"Week {ctx.week} projections:"]
    for player, pts in ((a, pa), (b, pb)):
        opp = _opponent_label(player.team_id, ctx)
        extra = f" {opp}" if opp else ""
        status = (player.injury_status or "").strip()
        if status:
            extra += f", {status}"
        lines.append(f"• {player.full_name}: {pts:.1f}{' (' + extra.strip() + ')' if extra.strip() else ''}")
    return "\n".join(lines) + f"\n{lean}" + _scoring_note(ctx)


def _top_projected(position, ctx, exclude_rostered=False, limit=5):
    from leagues.models import FantasyProjection, FantasyRosterPlayer
    from leagues.services.kicker_scoring import league_projection

    qs = FantasyProjection.objects.select_related("player").filter(
        season=ctx.season, week=ctx.week, model_version=MODEL_VERSION, player__position=position,
    )
    if exclude_rostered and ctx.league is not None:
        rostered = FantasyRosterPlayer.objects.filter(
            roster__league_id=ctx.league.pk, player_id__isnull=False
        ).values("player_id")
        qs = qs.exclude(player_id__in=rostered)
    rows = []
    for projection in qs.order_by("-projected_fantasy_points")[:60]:
        if ctx.league is not None:
            projection = league_projection(projection, ctx.league)
        if _points(projection) is not None:
            rows.append(projection)
    rows.sort(key=lambda p: _points(p), reverse=True)
    return rows[:limit]


def _format_top(position, rows, ctx, title):
    lines = [f"{title} ({position}, Week {ctx.week}):"]
    for projection in rows:
        player = projection.player
        opp = _opponent_label(player.team_id, ctx)
        lines.append(f"• {player.full_name}: {_points(projection):.1f}" + (f" ({opp})" if opp else ""))
    return "\n".join(lines) + _scoring_note(ctx)


def _my_roster_items(ctx):
    """Build the same item dicts the Start/Sit page feeds the lineup optimizer."""
    from leagues.models import DefenseProjection, FantasyProjection, FantasyRoster, UserLeagueConnection
    from leagues.services.kicker_scoring import league_projection

    connection = UserLeagueConnection.objects.filter(user=ctx.user, league=ctx.league).first()
    if connection is None:
        return None
    roster = FantasyRoster.objects.filter(
        league=ctx.league, owner_sleeper_id=connection.external_user_id
    ).first()
    if roster is None:
        return None
    roster_players = list(roster.roster_players.select_related("player", "team"))
    projections = {
        p.player_id: league_projection(p, ctx.league)
        for p in FantasyProjection.objects.select_related("player").filter(
            player_id__in=[rp.player_id for rp in roster_players if rp.player_id],
            season=ctx.season, week=ctx.week, model_version=MODEL_VERSION,
        )
    }
    defenses = {
        p.team_id: p
        for p in DefenseProjection.objects.filter(
            team_id__in=[rp.team_id for rp in roster_players if rp.player_id is None and rp.team_id],
            season=ctx.season, week=ctx.week, model_version=MODEL_VERSION,
        )
    }
    items = []
    for rp in roster_players:
        if rp.player is None:
            items.append({"player": None, "roster_player": rp, "team": rp.team,
                          "prediction": defenses.get(rp.team_id)})
        else:
            items.append({"player": rp.player, "roster_player": rp, "team": rp.team,
                          "prediction": projections.get(rp.player_id)})
    return items


def _item_name(item):
    if item["player"] is not None:
        return item["player"].full_name
    team = item.get("team")
    return f"{team.abbreviation} D/ST" if team else "D/ST"


def _answer_my_lineup(ctx):
    from scripts.commands.lineup import build_current_lineup, build_optimized_lineup, get_lineup_total

    if ctx.league is None:
        return "Connect a league first (League > Connect) and I can look at your lineup."
    items = _my_roster_items(ctx)
    if items is None:
        return "I couldn't find your roster in the active league."
    if not any(_points(i["prediction"]) is not None for i in items):
        return f"I don't have Week {ctx.week} projections for your roster yet, so I can't recommend a lineup."

    slots = [s for s in (ctx.league.roster_positions or []) if s not in {"BN", "IR", "TAXI"}]
    current = build_current_lineup(items, slots)
    optimized, opt_total = build_optimized_lineup(items, slots)
    cur_total = get_lineup_total(current)

    swaps = []
    for cur, opt in zip(current, optimized):
        cur_item, opt_item = cur["item"], opt["item"]
        if opt_item is None or (cur_item is not None and cur_item["roster_player"].id == opt_item["roster_player"].id):
            continue
        swaps.append(
            f"• {opt['slot']}: start {_item_name(opt_item)} ({_points(opt_item['prediction']) or 0:.1f})"
            + (f" over {_item_name(cur_item)} ({_points(cur_item['prediction']) or 0:.1f})" if cur_item else "")
        )
    missing = [_item_name(i) for i in items if _points(i["prediction"]) is None]

    if not swaps:
        text = f"Your Week {ctx.week} lineup already looks optimal at {cur_total:.1f} projected points."
    else:
        text = (f"Week {ctx.week}: your lineup projects {cur_total:.1f}; the best lineup projects "
                f"{opt_total:.1f} (+{opt_total - cur_total:.1f}).\nSuggested changes:\n" + "\n".join(swaps))
    if missing:
        text += "\nNo projection available for: " + ", ".join(missing[:6]) + " (treated as 0)."
    return text + _scoring_note(ctx)


def _items_for_roster(roster, ctx):
    from leagues.models import DefenseProjection, FantasyProjection
    from leagues.services.kicker_scoring import league_projection

    rps = list(roster.roster_players.select_related("player", "team"))
    projections = {
        p.player_id: league_projection(p, ctx.league)
        for p in FantasyProjection.objects.select_related("player").filter(
            player_id__in=[rp.player_id for rp in rps if rp.player_id],
            season=ctx.season, week=ctx.week, model_version=MODEL_VERSION)
    }
    defenses = {
        p.team_id: p for p in DefenseProjection.objects.filter(
            team_id__in=[rp.team_id for rp in rps if rp.player_id is None and rp.team_id],
            season=ctx.season, week=ctx.week, model_version=MODEL_VERSION)
    }
    return [
        {"player": rp.player, "roster_player": rp, "team": rp.team,
         "prediction": defenses.get(rp.team_id) if rp.player is None else projections.get(rp.player_id)}
        for rp in rps
    ]


def _computed_team_projection(roster, ctx):
    """Best-lineup total from player projections; None if nothing is projected."""
    from scripts.commands.lineup import build_optimized_lineup

    items = _items_for_roster(roster, ctx)
    if not any(_points(i["prediction"]) is not None for i in items):
        return None
    slots = [x for x in (ctx.league.roster_positions or []) if x not in {"BN", "IR", "TAXI"}]
    return build_optimized_lineup(items, slots)[1]


def _answer_matchup(ctx):
    from leagues.models import FantasyMatchup, FantasyRoster, TeamWeekProjection, UserLeagueConnection

    if ctx.league is None:
        return "Connect a league first and I can look up your matchup."
    connection = UserLeagueConnection.objects.filter(user=ctx.user, league=ctx.league).first()
    roster = connection and FantasyRoster.objects.filter(
        league=ctx.league, owner_sleeper_id=connection.external_user_id).first()
    if roster is None:
        return "I couldn't find your roster in the active league."
    matchup = FantasyMatchup.objects.filter(
        league=ctx.league, roster=roster, season=ctx.season, week=ctx.week).select_related("opponent").first()
    if matchup is None or matchup.opponent is None:
        return f"I don't have a Week {ctx.week} matchup for your team (it may be a bye or not synced yet)."

    def team_proj(r):
        row = TeamWeekProjection.objects.filter(
            league=ctx.league, roster=r, season=ctx.season, week=ctx.week).order_by("-generated_at").first()
        return row.projected_points if row else None

    mine, theirs = team_proj(roster), team_proj(matchup.opponent)
    if mine is None:
        mine = _computed_team_projection(roster, ctx)
    if theirs is None:
        theirs = _computed_team_projection(matchup.opponent, ctx)
    opp_name = matchup.opponent.owner_name or "your opponent"
    if mine is None or theirs is None:
        return f"In Week {ctx.week} you face {opp_name}. I don't have team projections for both sides yet."
    diff = mine - theirs
    verdict = "You're favored" if diff > 0 else "You're the underdog"
    return (f"Week {ctx.week} vs {opp_name}: you're projected for {mine:.1f}, they're at {theirs:.1f}. "
            f"{verdict} by {abs(diff):.1f} points.")


def answer_question(question, user=None, league=None):
    """Answer a question using projections, the user's roster and historical stats."""
    q = question.strip()
    lower = q.lower()
    if re.search(r"\b(hello|hi|hey)\b", lower) and len(lower.split()) <= 5:
        return _answer_from_history(q)

    ctx = _build_context(q, user, league)
    position = _detect_position(q)

    if re.search(r"\b(my|our)\s+(lineup|team|roster|bench|starters)\b|\bwho\s+(should|do)\s+i\s+(start|sit)\b|\boptimi[sz]e\b", lower) \
            and not _find_players_in_question(q, limit=1):
        return _answer_my_lineup(ctx)

    if re.search(r"\b(matchup|opponent|who am i (playing|facing)|will i win|my chances)\b", lower) \
            and not _find_players_in_question(q, limit=1):
        return _answer_matchup(ctx)

    if re.search(r"\b(waiver|waivers|pick ?up|free agent|available|add)\b", lower) and position and position != "DST":
        if ctx.league is None:
            return "Connect a league first so I know which players are available."
        rows = _top_projected(position, ctx, exclude_rostered=True)
        if not rows:
            return f"I don't have Week {ctx.week} projections for available {position}s yet."
        return _format_top(position, rows, ctx, "Best available by projection")

    players = _find_players_in_question(q, limit=2)
    if len(players) >= 2 and re.search(r"\b(compare|start|sit|or|versus|vs\.?|better|between)\b", lower):
        answer = _compare_with_projections(players[0], players[1], ctx)
        return answer or _compare_players(players)

    if players:
        if re.search(r"\b(recent|recently|performed|performance|lately|last|history)\b", lower):
            return _player_summary(players[0]) + "\n" + _projection_summary(players[0], ctx).split(" Recent average")[0]
        return _projection_summary(players[0], ctx)

    if re.search(r"\b(top|best|rank|leaders|who are the)\b", lower) and position in SKILL_POSITIONS + ("K",):
        rows = _top_projected(position, ctx)
        if rows:
            return _format_top(position, rows, ctx, "Top projected")

    return _answer_from_history(q)
