from analyzer.models import NFLGame


def get_team_matchup(team_id, season, week):
    game = NFLGame.objects.filter(
        season=season,
        week=week,
        away_team_id=team_id,
    ).first()

    if game:
        return {
            "opponent": game.home_team,
            "is_home": False,
            "game": game,
        }

    game = NFLGame.objects.filter(
        season=season,
        week=week,
        home_team_id=team_id,
    ).first()

    if game:
        return {
            "opponent": game.away_team,
            "is_home": True,
            "game": game,
        }

    return None