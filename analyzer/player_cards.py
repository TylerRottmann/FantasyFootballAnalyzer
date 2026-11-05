from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from requests import RequestException

from leagues.models import BoomBustWeeklyPrediction, FantasyRosterPlayer, UserLeagueConnection
from leagues.services.context_processors import league_selector
from scripts.commands.nflweek import get_current_nfl_week
from .models import Players
from .player_profiles import build_player_profile


@login_required
@require_GET
def player_card(request, player_id):
    context = league_selector(request)
    player = get_object_or_404(Players.objects.select_related('team'), pk=player_id)
    league = context['active_league']
    try:
        week = int(request.GET['week']) if request.GET.get('week') else int(get_current_nfl_week())
        if not 1 <= week <= 18:
            raise ValueError
    except (ValueError, TypeError, RequestException, KeyError):
        return JsonResponse({'error': 'Choose a valid regular-season week.'}, status=400)
    context['profile'] = build_player_profile(player, league, week)

    # Saved v2 estimates are visible only for the connected user's own roster.
    if (
        league is not None
        and request.session.get('active_league_id') == league.pk
        and player.position in {'QB', 'RB', 'WR', 'TE'}
        and (
            context['profile']['boom_pct'] is None
            or context['profile']['bust_pct'] is None
        )
    ):
        connection = UserLeagueConnection.objects.filter(
            user=request.user,
            league=league,
        ).only('external_user_id').first()

        if connection and connection.external_user_id:
            authorized = FantasyRosterPlayer.objects.filter(
                roster__league=league,
                roster__owner_sleeper_id=connection.external_user_id,
                player_id=player.pk,
            ).exists()

            if authorized:
                saved_v2 = BoomBustWeeklyPrediction.objects.filter(
                    player_id=player.pk,
                    season=league.season,
                    week=week,
                    model_version='2',
                ).first()

                if saved_v2:
                    for kind in ('boom', 'bust'):
                        key = kind + '_pct'
                        probability = getattr(saved_v2, kind + '_probability')
                        if (
                            context['profile'][key] is None
                            and probability is not None
                            and 0 <= probability <= 1
                        ):
                            context['profile'][key] = round(probability * 100, 1)
    if request.GET.get('format') == 'json':
        return JsonResponse(context['profile'])
    template = 'players/card_content.html' if request.GET.get('fragment') == '1' else 'players/card_page.html'
    return render(request, template, context)
