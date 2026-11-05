"""League-scoped waiver browsing using the existing imported roster tables."""
from requests import RequestException

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.shortcuts import render

from leagues.services.context_processors import league_selector
from leagues.models import FantasyRosterPlayer
from .models import Players, Teams
from .waiver_value import load_player_values, PlayerValue
from .waiver_predictions import load_waiver_predictions, predict_waiver_player
from .waiver_moves import suggested_moves
from scripts.commands.nflweek import get_current_nfl_week


# Matches scripts/load_player_data.py; expand when the importer supports more.
FANTASY_POSITIONS = ('QB', 'RB', 'WR', 'TE')


class WaiverFilterForm(forms.Form):
    week = forms.TypedChoiceField(choices=[(w, f"Week {w}") for w in range(1, 19)], coerce=int)
    value = forms.ChoiceField(required=False, label='What do you need?', choices=[
        ('', 'All pickups'), ('long', 'Long-term value'), ('short', 'Short-term value'), ('fading', 'Fading value'), ('unknown', 'Unclear')])
    trend = forms.ChoiceField(required=False, label='Role trend', choices=[
        ('', 'Any trend'), ('long', 'Growing role'), ('declining', 'Losing work'),
        ('neutral', 'Steady role'), ('uneven', 'Uneven usage'), ('unknown', 'Still evaluating')])
    search = forms.CharField(required=False, max_length=100, label='Player name')
    position = forms.ChoiceField(
        required=False, choices=[('', 'All positions'), ('FLEX', 'WR/RB/TE')] + [(p, p) for p in FANTASY_POSITIONS],
    )
    team = forms.ModelChoiceField(
        queryset=Teams.objects.none(), required=False, empty_label='All teams', label='NFL team',
    )
    age_min = forms.IntegerField(required=False, min_value=0, max_value=100, label='Minimum age')
    age_max = forms.IntegerField(required=False, min_value=0, max_value=100, label='Maximum age')
    sort = forms.ChoiceField(choices=[
        ('week', "Selected week's projection: high to low"),
        ('season', 'Rest of season prediction: high to low'),
        ('long', 'Best long-term value'), ('short', 'Best short-term value'),
    ])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['team'].queryset = Teams.objects.order_by('abbreviation')
        self.fields['team'].label_from_instance = lambda team: f'{team.abbreviation} — {team.name}'

    def clean(self):
        data = super().clean()
        low, high = data.get('age_min'), data.get('age_max')
        if low is not None and high is not None and low > high:
            self.add_error('age_max', 'Maximum age must be at least the minimum age.')
        return data


@login_required
def waiver_wire(request):
    # Reuse the selector's authorization and fallback behavior exactly.
    context = league_selector(request)
    league = context['active_league']
    params = request.GET.copy()
    if not params.get('sort'):
        params['sort'] = 'week'
    if not params.get('week'):
        try:
            params['week'] = str(max(1, min(18, get_current_nfl_week())))
        except (RequestException, KeyError, TypeError, ValueError):
            context['week_unavailable'] = True
    form = WaiverFilterForm(params)
    context['filter_form'] = form
    context['suggested_moves'] = [{'horizon': horizon, 'title': title,
        'message': 'Choose a valid week to see suggested moves.'}
        for horizon, title in [('long', 'Long-term pickups'), ('short', 'Short-term pickups')]]
    rows = []
    has_rosters = league is not None and league.rosters.exists()
    context['has_rosters'] = has_rosters

    if league is not None and has_rosters and form.is_valid():
        rostered = FantasyRosterPlayer.objects.filter(
            roster__league_id=league.pk, player_id=OuterRef('pk'),
        )
        players = (Players.objects
            .filter(position__in=FANTASY_POSITIONS)
            .exclude(full_name__isnull=True).exclude(full_name='')
            .annotate(is_rostered=Exists(rostered)).filter(is_rostered=False)
            .select_related('team'))
        filters = form.cleaned_data
        available_players = list(players)
        connection = next(c for c in context['connected_leagues'] if c.league_id == league.pk)
        roster = (league.rosters.filter(owner_sleeper_id=connection.external_user_id).first()
            if connection.external_user_id else None)
        entries = list(roster.roster_players.filter(player_id__isnull=False).select_related('player')) if roster else []
        week = filters['week']
        forecasts = load_waiver_predictions([p.pk for p in available_players] + [e.player_id for e in entries], league, week)
        values = load_player_values(league.season, week)
        def player_row(player):
            return {'player': player, 'prediction': predict_waiver_player(player, league, week, forecasts),
                'value': values.get(player.pk, PlayerValue())}
        all_rows = {p.pk: player_row(p) for p in available_players}
        if roster:
            owned_players = {p.pk: p for p in Players.objects.filter(pk__in=[e.player_id for e in entries]).select_related('team')}
            owned = [dict(player_row(owned_players[e.player_id]), roster_slot=(e.roster_slot or '').upper()) for e in entries]
            context['suggested_moves'] = suggested_moves(list(all_rows.values()), owned, league.roster_positions or [])
        else:
            context['suggested_moves'] = [{'horizon': horizon, 'title': title,
                'message': 'Refresh your league so we can find your roster and suggest a move.'}
                for horizon, title in [('long', 'Long-term pickups'), ('short', 'Short-term pickups')]]
        if filters['position'] == 'FLEX':
            players = players.filter(position__in=('WR', 'RB', 'TE'))
        elif filters['position']:
            players = players.filter(position=filters['position'])
        if filters['team']:
            players = players.filter(team=filters['team'])
        if filters['search']:
            players = players.filter(full_name__icontains=filters['search'])
        if filters['age_min'] is not None:
            players = players.filter(age__gte=filters['age_min'])
        if filters['age_max'] is not None:
            players = players.filter(age__lte=filters['age_max'])
        players = list(players)
        week = filters['week']
        context['projection_week'] = week
        rows = [all_rows[player.pk] for player in players]
        category = filters['value'] or (filters['sort'] if filters['sort'] in ('long', 'short') else '')
        if category:
            rows = [row for row in rows if row['value'].horizon == category]
        if filters['trend']:
            rows = [row for row in rows if (row['value'].category if row['value'].category != 'short' else 'long') == filters['trend']]
        metric = 'rest_of_season' if filters['sort'] in ('season', 'long') else 'this_week'
        rows.sort(key=lambda row: (
            getattr(row['prediction'], metric) is None,
            -(getattr(row['prediction'], metric) or 0),
            -(row['prediction'].this_week or 0),
            row['player'].full_name.casefold(), row['player'].pk,
        ))

    context['page_obj'] = Paginator(rows, 50).get_page(request.GET.get('page'))
    params.pop('page', None)
    context['filter_query'] = params.urlencode()
    return render(request, 'waivers.html', context)
