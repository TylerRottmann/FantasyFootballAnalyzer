from django.urls import path

from . import views
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
]
