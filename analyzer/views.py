from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import CustomUserCreationForm, ProfileForm, SettingsForm
from .models import Players, Teams

def home(request):
    return render(request, "home.html")


def adp_rankings(request):
    players = (
        Players.objects
        .select_related("team")
        .exclude(full_name__isnull=True)
        .exclude(full_name="")
    )

    position = request.GET.get("position", "")
    team = request.GET.get("team", "")
    age = request.GET.get("age", "")
    search = request.GET.get("search", "")

    if position:
        players = players.filter(position=position)

    if team:
        players = players.filter(team_id=team)

    if age:
        players = players.filter(age=age)

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
        Teams.objects
        .filter(is_active=True)
        .order_by("abbreviation")
    )

    ages = (
        Players.objects
        .exclude(age__isnull=True)
        .values_list("age", flat=True)
        .distinct()
        .order_by("age")
    )

    context = {
        "players": players,
        "positions": positions,
        "teams": teams,
        "ages": ages,
        "selected_position": position,
        "selected_team": team,
        "selected_age": age,
        "search": search,
    }

    return render(request, "adp.html", context)

class SignUpView(CreateView):
    form_class = CustomUserCreationForm
    success_url = reverse_lazy("login")
    template_name = "registration/signup.html"


@login_required
def profile(request):
    profile_form = ProfileForm(instance=request.user)
    settings_form = SettingsForm(instance=request.user)

    if request.method == "POST":
        form_type = request.POST.get("form_type")

        if form_type == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user)

            if profile_form.is_valid():
                profile_form.save()
                return redirect("profile")

        elif form_type == "settings":
            settings_form = SettingsForm(request.POST, instance=request.user)

            if settings_form.is_valid():
                settings_form.save()
                return redirect("profile")

    return render(
        request,
        "profile.html",
        {
            "profile_form": profile_form,
            "settings_form": settings_form,
        },
    )
