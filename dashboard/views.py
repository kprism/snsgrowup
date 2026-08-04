from django.shortcuts import render


def home(request):
    context = {"account_type": None, "press_profile": None}
    if request.user.is_authenticated:
        context["account_type"] = request.user.account_type
        if request.user.account_type == "press":
            context["press_profile"] = getattr(request.user, "press_profile", None)
    return render(request, "dashboard/index.html", context)
