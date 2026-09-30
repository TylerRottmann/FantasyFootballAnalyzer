from django.urls import path
from .views import SignUpView, adp_rankings, profile

from .waivers import waiver_wire

urlpatterns = [
    path("waivers/", waiver_wire, name="waiver_wire"),
    path("signup/", SignUpView.as_view(), name="signup"),
    path("profile/", profile, name="profile"),
    path("adp/", adp_rankings, name="adp_rankings"),
]