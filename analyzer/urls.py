# analyzer/urls.py
from django.urls import path
from .views import SignUpView, adp_rankings

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('adp/', adp_rankings, name='adp_rankings'),
]