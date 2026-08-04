from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import GeneralSignupForm, PressSignupForm


def signup_type(request):
    if request.user.is_authenticated:
        return redirect("home")
    return render(request, "accounts/signup_type.html")


def signup_general(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = GeneralSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")

    return render(request, "accounts/signup_general.html", {"form": form})


def signup_press(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = PressSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")

    return render(request, "accounts/signup_press.html", {"form": form})
