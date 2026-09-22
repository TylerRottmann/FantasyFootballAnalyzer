from django.urls import path

from . import views


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
]