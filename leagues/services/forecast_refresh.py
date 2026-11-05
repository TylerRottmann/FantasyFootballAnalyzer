def refresh_league_forecasts(league, first_week, last_week):
    weeks = range(first_week, last_week + 1)
    rosters = load_league_rosters_with_players(league)

    player_forecasts = forecast_all_rosters(rosters, league.season, weeks)

    team_week_rows = []
    for roster in rosters:
        for week in weeks:
            row = project_team_week(
                roster_players=roster.roster_players.all(),
                player_forecasts=player_forecasts[roster.id],
                starting_positions=league.roster_positions,
                week=week,
            )
            save_team_week_projection(league, roster, row)
            team_week_rows.append({
                "roster_id": roster.id,
                **row,
            })

    return team_week_rows