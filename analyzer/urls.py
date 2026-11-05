from django.urls import path
from .views import SignUpView, adp_rankings, profile, assistant_gm_page, assistant_gm_chat

from .waivers import waiver_wire
from .player_cards import player_card

urlpatterns = [
    path('players/<int:player_id>/card/', player_card, name='player_card'),
    path("waivers/", waiver_wire, name="waiver_wire"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("profile/", profile, name="profile"),
    path("adp/", adp_rankings, name="adp_rankings"),
    path("assistant-gm/", assistant_gm_page, name="assistant_gm"),
    path("assistant-gm/chat/", assistant_gm_chat, name="assistant_gm_chat"),
]
