import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import CustomUserCreationForm, ProfileForm, SettingsForm
from .models import Players, PlayerWeeklyStats
from .assistant_gm import answer_question

logger = logging.getLogger(__name__)

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
        from leagues.services.context_processors import league_selector
        league = league_selector(request)["active_league"]
        response = answer_question(question, user=request.user, league=league)
    except Exception:
        logger.exception("Assistant GM failed to answer: %r", question)
        return JsonResponse(
            {"error": "I couldn't analyze that question right now. Please try again."},
            status=500,
        )
    return JsonResponse({"answer": response})
