"""RB production, workload, efficiency, and matchup features from verified tables."""

from collections import Counter, defaultdict
from datetime import date

from psycopg.rows import dict_row

from scripts.algorithm.features.qb_features import (
    average, get_connection, standard_deviation, trend,
)
from scripts.algorithm.rb.feature_names import (
    CONTEXT_WINDOWS, DEFENSE_STATS, PLAYER_WINDOWS, PRODUCTION_STATS,
    TEAM_STATS, TREND_STATS,
)


def normalize_team(abbreviation):
    # nflverse weekly stats use LA; the imported teams table uses LAR.
    return "LAR" if abbreviation == "LA" else abbreviation


def paired_rate(games, numerator, denominator):
    pairs = [
        (float(game[numerator]), float(game[denominator]))
        for game in games
        if game[numerator] is not None and game[denominator] is not None
    ]
    total = sum(pair[1] for pair in pairs)
    return sum(pair[0] for pair in pairs) / total if total else None


class RBSeasonData:
    """A bounded season snapshot, reused across training rows without global caching."""

    def __init__(self, season, player_games, team_games, teams, schedules):
        self.season = season
        self.players = defaultdict(list)
        for game in player_games:
            game = dict(game)
            game["fantasy_points"] = game["fantasy_points_ppr"]
            for name, other in (("touches", "receptions"), ("opportunities", "targets")):
                game[name] = (
                    game["carries"] + game[other]
                    if game["carries"] is not None and game[other] is not None else None
                )
            self.players[game["player_id"]].append(game)
        for games in self.players.values():
            games.sort(key=lambda game: game["week"])
        self.team_games = defaultdict(list)
        self.historical_matchups = {}
        for game in team_games:
            self.team_games[game["team_id"]].append(game)
            self.historical_matchups[(game["opponent_team_id"], game["week"])] = game
        for games in self.team_games.values():
            games.sort(key=lambda game: game["week"])
        self.team_ids = {normalize_team(team["abbreviation"]): team["id"] for team in teams}
        self.abbreviations = {team["id"]: team["abbreviation"] for team in teams}
        self.schedules = schedules
        self.schedule_counts = Counter(
            team_id for game in schedules
            for team_id in (game["home_team_id"], game["away_team_id"])
        )

    @classmethod
    def load(cls, season, player_id=None, through_week=18):
        """Read source mappings once; feature construction applies strict week cutoffs."""
        with get_connection().cursor(row_factory=dict_row) as cur:
            cur.execute("""
                WITH team_totals AS (
                    SELECT week,
                           CASE WHEN opponent_team = 'LA' THEN 'LAR'
                                ELSE opponent_team END AS opponent_team,
                           SUM(carries) AS team_carries,
                           SUM(targets) AS team_targets
                    FROM player_weekly_stats
                    WHERE season = %s AND season_type = 'REG' AND week <= %s
                    GROUP BY week, CASE WHEN opponent_team = 'LA' THEN 'LAR'
                                        ELSE opponent_team END
                )
                SELECT p.player_id, p.week, p.game_id, p.opponent_team,
                       p.carries, p.rushing_yards, p.rushing_tds,
                       p.targets, p.receptions, p.receiving_yards,
                       p.receiving_tds, p.fumbles_lost, p.fantasy_points_ppr,
                       t.team_carries, t.team_targets
                FROM player_weekly_stats p
                LEFT JOIN team_totals t ON t.week = p.week
                  AND t.opponent_team = CASE WHEN p.opponent_team = 'LA' THEN 'LAR'
                                            ELSE p.opponent_team END
                WHERE p.season = %s AND p.season_type = 'REG' AND p.week <= %s
                  AND (%s::bigint IS NULL OR p.player_id = %s)
                ORDER BY p.player_id, p.week
            """, (season, through_week, season, through_week, player_id, player_id))
            player_games = cur.fetchall()
            cur.execute("""
                SELECT team_id, week, opponent_team_id, is_home,
                       points_for, passing_yards, rushing_yards, total_yards,
                       rb_fantasy_points_allowed, rushing_yards_against,
                       passing_yards_against, points_against, total_yards_against
                FROM team_weekly_stats
                WHERE season = %s AND season_type = 1 AND week <= %s
                ORDER BY team_id, week
            """, (season, through_week))
            team_games = cur.fetchall()
            cur.execute("SELECT id, abbreviation FROM teams")
            teams = cur.fetchall()
            cur.execute("""
                SELECT week, home_team_id, away_team_id FROM nfl_games
                WHERE season = %s AND game_type = 'REG'
            """, (season,))
            schedules = cur.fetchall()
        return cls(season, player_games, team_games, teams, schedules)

    def game_context(self, player, week):
        context = {
            "game_status": "UNKNOWN", "team_id": None,
            "opponent_team_id": None, "opponent_team": None, "is_home": None,
        }
        historical = next((g for g in self.players.get(player.id, []) if g["week"] == week), None)
        if historical is not None:
            opponent = normalize_team(historical["opponent_team"])
            opponent_id = self.team_ids.get(opponent)
            context.update(opponent_team=opponent, opponent_team_id=opponent_id)
            game = self.historical_matchups.get((opponent_id, week))
            if game is not None:
                context.update(game_status="GAME", team_id=game["team_id"], is_home=game["is_home"])
                return context
            # A scheduled opponent identifies the historical team without using today's roster.
            for scheduled in self.schedules:
                if scheduled["week"] == week and opponent_id in (
                    scheduled["home_team_id"], scheduled["away_team_id"],
                ):
                    is_home = opponent_id == scheduled["away_team_id"]
                    context.update(
                        game_status="GAME", is_home=is_home,
                        team_id=scheduled["home_team_id"] if is_home else scheduled["away_team_id"],
                    )
                    return context
            # Imported nflverse game IDs encode season, week, away team, and home team.
            game_id = (historical.get("game_id") or "").split("_")
            if len(game_id) == 4 and game_id[:2] == [str(self.season), f"{week:02d}"]:
                away, home = [normalize_team(team) for team in game_id[2:]]
                if away != home and opponent in (away, home):
                    team = home if opponent == away else away
                    team_id = self.team_ids.get(team)
                    if team_id is not None and opponent_id is not None:
                        context.update(game_status="GAME", team_id=team_id, is_home=opponent == away)
                        return context
            # A missing historical team row is not evidence of a bye or a current-team matchup.
            return context
        if not self.schedules or player.team_id is None or self.season != date.today().year:
            return context
        # Do not use the current roster to fill a missing earlier game for this player.
        if any(g["week"] > week for g in self.players.get(player.id, [])):
            return context
        for game in self.schedules:
            if game["week"] != week:
                continue
            if player.team_id in (game["home_team_id"], game["away_team_id"]):
                is_home = player.team_id == game["home_team_id"]
                opponent_id = game["away_team_id"] if is_home else game["home_team_id"]
                context.update(
                    game_status="GAME", team_id=player.team_id, is_home=is_home,
                    opponent_team_id=opponent_id,
                    opponent_team=self.abbreviations.get(opponent_id),
                )
                return context
        # A missing matchup means a bye only when all 17 team games were imported.
        if self.schedule_counts[player.team_id] == 17:
            context.update(game_status="BYE", team_id=player.team_id)
        return context


def build_rb_features(player, season, week, data=None):
    """Keep target-week outcomes out of every production and matchup feature."""
    if not 1 <= week <= 18:
        raise ValueError("RB projections require a regular-season week from 1 through 18.")
    if data is None:
        data = RBSeasonData.load(season, player.id, week)
    if data.season != season:
        raise ValueError("RB feature data must match the requested season.")
    history = [g for g in data.players.get(player.id, []) if g["week"] < week]
    context = data.game_context(player, week)
    team_games = [g for g in data.team_games.get(context["team_id"], []) if g["week"] < week]
    opponent_games = [g for g in data.team_games.get(context["opponent_team_id"], []) if g["week"] < week]
    features = {
        "player_id": player.id, "season": season, "week": week, **context,
        "games_played": len(history), "games_played_l8": len(history[-8:]),
    }
    rates = {
        "rushing_yards_per_carry": ("rushing_yards", "carries"),
        "rushing_td_rate": ("rushing_tds", "carries"),
        "catch_rate": ("receptions", "targets"),
        "receiving_yards_per_target": ("receiving_yards", "targets"),
        "receiving_td_rate": ("receiving_tds", "targets"),
        "carry_share": ("carries", "team_carries"),
        "target_share": ("targets", "team_targets"),
    }
    for window in PLAYER_WINDOWS:
        games = history if window == "season" else history[-int(window[1:]):]
        for stat in PRODUCTION_STATS:
            features[f"{stat}_{window}"] = average([g[stat] for g in games])
        for stat, (numerator, denominator) in rates.items():
            features[f"{stat}_{window}"] = paired_rate(games, numerator, denominator)
        if window in CONTEXT_WINDOWS:
            for stat in ("fantasy_points", "carries", "targets", "touches"):
                features[f"{stat}_stddev_{window}"] = standard_deviation([g[stat] for g in games])
    for stat in TREND_STATS:
        features[f"{stat}_trend_l3_l8"] = trend(features[f"{stat}_l3"], features[f"{stat}_l8"])
    team_columns = ("points_for", "passing_yards", "rushing_yards", "total_yards")
    defense_columns = (
        "rb_fantasy_points_allowed", "rushing_yards_against", "passing_yards_against",
        "points_against", "total_yards_against",
    )
    for window in CONTEXT_WINDOWS:
        teams = team_games if window == "season" else team_games[-int(window[1:]):]
        opponents = opponent_games if window == "season" else opponent_games[-int(window[1:]):]
        for stat, column in zip(TEAM_STATS, team_columns):
            features[f"team_{stat}_{window}"] = average([g[column] for g in teams])
        for stat, column in zip(DEFENSE_STATS, defense_columns):
            features[f"opponent_{stat}_{window}"] = average([g[column] for g in opponents])
    features["game_environment_l3"] = average([
        features["team_points_l3"], features["opponent_points_allowed_l3"],
    ]) if all(features[n] is not None for n in ("team_points_l3", "opponent_points_allowed_l3")) else None
    return features
