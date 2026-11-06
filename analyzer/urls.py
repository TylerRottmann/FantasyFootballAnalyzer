from django.urls import path
from django.views.generic import RedirectView
from .views import SignUpView, profile, assistant_gm_page, assistant_gm_chat
from .market import market_long_term, market_short_term

from .waivers import waiver_wire
from .player_cards import player_card

urlpatterns = [
    path('players/<int:player_id>/card/', player_card, name='player_card'),
    path("waivers/", waiver_wire, name="waiver_wire"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("profile/", profile, name="profile"),
    path("market/", RedirectView.as_view(pattern_name="market_short_term"), name="market"),
    path("market/short-term/", market_short_term, name="market_short_term"),
    path("market/long-term/", market_long_term, name="market_long_term"),
    path("adp/", RedirectView.as_view(pattern_name="market_long_term", query_string=True), name="adp_rankings"),
    path("assistant-gm/", assistant_gm_page, name="assistant_gm"),
    path("assistant-gm/chat/", assistant_gm_chat, name="assistant_gm_chat"),
]
