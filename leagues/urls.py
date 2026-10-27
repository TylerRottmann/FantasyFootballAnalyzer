from django.urls import path

from . import views
from .trades import views as trade_views
from .views import yahoo_callback, yahoo_connect


urlpatterns = [
    path(
        "connect/",
        views.connect_league,
        name="connect_league",
    ),

    path(
        "select/<int:league_id>/",
        views.select_league,
        name="select_league",
    ),

    path(
        "start-sit/",
        views.start_sit,
        name="start_sit",
    ),
    path(
        "projection-details/<int:player_id>/",
        views.projection_details,
        name="projection_details",
    ),

    path(
        "yahoo/connect/",
        yahoo_connect,
        name="yahoo_connect",
    ),

    path(
        "yahoo/callback/",
        yahoo_callback,
        name="yahoo_callback",
    ),
    path(
        "resync/",
        views.resync_league,
        name="resync_league"
    ),
    path("trades/", trade_views.trades, name="trades"),
    path("trades/suggestions/", trade_views.trade_suggestions, name="trade_suggestions"),
    path("trades/player-search/", trade_views.trade_player_search, name="trade_player_search"),
    path("trades/calculate/", trade_views.trade_calculate, name="trade_calculate"),
    path(
        "<int:league_id>/power-rankings/",
        views.power_rankings,
        name="power_rankings",
    ),
    path(
        "<int:league_id>/power-rankings/sync/",
        views.sync_matchups,
        name="sync_matchups",
    ),
    path(
        "<int:league_id>/teams/<int:roster_id>/",
        views.team_breakdown,
        name="team_breakdown",
    ),
]
