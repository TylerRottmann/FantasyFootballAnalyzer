"""League-scoped waiver browsing using the existing imported roster tables."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.shortcuts import render

from leagues.context_processors import league_selector
from leagues.models import FantasyRosterPlayer
from .models import Players, Teams
from .waiver_predictions import predict_waiver_player


# Matches scripts/load_player_data.py; expand when the importer supports more.
FANTASY_POSITIONS = ('QB', 'RB', 'WR', 'TE')


class WaiverFilterForm(forms.Form):
    search = forms.CharField(required=False, max_length=100, label='Player name')
    position = forms.ChoiceField(
        required=False, choices=[('', 'All positions')] + [(p, p) for p in FANTASY_POSITIONS],
    )
    team = forms.ModelChoiceField(
        queryset=Teams.objects.none(), required=False, empty_label='All teams', label='NFL team',
    )
    age_min = forms.IntegerField(required=False, min_value=0, max_value=100, label='Minimum age')
    age_max = forms.IntegerField(required=False, min_value=0, max_value=100, label='Maximum age')
    sort = forms.ChoiceField(choices=[
        ('week', "This week's prediction: high to low"),
        ('season', 'Rest of season prediction: high to low'),
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
    form = WaiverFilterForm(params)
    context['filter_form'] = form
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
        if filters['position']:
            players = players.filter(position=filters['position'])
        if filters['team']:
            players = players.filter(team=filters['team'])
        if filters['search']:
            players = players.filter(full_name__icontains=filters['search'])
        if filters['age_min'] is not None:
            players = players.filter(age__gte=filters['age_min'])
        if filters['age_max'] is not None:
            players = players.filter(age__lte=filters['age_max'])
        rows = [
            {'player': player, 'prediction': predict_waiver_player(player, league)}
            for player in players
        ]
        metric = 'rest_of_season' if filters['sort'] == 'season' else 'this_week'
        rows.sort(key=lambda row: (
            -getattr(row['prediction'], metric), row['player'].full_name.casefold(), row['player'].pk,
        ))

    context['page_obj'] = Paginator(rows, 50).get_page(request.GET.get('page'))
    params.pop('page', None)
    context['filter_query'] = params.urlencode()
    return render(request, 'waivers.html', context)
