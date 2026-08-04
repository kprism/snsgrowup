from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import PublishingBatch


@login_required
def batch_list(request):
    batches = (
        PublishingBatch.objects.filter(owner=request.user)
        .prefetch_related("contents", "channels__platform")
        .order_by("-created_at")
    )
    return render(request, "publishing/batch_list.html", {"batches": batches})
