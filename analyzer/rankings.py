from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from requests import RequestException
from leagues.services.context_processors import league_selector
from scripts.commands.nflweek import get_current_nfl_week
from .models import Players
from .waiver_predictions import load_waiver_predictions


class RankingForm(forms.Form):
    week = forms.TypedChoiceField(choices=[(w, f'Week {w}') for w in range(1,19)], coerce=int)
    position = forms.ChoiceField(required=False, choices=[('', 'All positions')] + [(p,p) for p in ('QB','RB','WR','TE','K')])


@login_required
def weekly_rankings(request):
    context = league_selector(request)
    params = request.GET.copy()
    if not params.get('week'):
        try:
            params['week'] = str(max(1,min(18,get_current_nfl_week())))
        except (RequestException, KeyError, TypeError, ValueError):
            pass
    form = RankingForm(params)
    context['form'] = form
    league = context['active_league']
    rows = []
    if league and form.is_valid():
        week = form.cleaned_data['week']
        players = Players.objects.filter(position__in=['QB','RB','WR','TE','K']).exclude(full_name__isnull=True).exclude(full_name='').select_related('team')
        if form.cleaned_data['position']:
            players = players.filter(position=form.cleaned_data['position'])
        players = list(players)
        forecasts = load_waiver_predictions([p.pk for p in players], league, week)
        rows = [{'player': p, 'points': forecasts.get((p.pk,week))} for p in players]
        rows.sort(key=lambda r: (r['points'] is None, -(r['points'] or 0), r['player'].full_name.casefold(), r['player'].pk))
        context['week'] = week
    context['page_obj'] = Paginator(rows,50).get_page(request.GET.get('page'))
    params.pop('page',None)
    context['filter_query'] = params.urlencode()
    return render(request,'weekly_rankings.html',context)
