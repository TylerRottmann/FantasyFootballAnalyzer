from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .integrations.sleeper import SleeperLeagueService
from .models import FantasyRoster, UserLeagueConnection
from django.shortcuts import redirect




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