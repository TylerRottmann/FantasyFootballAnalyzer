"""Validate scheduled NFL imports against the games expected to have finished."""
import nflreadpy as nfl
import polars as pl


def team_code(code):
    return "LAR" if code == "LA" else code


def completed_games(season, through_week):
    if not 1 <= through_week <= 18:
        raise ValueError("Completed week must be between 1 and 18.")
    games = nfl.load_schedules(seasons=[season]).filter(pl.col("game_type") == "REG")
    if len(games) != 272:
        raise ValueError("NFL schedule does not contain 272 regular-season games.")
    rows = games.filter(pl.col("week") <= through_week).to_dicts()
    if (
        {game["week"] for game in rows} != set(range(1, through_week + 1))
        or any(game["home_score"] is None or game["away_score"] is None for game in rows)
    ):
        raise ValueError(f"NFL schedule has unfinished or missing games through Week {through_week}.")
    return rows


def require_team_coverage(games, rows, source, *team_fields):
    expected = {
        (game["week"], team_code(game[field]))
        for game in games for field in ("home_team", "away_team")
    }
    actual = {
        (row["week"], team_code(row[field]))
        for row in rows for field in team_fields
    }
    missing = expected - actual
    if missing:
        raise ValueError(f"{source} is missing {len(missing)} team-weeks: {sorted(missing)}")


def regular_through(frame, week, phase_column="season_type"):
    return frame.filter((pl.col(phase_column) == "REG") & pl.col("week").is_between(1, week))
