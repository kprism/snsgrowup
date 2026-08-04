from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class AccountType(models.TextChoices):
        GENERAL = "general", "일반 계정 사용자"
        PRESS = "press", "신문사 사용자"

    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "display_name", "account_type"]
