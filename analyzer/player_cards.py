from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from requests import RequestException

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
    if request.GET.get('format') == 'json':
        return JsonResponse(context['profile'])
    template = 'players/card_content.html' if request.GET.get('fragment') == '1' else 'players/card_page.html'
    return render(request, template, context)
