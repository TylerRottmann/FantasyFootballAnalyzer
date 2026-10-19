def score_projection(prediction, league):
    stat_line = prediction.get("projected_stats")

    if stat_line:
        return score_stat_line(
            stat_line=stat_line,
            scoring_settings=league.scoring_settings,
        )

    if league_uses_compatible_ppr(league):
        return prediction.get("projected_fantasy_points")

    # Avoid presenting a PPR estimate as an exact custom-scoring result.
    return None