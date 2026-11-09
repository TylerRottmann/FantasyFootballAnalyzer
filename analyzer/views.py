import logging

from django.contrib.auth.decorators import login_required
from django.db import models
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import CustomUserCreationForm, ProfileForm, SettingsForm
from .models import Players, PlayerWeeklyStats, Teams
from .assistant_gm import answer_with_state

logger = logging.getLogger(__name__)

def home(request):
    return render(request, "home.html")



def adp_rankings(request):
    fantasy_positions = ("QB", "RB", "WR", "K")
    scoring_formats = (
        ("ppr", "Full PPR"),
        ("half_ppr", "Half PPR"),
        ("std", "Standard"),
    )
    season = 2026

    scoring_format = request.GET.get("scoring", "ppr").strip().lower()
    valid_formats = {value for value, _ in scoring_formats}
    if scoring_format not in valid_formats:
        scoring_format = "ppr"

    position = request.GET.get("position", "").strip().upper()
    team = request.GET.get("team", "").strip()
    search = request.GET.get("search", "").strip()

    players = (
        Players.objects
        .filter(
            position__in=fantasy_positions,
            adp_rankings__season=season,
            adp_rankings__scoring_format=scoring_format,
        )
        .exclude(full_name__isnull=True)
        .exclude(full_name="")
        .select_related("team")
        .annotate(adp_value=models.F("adp_rankings__adp"))
    )

    if position in fantasy_positions:
        players = players.filter(position=position)
    else:
        position = ""

    if team:
        if team.isdecimal():
            players = players.filter(team_id=int(team))
        else:
            team = ""

    if search:
        players = players.filter(full_name__icontains=search)

    players = players.order_by(
        "adp_rankings__adp",
        "full_name",
        "id",
    )

    teams = (
        Teams.objects
        .filter(players__position__in=fantasy_positions)
        .distinct()
        .order_by("name")
    )

    context = {
        "players": players,
        "positions": fantasy_positions,
        "teams": teams,
        "selected_position": position,
        "selected_team": team,
        "search": search,
        "scoring_formats": scoring_formats,
        "selected_scoring": scoring_format,
        "season": season,
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



@login_required
def assistant_gm_page(request):
    """Render the rule-based Assistant GM chat page."""
    request.session.pop("gm_state", None)  # a fresh page load starts a fresh conversation
    return render(request, "assistant_gm.html")


@login_required
def assistant_gm_chat(request):
    """Answer a question using local Python rules and the existing database."""
    from django.http import JsonResponse
    from django.views.decorators.http import require_POST
    from django.utils.decorators import method_decorator

    if request.method != "POST":
        return JsonResponse({"error": "Use POST to send a question."}, status=405)

    question = (request.POST.get("message") or "").strip()
    if not question:
        return JsonResponse({"error": "Please enter a question."}, status=400)
    if len(question) > 500:
        return JsonResponse({"error": "Please keep your question under 500 characters."}, status=400)

    try:
        from leagues.services.active_connection import get_active_connection
        connection = get_active_connection(request, fallback_to_recent=False)
        league = connection.league if connection else None
        response, new_state = answer_with_state(
            question, user=request.user, league=league,
            state=request.session.get("gm_state"), connection=connection,
        )
        request.session["gm_state"] = new_state
    except Exception:
        logger.exception("Assistant GM failed to answer")
        return JsonResponse(
            {"error": "I couldn't analyze that question right now. Please try again."},
            status=500,
        )
    from .assistant_gm import _find_players_in_question
    players = _find_players_in_question(response, limit=20)
    return JsonResponse({"answer": response, "week": new_state.get('week'), "players": [{'id': p.pk, 'name': p.full_name} for p in players]})
