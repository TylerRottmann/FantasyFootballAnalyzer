from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    email_notifications = models.BooleanField(
        default=True
    )

    nickname = models.CharField(
        max_length=150,
        default="",
    )

    sleeper_username = models.CharField(
        max_length=150,
        default="",
    )

    yahoo_username = models.CharField(
        max_length=150,
        default="",
    )

    espn_username = models.CharField(
        max_length=150,
        default="",
    )

    def __str__(self):
        return self.username