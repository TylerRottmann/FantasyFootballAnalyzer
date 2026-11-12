import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import CustomUserCreationForm, ProfileForm, SettingsForm
from .assistant_gm import answer_with_state

logger = logging.getLogger(__name__)

def home(request):
    return render(request, "home.html")



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
    if request.POST.get("reset") == "1":
        request.session.pop("gm_state", None)
        return JsonResponse({"status": "reset"})
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
