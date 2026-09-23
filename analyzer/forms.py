from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django import forms

from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email")


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ("username", "email", "nickname", "sleeper_username")


class SettingsForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ("email_notifications",)
        