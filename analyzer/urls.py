from django.urls import path
from .views import SignUpView, adp_rankings, profile

urlpatterns = [
    path("signup/", SignUpView.as_view(), name="signup"),
    path("profile/", profile, name="profile"),
    path("adp/", adp_rankings, name="adp_rankings"),
]