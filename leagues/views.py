from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .integrations.sleeper import SleeperLeagueService
from .models import FantasyRoster, UserLeagueConnection
from django.shortcuts import redirect
from django.contrib import messages

import secrets

from leagues.integrations.yahoo import YahooLeagueService




@login_required
def connect_league(request):
    context = {}

    if request.method == "POST":
        platform = request.POST.get("platform")
        platform_username = request.POST.get(
            "platform_username", ""
        ).strip()
        league_identifier = request.POST.get(
            "league_identifier", ""
        ).strip()

        if platform == "sleeper":
            try:
                service = SleeperLeagueService(league_identifier)

                result = service.import_league(
                    request.user,
                    platform_username=platform_username,
                )

                connection = UserLeagueConnection.objects.get(
                    user=request.user,
                    league=result["league"],
                )

                roster = FantasyRoster.objects.filter(
                    league=result["league"],
                    owner_sleeper_id=connection.external_user_id,
                ).first()

                if roster is None:
                    context["error"] = (
                        "The league was imported, but your roster "
                        "could not be found."
                    )
                else:
                    context["success"] = (
                        f"Successfully connected {result['league'].name}!"
                    )

            except Exception as e:
                context["error"] = str(e)

        else:
            context["error"] = "Please select a supported platform."

    context["connected_leagues"] = (
        UserLeagueConnection.objects
        .filter(user=request.user)
        .select_related("league")
        .order_by("-league__updated_at")
    )

    return render(
        request,
        "leagues/connect.html",
        context,
    )

@login_required
def select_league(request, league_id):
    connection = (
        UserLeagueConnection.objects
        .filter(
            user=request.user,
            league_id=league_id,
        )
        .first()
    )

    if connection is None:
        return redirect("connect_league")

    request.session["active_league_id"] = connection.league.id

    return redirect(request.META.get("HTTP_REFERER", "/"))

@login_required
def yahoo_connect(request):
    state = secrets.token_urlsafe(32)

    request.session["yahoo_oauth_state"] = state

    authorization_url = (
        YahooLeagueService.build_authorization_url(state)
    )

    return redirect(authorization_url)

@login_required
def yahoo_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")

    expected_state = request.session.pop(
        "yahoo_oauth_state",
        None,
    )

    if not state or state != expected_state:
        messages.error(
            request,
            "Yahoo authorization failed: invalid state.",
        )
        return redirect("/")

    if not code:
        error = request.GET.get(
            "error",
            "unknown_error",
        )

        messages.error(
            request,
            f"Yahoo authorization failed: {error}.",
        )

        return redirect("/")

    # Token exchange will go here next.
    return redirect("/")