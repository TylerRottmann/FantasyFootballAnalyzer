import logging
import re
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Q, Sum

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
MODEL_VERSION = "v2_stat"


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
    detail: bool = False
    connection: Any = None
    cache: dict = field(default_factory=dict)


def _build_context(question, user, league, detail=False, connection=None):
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
        if week is not None:
            if re.search(r"\bnext week\b", question, re.I):
                week = min(18, week + 1)
            elif re.search(r"\blast week\b", question, re.I):
                week = max(1, week - 1)
    return ChatContext(user=user, league=league, season=season, week=week, detail=detail, connection=connection)


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


def _opponent_info(team_id, ctx):
    """Return {"label", "abbr", "home", "bye"} for this team's game, or None if unknown."""
    if not team_id or ctx.season is None or ctx.week is None:
        return None
    game = (
        NFLGame.objects.filter(season=ctx.season, week=ctx.week, game_type="REG")
        .filter(Q(home_team_id=team_id) | Q(away_team_id=team_id))
        .select_related("home_team", "away_team").first()
    )
    if game is None:
        from leagues.services.schedule import confirmed_bye_team_ids
        if team_id in confirmed_bye_team_ids(ctx.season, ctx.week):
            return {"label": "BYE", "abbr": None, "home": None, "bye": True}
        return None
    home = game.home_team_id == team_id
    opp = game.away_team if home else game.home_team
    return {"label": f"{'vs' if home else '@'} {opp.abbreviation}",
            "abbr": opp.abbreviation, "home": home, "bye": False}


def _opponent_label(team_id, ctx):
    info = _opponent_info(team_id, ctx)
    return info["label"] if info else None


def _ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _position_defense_table(position, ctx):
    """PPR points each defense has allowed per game to a position this season (before ctx.week)."""
    key = ("pos_def", ctx.season, ctx.week, position)
    if key in ctx.cache:
        return ctx.cache[key]
    table = None
    if position in SKILL_POSITIONS and ctx.season is not None and ctx.week:
        rows = (
            PlayerWeeklyStats.objects.filter(
                season=ctx.season, season_type__iexact="REG", week__lt=ctx.week,
                player__position=position, opponent_team__isnull=False,
            ).exclude(fantasy_points_ppr__isnull=True)
            .values("opponent_team", "week").annotate(total=Sum("fantasy_points_ppr"))
        )
        per_team = {}
        for row in rows:
            per_team.setdefault(row["opponent_team"], []).append(float(row["total"]))
        averages = {t: sum(v) / len(v) for t, v in per_team.items() if len(v) >= 3}
        if len(averages) >= 8:
            ordered = sorted(averages, key=averages.get, reverse=True)  # rank 1 = most generous
            table = {
                "teams": {t: (averages[t], i + 1) for i, t in enumerate(ordered)},
                "n": len(ordered), "through": ctx.week - 1,
            }
    ctx.cache[key] = table
    return table


def _matchup_note(player, ctx):
    """How friendly this week's defense is to the player's position. None if unknown."""
    position = player.position
    info = _opponent_info(getattr(player, "team_id", None), ctx)
    if position not in SKILL_POSITIONS or not info or info["bye"]:
        return None
    table = _position_defense_table(position, ctx)
    entry = table and table["teams"].get(info["abbr"])
    if not entry:
        return None
    avg, rank = entry
    n = table["n"]
    quarter = max(1, round(n / 4))
    if rank <= quarter:
        tier, verdict = "favorable", "a favorable matchup"
    elif rank > n - quarter:
        tier, verdict = "tough", "a tough matchup"
    else:
        tier, verdict = "neutral", "a middling matchup"
    text = (f"{info['abbr']} has allowed {avg:.1f} PPR points per game to {position}s "
            f"({_ordinal(rank)}-most of {n} teams through Week {table['through']}), {verdict}.")
    return {"tier": tier, "text": text, "avg": avg, "rank": rank}


def _matchup_tag(player, ctx):
    note = _matchup_note(player, ctx)
    if not note:
        return ""
    if ctx.detail:
        return f"\n    ↳ {note['text']}"
    if note["tier"] in {"favorable", "tough"}:
        return f" - {note['tier']} matchup"
    return ""


_STAT_LABELS = [
    ("passing_yards", "pass yds", 0), ("passing_tds", "pass TD", 1),
    ("rushing_yards", "rush yds", 0), ("rushing_tds", "rush TD", 1),
    ("receptions", "rec", 1), ("receiving_yards", "rec yds", 0), ("receiving_tds", "rec TD", 1),
]


def _projected_line(projection):
    stats = getattr(projection, "projected_stats", None) or {}
    parts = []
    for key, label, decimals in _STAT_LABELS:
        value = stats.get(key)
        if isinstance(value, (int, float)) and value:
            parts.append(f"{value:.{decimals}f} {label}")
    return ", ".join(parts)


def _form_parts(player, points):
    """Return (sentence, is_notable) comparing the projection to recent form, or None."""
    avg = _recent_avg(player)
    if avg is None or points is None:
        return None
    diff = points - avg
    if diff >= 3:
        return f"The projection is {diff:.1f} above his recent average of {avg:.1f}, so the model expects a step up.", True
    if diff <= -3:
        return f"The projection is {abs(diff):.1f} below his recent average of {avg:.1f}, so the model expects a dip.", True
    return f"That's in line with his recent average of {avg:.1f} PPR.", False


def _form_note(player, points, ctx):
    parts = _form_parts(player, points)
    return parts[0] if parts else None


def _reasons(player, projection, points, ctx, limit=2, include_form=True):
    """Most important reasons first. Truncated to `limit` unless the user asked for detail."""
    candidates = []  # (priority, text); lower priority number = more important
    note = _matchup_note(player, ctx)
    if note:
        candidates.append((0 if note["tier"] in {"favorable", "tough"} else 3, note["text"]))
    if include_form:
        form = _form_parts(player, points)
        if form:
            candidates.append((1 if form[1] else 4, form[0]))
    line = _projected_line(projection)
    if line:
        candidates.append((2, f"Projected stat line: {line}."))
    candidates.sort(key=lambda c: c[0])
    texts = [text for _, text in candidates]
    if ctx.detail or limit is None:
        return texts
    if len(texts) > limit:
        ctx.cache["truncated"] = True
    return texts[:limit]


def _scoring_note(ctx):
    ppr = getattr(ctx.league, "ppr", None)
    if ctx.league is not None and ppr is not None and float(ppr) != 1.0:
        return (" Note: projections come from the app's standard model and are not fully "
                f"re-scored for your league's {float(ppr):g}-PPR settings.")
    return ""


def _recent_avg(player):
    vals = [float(r["fantasy_points_ppr"]) for r in _recent_stats(player) if r["fantasy_points_ppr"] is not None]
    return (sum(vals) / len(vals)) if vals else None


def _projection_summary(player, ctx, include_recent=True):
    projection = _projection_for(player, ctx)
    points = _points(projection)
    head = f"{player.full_name} ({player.position or '?'})"
    info = _opponent_info(player.team_id, ctx)
    if info and info["bye"]:
        return f"{head} is on a bye in Week {ctx.week}."
    opponent = info["label"] if info else None
    parts = []
    if points is None:
        parts.append(f"I don't have a Week {ctx.week} projection for {head} yet.")
        avg = _recent_avg(player)
        if avg is not None and include_recent:
            parts.append(f"Recent average over the last {len(_recent_stats(player))} games: {avg:.1f} PPR.")
    else:
        line = f"{head} is projected for {points:.1f} fantasy points in Week {ctx.week}"
        line += f" ({opponent})." if opponent else "."
        parts.append(line)
    status = (player.injury_status or player.status or "").strip()
    if status and status.lower() not in {"active"}:
        parts.append(f"Listed status: {status}.")
    text = " ".join(parts)
    if points is not None:
        text += _scoring_note(ctx)
        reasons = _reasons(player, projection, points, ctx, include_form=include_recent)
        if reasons:
            text += "\n\nWhy:\n" + "\n".join(f"• {r}" for r in reasons)
    return text


def _compare_with_projections(a, b, ctx):
    proj_a, proj_b = _projection_for(a, ctx), _projection_for(b, ctx)
    pa, pb = _points(proj_a), _points(proj_b)
    if pa is None or pb is None:
        return None  # caller falls back to the history-only comparison
    gap = abs(pa - pb)
    note_a, note_b = _matchup_note(a, ctx), _matchup_note(b, ctx)
    tier_a = note_a["tier"] if note_a else None
    tier_b = note_b["tier"] if note_b else None

    if gap < 1.5:
        lean = "It's close enough that I'd call it a toss-up."
        better = None
        if note_a and note_b and note_a["rank"] != note_b["rank"]:
            better = a if note_a["rank"] < note_b["rank"] else b
        if better is not None:
            lean += f" If you need a tiebreaker, {better.full_name} has the friendlier matchup."
    else:
        winner, loser = (a, b) if pa > pb else (b, a)
        lean = f"The model leans {winner.full_name} by {gap:.1f} points."
        w_tier, l_tier = (tier_a, tier_b) if winner is a else (tier_b, tier_a)
        if w_tier == "favorable" and l_tier != "favorable":
            lean += " The matchup adds to that edge."
        elif w_tier == "tough" and l_tier == "favorable":
            lean += f" That's despite a tougher matchup, so {winner.full_name}'s role and recent form are doing the work."

    lines = [f"Week {ctx.week} projections:"]
    for player, pts in ((a, pa), (b, pb)):
        opp = _opponent_label(player.team_id, ctx)
        extra = opp or ""
        status = (player.injury_status or "").strip()
        if status:
            extra = f"{extra}, {status}" if extra else status
        lines.append(f"• {player.full_name}: {pts:.1f}" + (f" ({extra})" if extra else ""))
    text = "\n".join(lines) + f"\n{lean}"

    detail = []
    for player, projection, pts in ((a, proj_a, pa), (b, proj_b, pb)):
        reasons = _reasons(player, projection, pts, ctx, limit=1)
        if reasons:
            detail.append(f"{player.full_name}:\n" + "\n".join(f"  • {r}" for r in reasons))
    if detail:
        text += "\n\nWhat's behind it:\n" + "\n".join(detail)
    return text + _scoring_note(ctx)


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
    for projection in qs:
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
        lines.append(f"• {player.full_name}: {_points(projection):.1f}"
                     + (f" ({opp})" if opp else "") + _matchup_tag(player, ctx))
    return "\n".join(lines) + _scoring_note(ctx)


def _my_roster_items(ctx):
    """Build the same item dicts the Start/Sit page feeds the lineup optimizer."""
    from leagues.models import DefenseProjection, FantasyProjection
    from leagues.services.roster_identity import resolve_connection_roster
    from leagues.services.kicker_scoring import league_projection, league_defense_projection

    roster = resolve_connection_roster(ctx.connection)
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
        p.team_id: league_defense_projection(p, ctx.league)
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
    for incoming, outgoing in _pair_swaps(current, optimized):
        in_pts = _points(incoming["prediction"]) or 0
        pos = incoming["player"].position if incoming["player"] is not None else "D/ST"
        info = _opponent_info(incoming["player"].team_id, ctx) if incoming["player"] is not None else None
        detail_bits = f"{pos}, {in_pts:.1f}" + (f", {info['label']}" if info and not info["bye"] else "")
        line = f"• Start {_item_name(incoming)} ({detail_bits})"
        if incoming["player"] is not None:
            note = _matchup_note(incoming["player"], ctx)
            if note and ctx.detail:
                line += f"\n    ↳ {note['text']}"
            elif note and note["tier"] == "favorable":
                line += " - favorable matchup"
        if outgoing is not None:
            line += f" over {_item_name(outgoing)} ({_points(outgoing['prediction']) or 0:.1f})"
        swaps.append(line)
    missing = [_item_name(i) for i in items if _points(i["prediction"]) is None]

    if not swaps:
        text = f"Your Week {ctx.week} lineup already looks optimal at {cur_total:.1f} projected points."
    else:
        text = (f"Week {ctx.week}: your lineup projects {cur_total:.1f}; the best lineup projects "
                f"{opt_total:.1f} (+{opt_total - cur_total:.1f}).\nSuggested changes:\n" + "\n".join(swaps))
    warnings = _lineup_warnings(current, ctx)
    if warnings:
        text += "\nHeads up:\n" + "\n".join(f"• {w}" for w in warnings)
    elif missing:
        text += "\nNo projection available for: " + ", ".join(missing[:6]) + " (treated as 0)."
    return text + _scoring_note(ctx)


def _pair_swaps(current, optimized):
    """Pair each player the optimizer wants to START with the starter he should replace.

    Compares who starts in each lineup, not which slot they fill, so reshuffling the
    same players between WR/FLEX slots is not reported as a change.
    """
    cur = {c["item"]["roster_player"].id: c["item"] for c in current if c["item"] is not None}
    opt = {o["item"]["roster_player"].id: o["item"] for o in optimized if o["item"] is not None}
    ins = sorted((i for k, i in opt.items() if k not in cur),
                 key=lambda i: _points(i["prediction"]) or 0, reverse=True)
    outs = sorted((i for k, i in cur.items() if k not in opt),
                  key=lambda i: _points(i["prediction"]) or 0)

    def position(item):
        return item["player"].position if item["player"] is not None else "DST"

    pairs = []
    for incoming in ins:
        match = next((o for o in outs if position(o) == position(incoming)), None) or (outs[0] if outs else None)
        if match is not None:
            outs.remove(match)
        pairs.append((incoming, match))
    return pairs


def _lineup_warnings(current, ctx):
    """Flag starters who are projected 0 (or have no projection) and say why if we can."""
    warnings = []
    for slot in current:
        item = slot["item"]
        if item is None or (_points(item["prediction"]) or 0) > 0:
            continue
        name = _item_name(item)
        player = item["player"]
        reason = "has no projection"
        if player is not None:
            info = _opponent_info(player.team_id, ctx)
            status = (player.injury_status or "").strip()
            if info and info["bye"]:
                reason = "is on a bye"
            elif status:
                reason = f"is listed as {status}"
        warnings.append(f"{name} is in your lineup but projects 0.0 ({reason}).")
    return warnings


def _items_for_roster(roster, ctx):
    from leagues.models import DefenseProjection, FantasyProjection
    from leagues.services.kicker_scoring import league_projection, league_defense_projection

    rps = list(roster.roster_players.select_related("player", "team"))
    projections = {
        p.player_id: league_projection(p, ctx.league)
        for p in FantasyProjection.objects.select_related("player").filter(
            player_id__in=[rp.player_id for rp in rps if rp.player_id],
            season=ctx.season, week=ctx.week, model_version=MODEL_VERSION)
    }
    defenses = {
        p.team_id: league_defense_projection(p, ctx.league) for p in DefenseProjection.objects.filter(
            team_id__in=[rp.team_id for rp in rps if rp.player_id is None and rp.team_id],
            season=ctx.season, week=ctx.week, model_version=MODEL_VERSION)
    }
    return [
        {"player": rp.player, "roster_player": rp, "team": rp.team,
         "prediction": defenses.get(rp.team_id) if rp.player is None else projections.get(rp.player_id)}
        for rp in rps
    ]


def _team_lineup_totals(roster, ctx):
    """(current_lineup_total, best_lineup_total) from player projections, or None."""
    from scripts.commands.lineup import build_current_lineup, build_optimized_lineup, get_lineup_total

    items = _items_for_roster(roster, ctx)
    if not any(_points(i["prediction"]) is not None for i in items):
        return None
    slots = [x for x in (ctx.league.roster_positions or []) if x not in {"BN", "IR", "TAXI"}]
    best = build_optimized_lineup(items, slots)[1]
    current = get_lineup_total(build_current_lineup(items, slots))
    if not current or current <= 0:  # starters not synced: fall back to the best lineup
        current = best
    return current, best


def _answer_matchup(ctx):
    from leagues.models import FantasyMatchup, TeamWeekProjection
    from leagues.services.roster_identity import resolve_connection_roster

    if ctx.league is None:
        return "Connect a league first and I can look up your matchup."
    roster = resolve_connection_roster(ctx.connection)
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
    mine_best = None
    if mine is None:
        totals = _team_lineup_totals(roster, ctx)
        if totals:
            mine, mine_best = totals
    if theirs is None:
        totals = _team_lineup_totals(matchup.opponent, ctx)
        if totals:
            theirs = totals[0]
    opp_name = matchup.opponent.owner_name or "your opponent"
    if mine is None or theirs is None:
        return f"In Week {ctx.week} you face {opp_name}. I don't have team projections for both sides yet."

    diff = mine - theirs
    verdict = "you're favored" if diff > 0 else "you're the underdog"
    text = (f"Week {ctx.week} vs {opp_name}: with your current lineup you're projected for {mine:.1f} "
            f"to their {theirs:.1f}, so {verdict} by {abs(diff):.1f}.")
    if mine_best is not None and mine_best - mine >= 0.5:
        best_diff = mine_best - theirs
        outcome = (f"that would put you ahead by {best_diff:.1f}" if best_diff > 0
                   else f"you'd still trail by {abs(best_diff):.1f}")
        text += (f"\nYour best lineup would project {mine_best:.1f} (+{mine_best - mine:.1f}) and {outcome}. "
                 "Ask “who should I start?” to see the changes.")
    return text


EXPAND_RE = re.compile(r"^\W*(why|explain|elaborate|tell me more|more detail|more info|how come|details?|go deeper)\b", re.I)
WEEK_ONLY_RE = re.compile(r"^\W*(?:and |what about |how about |what if )?(next week|this week|last week|week\s*\d{1,2})\W*$", re.I)
SINGULAR_RE = re.compile(r"\b(he|him|his|she|her)\b", re.I)
PLURAL_RE = re.compile(r"\b(they|them|their|both)\b", re.I)
ELLIPSIS_RE = re.compile(r"^\W*(and|what about|how about|ok|okay|so)\b", re.I)
WEEK_PHRASE_RE = re.compile(r"\b(next|last|this) week\b|\bweek\s*\d{1,2}\b", re.I)


def _resolve_follow_up(q, state):
    """Rewrite a follow-up into a standalone question using the saved state.

    Returns (resolved_question, detail, clarification). `clarification` is a reply
    to send instead of answering when the follow-up is ambiguous.
    """
    last = state.get("last_question")
    if not last:
        return q, False, None
    lower = q.lower()
    words = lower.split()
    names = state.get("players") or []

    if EXPAND_RE.match(q) and len(words) <= 7 and not _find_players_in_question(q, limit=1):
        return last, True, None

    week_match = WEEK_ONLY_RE.match(q)
    if week_match:
        phrase = week_match.group(1).lower()
        base = state.get("week")
        stripped = WEEK_PHRASE_RE.sub("", last).strip()
        if phrase == "this week" or base is None:
            return stripped, False, None
        if phrase == "next week":
            target = base + 1
        elif phrase == "last week":
            target = base - 1
        else:
            target = int(re.search(r"\d+", phrase).group())
        return f"{stripped} week {max(1, min(18, target))}", False, None

    has_name = bool(_find_players_in_question(q, limit=1)) if len(words) <= 12 else True
    if not has_name:
        if state.get("topic") in {"top", "waiver"} and len(words) <= 5 and _detect_position(q):
            pos = _detect_position(q)
            if pos != "DST":
                base_q = "best available {} on waivers" if state["topic"] == "waiver" else "top projected {}s"
                return base_q.format(pos), False, None
        if names and PLURAL_RE.search(q):
            return f"{q} {' and '.join(names)}", False, None
        if names and SINGULAR_RE.search(q):
            if len(names) == 1:
                return f"{q} {names[0]}", False, None
            return q, False, f"Which one do you mean, {names[0]} or {names[1]}?"
    return q, False, None


def _route(q, user, league, detail=False, connection=None):
    """Pick an answer. Returns (text, topic, players, ctx); topic drives follow-up handling."""
    lower = q.lower()
    if re.search(r"\b(hello|hi|hey)\b", lower) and len(lower.split()) <= 5:
        return _answer_from_history(q), "greeting", [], None

    ctx = _build_context(q, user, league, detail=detail, connection=connection)
    position = _detect_position(q)
    players = _find_players_in_question(q, limit=2)

    if re.search(r"\b(my|our)\s+(lineup|team|roster|bench|starters)\b|\bwho\s+(should|do)\s+i\s+(start|sit)\b|\boptimi[sz]e\b", lower) \
            and not players:
        return _answer_my_lineup(ctx), "lineup", [], ctx

    if re.search(r"\b(matchup|opponent|who am i (playing|facing)|will i win|my chances)\b", lower) and not players:
        return _answer_matchup(ctx), "matchup", [], ctx

    if re.search(r"\b(waiver|waivers|pick ?up|free agent|available|add)\b", lower) and position and position != "DST":
        if ctx.league is None:
            return "Connect a league first so I know which players are available.", "waiver", [], ctx
        rows = _top_projected(position, ctx, exclude_rostered=True)
        if not rows:
            return f"I don't have Week {ctx.week} projections for available {position}s yet.", "waiver", [], ctx
        return _format_top(position, rows, ctx, "Best available by projection"), "waiver", [], ctx

    if len(players) >= 2 and re.search(r"\b(compare|start|sit|or|versus|vs\.?|better|between)\b", lower):
        answer = _compare_with_projections(players[0], players[1], ctx)
        return answer or _compare_players(players), "compare", players, ctx

    if players:
        if re.search(r"\b(recent|recently|performed|performance|lately|last|history)\b", lower):
            text = _player_summary(players[0]) + "\n\n" + _projection_summary(players[0], ctx, include_recent=False)
        elif re.search(r"\b(overview|summary|upside|downside|value|role|consistent|consistency|inconsistent|outlook|boom|bust)\b", lower):
            from .player_profiles import build_player_profile, profile_overview_text
            profile = build_player_profile(players[0], ctx.league, ctx.week)
            text = profile_overview_text(profile, include_estimates=bool(re.search(r'\b(boom|bust)\b', lower)))
        else:
            text = _projection_summary(players[0], ctx)
        return text, "player", players[:1], ctx

    if re.search(r"\b(top|best|rank|leaders|who are the)\b", lower) and position in SKILL_POSITIONS + ("K",):
        rows = _top_projected(position, ctx)
        if rows:
            return _format_top(position, rows, ctx, "Top projected"), "top", [], ctx

    return _answer_from_history(q), "fallback", [], ctx


def answer_with_state(question, user=None, league=None, state=None, connection=None):
    """Answer a question, using and updating a small conversation state.

    `state` is a JSON-serialisable dict (kept in the Django session). Returns
    (answer_text, new_state).
    """
    state = dict(state or {})
    league_id = getattr(league, "pk", None)
    connection_id = getattr(connection, "pk", None)
    if state.get("league_id") != league_id or state.get("connection_id") != connection_id:
        state = {}

    q = question.strip()
    resolved, detail, clarification = _resolve_follow_up(q, state)
    if clarification:
        return clarification, state

    text, topic, players, ctx = _route(resolved, user, league, detail=detail, connection=connection)
    if ctx is not None and ctx.cache.pop("truncated", False) and not ctx.detail:
        text += "\n\nAsk “why” for more detail."

    if topic in {"greeting", "fallback"}:
        return text, state  # keep the previous context so the next follow-up still works
    new_state = {
        "last_question": resolved,
        "topic": topic,
        "week": ctx.week if ctx else None,
        "players": [p.full_name for p in players],
        "league_id": league_id,
        "connection_id": connection_id,
    }
    return text, new_state


def answer_question(question, user=None, league=None, connection=None):
    """Stateless convenience wrapper (no follow-up memory)."""
    return answer_with_state(question, user=user, league=league, connection=connection)[0]
