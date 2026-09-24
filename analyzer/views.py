from django.shortcuts import render

# Create your views here.
from django.urls import reverse_lazy
from django.views.generic import CreateView
from .forms import CustomUserCreationForm
from django.shortcuts import render
from .models import Players


def home(request):
    return render(request, "home.html")
def adp_rankings(request):
    players = Players.objects.exclude(
        full_name__isnull=True
    ).exclude(
        full_name=""
    )

    position = request.GET.get("position", "")
    team = request.GET.get("team", "")
    search = request.GET.get("search", "")

    if position:
        players = players.filter(position=position)

    if team:
        players = players.filter(team_id=team)

    if search:
        players = players.filter(full_name__icontains=search)

    players = players.order_by("full_name")

    positions = (
        Players.objects
        .exclude(position__isnull=True)
        .exclude(position="")
        .values_list("position", flat=True)
        .distinct()
        .order_by("position")
    )

    teams = (
        Players.objects
        .exclude(team_id__isnull=True)
        .values_list("team_id", flat=True)
        .distinct()
        .order_by("team_id")
    )

    context = {
        "players": players,
        "positions": positions,
        "teams": teams,
        "selected_position": position,
        "selected_team": team,
        "search": search,
    }

    return render(request, "adp.html", context)

class SignUpView(CreateView):
    form_class = CustomUserCreationForm
    success_url = reverse_lazy('login')
    template_name = 'registration/signup.html'