from django.urls import path

from . import views
from .views import yahoo_connect, yahoo_callback

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
        "yahoo/connect/",
        yahoo_connect,
        name="yahoo_connect",
    ),
    path(
        "yahoo/callback/",
        yahoo_callback,
        name="yahoo_callback",
    ),
]