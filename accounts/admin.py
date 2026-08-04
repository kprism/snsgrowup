from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("SNSGROWUP", {"fields": ("display_name", "account_type")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("SNSGROWUP", {"fields": ("email", "display_name", "account_type")}),)
    list_display = ("email", "display_name", "account_type", "is_staff", "is_active")
